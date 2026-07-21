"""User-scoped singleton broker for the persistent ChatGPT Web browser."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any


BROKER_PROTOCOL = 1
BROKER_VERSION = "0.6.7"
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class BrokerTransportError(RuntimeError):
    def __init__(self, message: str, request_sent: bool = False):
        super().__init__(message)
        self.request_sent = request_sent


def resolve_profile_dir(config: dict[str, Any]) -> Path:
    web = config.get("web_adapter", {})
    workspace = Path(config.get("_workspace_root") or Path.cwd())
    raw = web.get("user_data_dir") or web.get("profile_dir") or ".chatgpt-web-browser"
    path = Path(os.path.expandvars(os.path.expanduser(str(raw)))).expanduser()
    return path if path.is_absolute() else (workspace / path).resolve()


def resolve_state_dir(config: dict[str, Any]) -> Path:
    broker = config.get("browser_broker", {})
    raw = os.getenv("WEB_BRIDGE_BROKER_STATE_DIR") or broker.get("state_dir")
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(str(raw)))).expanduser().resolve()
    return resolve_profile_dir(config).parent / "state" / "browser-broker"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _project_label(project_root: str | None) -> str:
    if not project_root:
        return "<none>"
    normalized = os.path.normcase(os.path.abspath(os.path.expanduser(project_root)))
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:12]


class BrowserBrokerClient:
    """Small IPC proxy used by every MCP process."""

    def __init__(self, config: dict[str, Any], logger=None):
        self.config = config
        self.logger = logger
        broker = config.get("browser_broker", {})
        self.state_dir = resolve_state_dir(config)
        self.state_file = self.state_dir / "broker.json"
        self.start_lock = self.state_dir / "start.lock"
        self.startup_timeout = max(2.0, float(broker.get("startup_timeout_seconds", 20)))
        self.request_timeout = max(5.0, float(broker.get("request_timeout_seconds", 660)))

    def _state(self) -> dict[str, Any] | None:
        state = _read_json(self.state_file)
        if not state:
            return None
        try:
            if not state.get("token") or int(state.get("port", 0)) <= 0:
                return None
        except (TypeError, ValueError):
            return None
        return state

    def _exchange(
        self,
        state: dict[str, Any],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        request = dict(payload)
        request["token"] = state["token"]
        request["protocol"] = BROKER_PROTOCOL
        wire = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(wire) > MAX_MESSAGE_BYTES:
            raise BrokerTransportError("request_too_large", request_sent=False)
        sent = False
        try:
            with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=min(timeout, 5.0)) as connection:
                connection.settimeout(timeout)
                connection.sendall(wire)
                sent = True
                response = bytearray()
                while len(response) <= MAX_MESSAGE_BYTES:
                    chunk = connection.recv(min(65536, MAX_MESSAGE_BYTES + 1 - len(response)))
                    if not chunk:
                        break
                    response.extend(chunk)
                    if b"\n" in chunk:
                        break
        except (OSError, TimeoutError) as exc:
            raise BrokerTransportError(f"{type(exc).__name__}: {exc}", request_sent=sent) from exc
        line = bytes(response).split(b"\n", 1)[0]
        if not line:
            raise BrokerTransportError("empty_broker_response", request_sent=sent)
        try:
            decoded = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise BrokerTransportError("invalid_broker_response", request_sent=sent) from exc
        if not isinstance(decoded, dict):
            raise BrokerTransportError("invalid_broker_response_type", request_sent=sent)
        return decoded

    def _ping(self, state: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = self._exchange(state, {"op": "ping"}, timeout=1.5)
            return response if response.get("ok") else None
        except BrokerTransportError:
            return None

    @staticmethod
    def _compatible(response: dict[str, Any]) -> bool:
        return int(response.get("protocol", -1)) == BROKER_PROTOCOL and response.get("version") == BROKER_VERSION

    def _launcher_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        entry = self.config.get("_server_entry_path")
        if not entry:
            raise BrokerTransportError("server_entry_path_missing", request_sent=False)
        return [sys.executable, str(entry)]

    def _spawn(self) -> None:
        config_path = self.config.get("_config_path")
        if not config_path:
            raise BrokerTransportError("config_path_missing", request_sent=False)
        command = [*self._launcher_command(), "--browser-broker", "--config", str(config_path)]
        environment = os.environ.copy()
        environment["WEB_BRIDGE_BROKER_PROCESS"] = "1"
        options: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
            "env": environment,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)

    def _remove_stale_state(self, state: dict[str, Any] | None) -> None:
        if state and _process_alive(int(state.get("pid", 0))):
            return
        try:
            self.state_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _ensure_server(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            state = self._state()
            ping = self._ping(state) if state else None
            if ping and self._compatible(ping):
                return state
            if ping and not self._compatible(ping):
                try:
                    self._exchange(state, {"op": "shutdown", "force": False}, timeout=5.0)
                except BrokerTransportError:
                    pass
                time.sleep(0.15)
                continue

            acquired = False
            try:
                descriptor = os.open(self.start_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump({"pid": os.getpid(), "created_at": time.time()}, stream)
                acquired = True
            except FileExistsError:
                lock = _read_json(self.start_lock) or {}
                age = time.time() - float(lock.get("created_at", 0) or 0)
                if age > self.startup_timeout and not _process_alive(int(lock.get("pid", 0) or 0)):
                    try:
                        self.start_lock.unlink()
                    except OSError:
                        pass
                time.sleep(0.1)
                continue

            if acquired:
                try:
                    state = self._state()
                    ping = self._ping(state) if state else None
                    if ping and self._compatible(ping):
                        return state
                    if state and _process_alive(int(state.get("pid", 0))):
                        raise BrokerTransportError(
                            f"broker_unresponsive pid={state.get('pid')}", request_sent=False
                        )
                    self._remove_stale_state(state)
                    self._spawn()
                    while time.monotonic() < deadline:
                        state = self._state()
                        ping = self._ping(state) if state else None
                        if ping and self._compatible(ping):
                            return state
                        time.sleep(0.1)
                finally:
                    try:
                        self.start_lock.unlink(missing_ok=True)
                    except OSError:
                        pass
        raise BrokerTransportError("broker_start_timeout", request_sent=False)

    @staticmethod
    def _web_error(stage: str, reason: str, sent: str, retryable: bool) -> str:
        return "\n".join(
            [
                "[WEB_ERROR]",
                f"stage={stage}",
                f"reason={reason}",
                f"web_prompt_sent={sent}",
                f"retryable={str(retryable).lower()}",
            ]
        )

    def _query_sync(self, prompt: str, project_root: str | None, conversation_mode: str, request_origin: str) -> str:
        request_id = uuid.uuid4().hex
        try:
            state = self._ensure_server()
        except BrokerTransportError as exc:
            return self._web_error("browser.broker.start", str(exc), "false", True)
        payload = {
            "op": "query",
            "request_id": request_id,
            "prompt": prompt,
            "project_root": project_root,
            "conversation_mode": conversation_mode,
            "request_origin": request_origin,
        }
        try:
            response = self._exchange(state, payload, timeout=self.request_timeout)
        except BrokerTransportError as exc:
            if exc.request_sent:
                return self._web_error("browser.broker.response", str(exc), "unknown", False)
            self._remove_stale_state(state)
            try:
                response = self._exchange(self._ensure_server(), payload, timeout=self.request_timeout)
            except BrokerTransportError as retry_exc:
                sent = "unknown" if retry_exc.request_sent else "false"
                return self._web_error("browser.broker.transport", str(retry_exc), sent, not retry_exc.request_sent)
        if not response.get("ok"):
            return self._web_error("browser.broker", str(response.get("error", "unknown_error")), "false", True)
        return str(response.get("result", ""))

    async def query(self, prompt: str, project_root: str | None, conversation_mode: str, request_origin: str = "interactive") -> str:
        return await asyncio.to_thread(self._query_sync, prompt, project_root, conversation_mode, request_origin)

    def call_sync(self, method: str, **kwargs: Any) -> Any:
        state = self._ensure_server()
        response = self._exchange(
            state,
            {
                "op": "call",
                "request_id": uuid.uuid4().hex,
                "method": method,
                "kwargs": kwargs,
            },
            timeout=self.request_timeout,
        )
        if not response.get("ok"):
            raise BrokerTransportError(str(response.get("error", "broker_call_failed")), request_sent=True)
        return response.get("result")

    async def call(self, method: str, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.call_sync, method, **kwargs)

    def status(self) -> str:
        state = self._state()
        if not state:
            return "BRIDGE_BROWSER_STATUS_OK\nbroker_alive=false\nbroker_pid=<none>"
        try:
            response = self._exchange(state, {"op": "status"}, timeout=2.5)
        except BrokerTransportError as exc:
            return f"BRIDGE_BROWSER_STATUS_FAILED\nbroker_alive=false\nreason={exc}"
        return str(response.get("result", "BRIDGE_BROWSER_STATUS_FAILED\nreason=empty_status"))

    def _shutdown_sync(self) -> str:
        state = self._state()
        if not state:
            return "BRIDGE_BROWSER_SHUTDOWN_OK\nbroker_was_alive=false"
        try:
            response = self._exchange(state, {"op": "shutdown", "force": False}, timeout=10.0)
        except BrokerTransportError as exc:
            self._remove_stale_state(state)
            return f"BRIDGE_BROWSER_SHUTDOWN_FAILED\nreason={exc}"
        if not response.get("ok"):
            return f"BRIDGE_BROWSER_SHUTDOWN_DEFERRED\nreason={response.get('error', 'broker_busy')}"
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and _process_alive(int(state.get("pid", 0))):
            time.sleep(0.1)
        self._remove_stale_state(state)
        return str(response.get("result", "BRIDGE_BROWSER_SHUTDOWN_OK"))

    async def shutdown(self) -> str:
        return await asyncio.to_thread(self._shutdown_sync)


class BrowserBrokerServer:
    """Owns the browser adapter and serializes all Web requests for one user."""

    def __init__(self, config: dict[str, Any], adapter: Any):
        self.config = config
        self.adapter = adapter
        self.state_dir = resolve_state_dir(config)
        self.state_file = self.state_dir / "broker.json"
        self.owner_file = self.state_dir / "owner.lock"
        self.token = secrets.token_urlsafe(32)
        broker = config.get("browser_broker", {})
        self.idle_timeout = max(30.0, float(broker.get("idle_timeout_seconds", 1800)))
        self.queue: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future[str]] | None] = asyncio.Queue()
        self.completed: OrderedDict[str, Any] = OrderedDict()
        self.inflight: dict[str, asyncio.Future[Any]] = {}
        self.state_lock = asyncio.Lock()
        self.shutdown_event = asyncio.Event()
        self.started_at = time.time()
        self.last_activity = time.monotonic()
        self.active_request_id = ""
        self.active_project = "<none>"
        self.processed_requests = 0
        self.max_queue_depth = 0

    def _claim_owner(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.owner_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            owner = _read_json(self.owner_file) or {}
            if _process_alive(int(owner.get("pid", 0) or 0)):
                raise RuntimeError(f"browser broker already running pid={owner.get('pid')}")
            self.owner_file.unlink(missing_ok=True)
            descriptor = os.open(self.owner_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "created_at": time.time()}, stream)

    async def _submit_query(self, request: dict[str, Any]) -> Any:
        request_id = str(request.get("request_id") or uuid.uuid4().hex)
        async with self.state_lock:
            if request_id in self.completed:
                return self.completed[request_id]
            future = self.inflight.get(request_id)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self.inflight[request_id] = future
                await self.queue.put((request_id, request, future))
                self.max_queue_depth = max(self.max_queue_depth, self.queue.qsize())
        return await asyncio.shield(future)

    async def _worker(self) -> None:
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            request_id, request, future = item
            self.active_request_id = request_id
            self.active_project = _project_label(request.get("project_root"))
            self.last_activity = time.monotonic()
            try:
                if request.get("op") == "query":
                    result = await self.adapter.query(
                        str(request.get("prompt", "")),
                        project_root=request.get("project_root"),
                        conversation_mode=str(request.get("conversation_mode") or "reuse_or_create"),
                        request_origin=str(request.get("request_origin") or "interactive"),
                    )
                else:
                    method_name = str(request.get("method", ""))
                    allowed = {
                        "run_chrome_preflight",
                        "chrome_smoke_test",
                        "chrome_lifecycle_test",
                        "bridge_tab_health_check",
                        "bridge_close_extra_tabs",
                    }
                    if method_name not in allowed:
                        raise ValueError(f"broker method is not allowed: {method_name}")
                    method = getattr(self.adapter, method_name)
                    result = method(**dict(request.get("kwargs") or {}))
                    if inspect.isawaitable(result):
                        result = await result
            except Exception as exc:
                result = "\n".join(
                    ["[WEB_ERROR]", "stage=browser.broker.worker", f"reason={type(exc).__name__}: {exc}"]
                )
            self.processed_requests += 1
            self.last_activity = time.monotonic()
            async with self.state_lock:
                self.inflight.pop(request_id, None)
                self.completed[request_id] = result
                while len(self.completed) > 64:
                    self.completed.popitem(last=False)
            if not future.done():
                future.set_result(result)
            self.active_request_id = ""
            self.active_project = "<none>"
            self.queue.task_done()

    def _status(self) -> str:
        adapter_status = self.adapter.browser_status() if hasattr(self.adapter, "browser_status") else "adapter_status=<unavailable>"
        return "\n".join(
            [
                "BRIDGE_BROWSER_STATUS_OK",
                "broker_alive=true",
                f"broker_pid={os.getpid()}",
                f"broker_protocol={BROKER_PROTOCOL}",
                f"broker_version={BROKER_VERSION}",
                f"queue_depth={self.queue.qsize()}",
                f"active_request_id={self.active_request_id or '<none>'}",
                f"active_project_key={self.active_project}",
                f"processed_requests={self.processed_requests}",
                f"max_queue_depth={self.max_queue_depth}",
                f"uptime_seconds={int(time.time() - self.started_at)}",
                adapter_status,
            ]
        )

    async def _write_response(self, writer: asyncio.StreamWriter, response: dict[str, Any]) -> None:
        writer.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        await writer.drain()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        shutdown_after_reply = False
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not line or len(line) > MAX_MESSAGE_BYTES:
                await self._write_response(writer, {"ok": False, "error": "invalid_request_size"})
                return
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            if not hmac.compare_digest(str(request.get("token", "")), self.token):
                await self._write_response(writer, {"ok": False, "error": "unauthorized"})
                return
            if int(request.get("protocol", -1)) != BROKER_PROTOCOL:
                await self._write_response(writer, {"ok": False, "error": "protocol_mismatch"})
                return
            operation = request.get("op")
            if operation == "ping":
                response = {"ok": True, "protocol": BROKER_PROTOCOL, "version": BROKER_VERSION, "pid": os.getpid()}
            elif operation == "status":
                response = {"ok": True, "result": self._status()}
            elif operation == "query":
                result = await self._submit_query(request)
                response = {"ok": True, "result": result}
            elif operation == "call":
                result = await self._submit_query(request)
                response = {"ok": True, "result": result}
            elif operation == "shutdown":
                if self.active_request_id or self.queue.qsize():
                    response = {"ok": False, "error": "broker_busy"}
                else:
                    response = {"ok": True, "result": "BRIDGE_BROWSER_SHUTDOWN_OK\nbroker_was_alive=true"}
                    shutdown_after_reply = True
            else:
                response = {"ok": False, "error": "unknown_operation"}
            await self._write_response(writer, response)
        except Exception as exc:
            try:
                await self._write_response(writer, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            if shutdown_after_reply:
                self.shutdown_event.set()

    async def _idle_watch(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(1.0)
            if not self.active_request_id and not self.queue.qsize() and time.monotonic() - self.last_activity >= self.idle_timeout:
                self.shutdown_event.set()

    async def run(self) -> None:
        self._claim_owner()
        server: asyncio.AbstractServer | None = None
        worker: asyncio.Task[None] | None = None
        idle: asyncio.Task[None] | None = None
        try:
            server = await asyncio.start_server(self._handle, "127.0.0.1", 0, limit=MAX_MESSAGE_BYTES)
            port = int(server.sockets[0].getsockname()[1])
            _atomic_json(
                self.state_file,
                {
                    "pid": os.getpid(),
                    "port": port,
                    "token": self.token,
                    "protocol": BROKER_PROTOCOL,
                    "version": BROKER_VERSION,
                    "started_at": time.time(),
                },
            )
            worker = asyncio.create_task(self._worker())
            idle = asyncio.create_task(self._idle_watch())
            await self.shutdown_event.wait()
            server.close()
            await server.wait_closed()
            await self.queue.put(None)
            await worker
            if hasattr(self.adapter, "shutdown_browser"):
                await self.adapter.shutdown_browser()
        finally:
            if idle:
                idle.cancel()
            if worker and not worker.done():
                worker.cancel()
            if server:
                server.close()
            state = _read_json(self.state_file)
            if state and int(state.get("pid", 0)) == os.getpid():
                self.state_file.unlink(missing_ok=True)
            self.owner_file.unlink(missing_ok=True)
