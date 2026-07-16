"""Stable request-boundary contract for Web Lead calls."""

from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_CONVERSATION_MODES = frozenset({"reuse_or_create", "new", "one_shot"})
SUPPORTED_REQUEST_ORIGINS = frozenset({"interactive", "automation", "scheduled"})
LEGACY_AUTOMATION_MODE = "automation"


class RequestContractError(ValueError):
    """Raised before a malformed request reaches the broker or browser."""


@dataclass(frozen=True)
class WebRequestContract:
    conversation_mode: str
    request_origin: str
    legacy_mode_normalized: bool = False


def normalize_request_contract(
    conversation_mode: str | None,
    request_origin: str | None = "interactive",
) -> WebRequestContract:
    """Validate the public request shape and normalize one legacy alias.

    ``automation`` was historically sent in the conversation-mode field. It is
    a request origin, not a conversation lifecycle instruction, so retain
    compatibility while translating it to the normal reuse policy.
    """

    mode = str(conversation_mode or "reuse_or_create").strip().lower()
    origin = str(request_origin or "interactive").strip().lower()
    if mode == LEGACY_AUTOMATION_MODE:
        return WebRequestContract(
            conversation_mode="reuse_or_create",
            request_origin="automation",
            legacy_mode_normalized=True,
        )
    if mode not in SUPPORTED_CONVERSATION_MODES:
        raise RequestContractError(f"invalid_conversation_mode:{mode}")
    if origin not in SUPPORTED_REQUEST_ORIGINS:
        raise RequestContractError(f"invalid_request_origin:{origin}")
    return WebRequestContract(conversation_mode=mode, request_origin=origin)
