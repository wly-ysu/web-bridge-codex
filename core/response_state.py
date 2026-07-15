"""Request-scoped response state machine for ChatGPT Web turns."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def normalize_turn_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def text_fingerprint(value: str) -> str:
    normalized = normalize_turn_text(value)
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()


class ResponseState(str, Enum):
    USER_TURN_PENDING = "USER_TURN_PENDING"
    ASSISTANT_TURN_PENDING = "ASSISTANT_TURN_PENDING"
    ASSISTANT_TURN_ACTIVE = "ASSISTANT_TURN_ACTIVE"
    ASSISTANT_TURN_SETTLING = "ASSISTANT_TURN_SETTLING"
    COMPLETED = "COMPLETED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    NETWORK_FAILED = "NETWORK_FAILED"
    PAGE_CRASHED = "PAGE_CRASHED"
    PAGE_CLOSED = "PAGE_CLOSED"
    TURN_ASSOCIATION_FAILED = "TURN_ASSOCIATION_FAILED"
    OBSERVER_FAILED = "OBSERVER_FAILED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


FAILURE_STATES = frozenset(
    {
        ResponseState.LOGIN_REQUIRED,
        ResponseState.RATE_LIMITED,
        ResponseState.RETRY_REQUIRED,
        ResponseState.NETWORK_FAILED,
        ResponseState.PAGE_CRASHED,
        ResponseState.PAGE_CLOSED,
        ResponseState.TURN_ASSOCIATION_FAILED,
        ResponseState.OBSERVER_FAILED,
        ResponseState.DEADLINE_EXCEEDED,
        ResponseState.INTERNAL_ERROR,
    }
)
TERMINAL_STATES = FAILURE_STATES | {ResponseState.COMPLETED}

_FAILURE_STATE_BY_CODE = {
    "AUTH_LOGIN_REQUIRED": ResponseState.LOGIN_REQUIRED,
    "AUTH_SESSION_EXPIRED": ResponseState.LOGIN_REQUIRED,
    "USAGE_RATE_LIMITED": ResponseState.RATE_LIMITED,
    "USAGE_QUOTA_EXHAUSTED": ResponseState.RATE_LIMITED,
    "REMOTE_RETRY_REQUIRED": ResponseState.RETRY_REQUIRED,
    "REMOTE_NETWORK_ERROR": ResponseState.NETWORK_FAILED,
    "BROWSER_PAGE_CRASHED": ResponseState.PAGE_CRASHED,
    "BROWSER_CONTEXT_CLOSED": ResponseState.PAGE_CLOSED,
    "BROWSER_PAGE_CLOSED": ResponseState.PAGE_CLOSED,
    "REQUEST_USER_TURN_NOT_FOUND": ResponseState.TURN_ASSOCIATION_FAILED,
    "REQUEST_ASSISTANT_TURN_NOT_FOUND": ResponseState.TURN_ASSOCIATION_FAILED,
    "REQUEST_TURN_ASSOCIATION_AMBIGUOUS": ResponseState.TURN_ASSOCIATION_FAILED,
    "REQUEST_ASSISTANT_TURN_REPLACED": ResponseState.TURN_ASSOCIATION_FAILED,
    "OBSERVER_PROTOCOL_ERROR": ResponseState.OBSERVER_FAILED,
    "REQUEST_DEADLINE_EXCEEDED": ResponseState.DEADLINE_EXCEEDED,
}

_ALLOWED_TRANSITIONS = {
    ResponseState.USER_TURN_PENDING: {ResponseState.ASSISTANT_TURN_PENDING},
    ResponseState.ASSISTANT_TURN_PENDING: {ResponseState.ASSISTANT_TURN_ACTIVE},
    ResponseState.ASSISTANT_TURN_ACTIVE: {ResponseState.ASSISTANT_TURN_SETTLING},
    ResponseState.ASSISTANT_TURN_SETTLING: {
        ResponseState.ASSISTANT_TURN_ACTIVE,
        ResponseState.COMPLETED,
    },
}


@dataclass(frozen=True)
class TurnSnapshot:
    role: str
    key: str
    ordinal: int
    text_length: int
    text_hash: str
    request_match: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TurnSnapshot":
        return cls(
            role=str(value.get("role") or "unknown").lower(),
            key=str(value.get("key") or ""),
            ordinal=int(value.get("ordinal") or 0),
            text_length=int(value.get("textLength") or 0),
            text_hash=str(value.get("textHash") or ""),
            request_match=bool(value.get("requestMatch")),
        )


@dataclass(frozen=True)
class PageSnapshot:
    turns: tuple[TurnSnapshot, ...]
    generation_active: bool
    composer_ready: bool
    observer_alive: bool = True
    observer_sequence: int = 0
    failure_code: str | None = None
    url: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "PageSnapshot":
        raw_turns = value.get("turns", [])
        turns = tuple(
            TurnSnapshot.from_mapping(item)
            for item in raw_turns
            if isinstance(item, dict) and item.get("key")
        )
        return cls(
            turns=turns,
            generation_active=bool(value.get("generationActive")),
            composer_ready=bool(value.get("composerReady")),
            observer_alive=bool(value.get("observerAlive", True)),
            observer_sequence=int(value.get("observerSequence") or 0),
            failure_code=str(value.get("failureCode") or "") or None,
            url=str(value.get("url") or ""),
        )


@dataclass
class ResponseRequestState:
    request_id: str
    submitted_hash: str
    baseline_keys: frozenset[str]
    baseline_turn_count: int
    expected_marker: str | None
    started_at: float
    deadline_at: float
    user_turn_deadline_at: float
    settle_seconds: float
    state: ResponseState = ResponseState.USER_TURN_PENDING
    user_turn_key: str | None = None
    user_turn_ordinal: int | None = None
    assistant_turn_key: str | None = None
    assistant_turn_ordinal: int | None = None
    assistant_text_hash: str = ""
    assistant_text_length: int = 0
    settle_started_at: float | None = None
    settle_hash: str = ""
    terminal_reason: str | None = None
    error_code: str | None = None
    last_event: str = "REQUEST_CREATED"
    event_sequence: int = 0
    observer_sequence: int = 0
    missing_assistant_observations: int = 0
    assistant_rebind_count: int = 0
    last_generation_active: bool = False
    last_composer_ready: bool = False
    transitions: list[tuple[str, str, str]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        request_id: str,
        submitted_text: str,
        baseline: PageSnapshot,
        expected_marker: str | None,
        started_at: float,
        deadline_seconds: float,
        settle_seconds: float,
        user_turn_confirm_seconds: float,
    ) -> "ResponseRequestState":
        return cls(
            request_id=request_id,
            submitted_hash=text_fingerprint(submitted_text),
            baseline_keys=frozenset(turn.key for turn in baseline.turns),
            baseline_turn_count=len(baseline.turns),
            expected_marker=expected_marker,
            started_at=started_at,
            deadline_at=started_at + deadline_seconds,
            user_turn_deadline_at=min(started_at + user_turn_confirm_seconds, started_at + deadline_seconds),
            settle_seconds=settle_seconds,
        )

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def completed(self) -> bool:
        return self.state == ResponseState.COMPLETED

    def _transition(self, target: ResponseState, event: str, reason: str | None = None) -> None:
        if self.terminal:
            return
        previous = self.state
        if target == previous:
            self.last_event = event
            return
        if target not in FAILURE_STATES and target not in _ALLOWED_TRANSITIONS.get(previous, set()):
            self.state = ResponseState.INTERNAL_ERROR
            self.error_code = "INTERNAL_STATE_MACHINE_ERROR"
            self.terminal_reason = f"illegal_transition:{previous.value}->{target.value}"
            self.last_event = "ILLEGAL_TRANSITION"
            self.transitions.append((previous.value, self.state.value, self.last_event))
            return
        self.state = target
        self.last_event = event
        if reason:
            self.terminal_reason = reason
        self.transitions.append((previous.value, target.value, event))

    def fail(self, code: str, reason: str | None = None) -> None:
        if self.terminal:
            return
        target = _FAILURE_STATE_BY_CODE.get(code, ResponseState.INTERNAL_ERROR)
        self.error_code = code
        self._transition(target, code, reason or code.lower())

    def check_time(self, now: float) -> None:
        if self.terminal:
            return
        if now >= self.deadline_at:
            if self.user_turn_key is None:
                self.fail("REQUEST_USER_TURN_NOT_FOUND", "response_deadline_before_user_turn")
            elif self.assistant_turn_key is None:
                self.fail("REQUEST_ASSISTANT_TURN_NOT_FOUND", "response_deadline_before_assistant_turn")
            else:
                self.fail("REQUEST_DEADLINE_EXCEEDED", "response_deadline_exceeded")
            return
        if self.user_turn_key is None and now >= self.user_turn_deadline_at:
            self.fail("REQUEST_USER_TURN_NOT_FOUND", "submitted_user_turn_not_confirmed")
            return
        if (
            self.state == ResponseState.ASSISTANT_TURN_SETTLING
            and self.settle_started_at is not None
            and not self.last_generation_active
            and self.last_composer_ready
            and now - self.settle_started_at >= self.settle_seconds
        ):
            self._transition(ResponseState.COMPLETED, "TURN_SETTLE_TIMER_ELAPSED")

    def observe(self, snapshot: PageSnapshot, now: float) -> None:
        if self.terminal:
            return
        self.event_sequence += 1
        self.observer_sequence = max(self.observer_sequence, snapshot.observer_sequence)
        self.last_generation_active = snapshot.generation_active
        self.last_composer_ready = snapshot.composer_ready

        if snapshot.failure_code:
            self.fail(snapshot.failure_code)
            return
        if not snapshot.observer_alive:
            self.fail("OBSERVER_PROTOCOL_ERROR", "response_observer_not_alive")
            return

        new_turns = [
            turn
            for turn in snapshot.turns
            if turn.key not in self.baseline_keys and turn.ordinal >= self.baseline_turn_count
        ]

        if self.user_turn_key is None:
            user_matches = [
                turn
                for turn in new_turns
                if turn.role == "user"
                and (turn.request_match or turn.text_hash == self.submitted_hash)
            ]
            if len(user_matches) > 1:
                self.fail("REQUEST_TURN_ASSOCIATION_AMBIGUOUS", "multiple_matching_user_turns")
                return
            if len(user_matches) == 1:
                user_turn = user_matches[0]
                self.user_turn_key = user_turn.key
                self.user_turn_ordinal = user_turn.ordinal
                self._transition(ResponseState.ASSISTANT_TURN_PENDING, "USER_TURN_MATCHED")

        if self.user_turn_key is None:
            self.check_time(now)
            return

        if self.assistant_turn_key is None:
            candidates = sorted(
                (
                    turn
                    for turn in new_turns
                    if turn.role == "assistant"
                    and self.user_turn_ordinal is not None
                    and turn.ordinal > self.user_turn_ordinal
                ),
                key=lambda turn: turn.ordinal,
            )
            if candidates:
                assistant_turn = candidates[0]
                self.assistant_turn_key = assistant_turn.key
                self.assistant_turn_ordinal = assistant_turn.ordinal
                self.assistant_text_hash = assistant_turn.text_hash
                self.assistant_text_length = assistant_turn.text_length
                self._transition(ResponseState.ASSISTANT_TURN_ACTIVE, "ASSISTANT_TURN_ADDED")

        if self.assistant_turn_key is None:
            self.check_time(now)
            return

        current = next(
            (turn for turn in snapshot.turns if turn.key == self.assistant_turn_key),
            None,
        )
        if current is None:
            replacements = [
                turn
                for turn in snapshot.turns
                if turn.role == "assistant"
                and self.assistant_turn_ordinal is not None
                and turn.ordinal == self.assistant_turn_ordinal
                and turn.key != self.assistant_turn_key
            ]
            if len(replacements) > 1:
                self.fail(
                    "REQUEST_TURN_ASSOCIATION_AMBIGUOUS",
                    "multiple_assistant_replacements_for_bound_ordinal",
                )
                return
            if len(replacements) == 1:
                if "request-placeholder" not in (self.assistant_turn_key or ""):
                    self.fail(
                        "REQUEST_ASSISTANT_TURN_REPLACED",
                        "confirmed_assistant_turn_key_changed",
                    )
                    return
                replacement = replacements[0]
                self.assistant_turn_key = replacement.key
                self.assistant_text_hash = replacement.text_hash
                self.assistant_text_length = replacement.text_length
                self.assistant_rebind_count += 1
                self.missing_assistant_observations = 0
                self.settle_started_at = None
                self.settle_hash = ""
                self.last_event = "ASSISTANT_TURN_NODE_REBOUND"
                current = replacement
            else:
                self.missing_assistant_observations += 1
                if not snapshot.generation_active and self.missing_assistant_observations >= 2:
                    self.fail("REQUEST_ASSISTANT_TURN_REPLACED", "bound_assistant_turn_disappeared")
                self.check_time(now)
                return

        self.missing_assistant_observations = 0
        content_changed = (
            current.text_hash != self.assistant_text_hash
            or current.text_length != self.assistant_text_length
        )
        if content_changed:
            self.assistant_text_hash = current.text_hash
            self.assistant_text_length = current.text_length
            self.settle_started_at = None
            self.settle_hash = ""
            if self.state == ResponseState.ASSISTANT_TURN_SETTLING:
                self._transition(ResponseState.ASSISTANT_TURN_ACTIVE, "ASSISTANT_TURN_MUTATED")
            else:
                self.last_event = "ASSISTANT_TURN_MUTATED"
            self.check_time(now)
            return

        if snapshot.generation_active or current.text_length <= 0 or not snapshot.composer_ready:
            self.settle_started_at = None
            self.settle_hash = ""
            if self.state == ResponseState.ASSISTANT_TURN_SETTLING:
                self._transition(ResponseState.ASSISTANT_TURN_ACTIVE, "GENERATION_ACTIVE")
            self.check_time(now)
            return

        if self.settle_started_at is None or self.settle_hash != current.text_hash:
            self.settle_started_at = now
            self.settle_hash = current.text_hash
            if self.state == ResponseState.ASSISTANT_TURN_ACTIVE:
                self._transition(ResponseState.ASSISTANT_TURN_SETTLING, "TURN_STRUCTURALLY_COMPLETE")

        self.check_time(now)
