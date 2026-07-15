import unittest

from core.response_state import (
    PageSnapshot,
    ResponseRequestState,
    ResponseState,
    TurnSnapshot,
    normalize_turn_text,
    text_fingerprint,
)


def turn(role: str, key: str, ordinal: int, text: str) -> TurnSnapshot:
    normalized = normalize_turn_text(text)
    return TurnSnapshot(
        role=role,
        key=key,
        ordinal=ordinal,
        text_length=len(normalized),
        text_hash=text_fingerprint(text),
    )


def page(
    *turns: TurnSnapshot,
    generating: bool = False,
    composer_ready: bool = True,
    failure_code: str | None = None,
    sequence: int = 1,
) -> PageSnapshot:
    return PageSnapshot(
        turns=tuple(turns),
        generation_active=generating,
        composer_ready=composer_ready,
        observer_alive=True,
        observer_sequence=sequence,
        failure_code=failure_code,
    )


class ResponseStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.old_user = turn("user", "user:conversation-turn-0", 0, "old question")
        self.old_assistant = turn("assistant", "assistant:conversation-turn-1", 1, "OLD_SUCCESS")
        self.baseline = page(self.old_user, self.old_assistant)

    def machine(self, prompt: str = "new question", expected_marker: str | None = None):
        return ResponseRequestState.create(
            request_id="request-1",
            submitted_text=prompt,
            baseline=self.baseline,
            expected_marker=expected_marker,
            started_at=0.0,
            deadline_seconds=600.0,
            settle_seconds=1.0,
            user_turn_confirm_seconds=20.0,
        )

    def test_historical_assistant_is_never_returned_for_new_request(self):
        machine = self.machine(expected_marker="OLD_SUCCESS")
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")

        machine.observe(page(self.old_user, self.old_assistant, new_user), 1.0)

        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_PENDING)
        self.assertIsNone(machine.assistant_turn_key)
        self.assertFalse(machine.completed)

    def test_new_user_and_following_assistant_are_strictly_bound(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        new_assistant = turn("assistant", "assistant:conversation-turn-3", 3, "new answer")

        machine.observe(page(self.old_user, self.old_assistant, new_user, new_assistant, generating=True), 1.0)

        self.assertEqual(machine.user_turn_key, new_user.key)
        self.assertEqual(machine.assistant_turn_key, new_assistant.key)
        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_ACTIVE)

    def test_active_generation_never_completes_from_elapsed_time(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        new_assistant = turn("assistant", "assistant:conversation-turn-3", 3, "thinking")

        machine.observe(page(self.old_user, self.old_assistant, new_user, new_assistant, generating=True), 1.0)
        machine.check_time(590.0)

        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_ACTIVE)
        self.assertFalse(machine.completed)

    def test_structural_completion_requires_settle_debounce(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        new_assistant = turn("assistant", "assistant:conversation-turn-3", 3, "final answer")
        snapshot = page(self.old_user, self.old_assistant, new_user, new_assistant)

        machine.observe(snapshot, 1.0)
        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_SETTLING)
        machine.check_time(1.9)
        self.assertFalse(machine.completed)
        machine.check_time(2.0)
        self.assertTrue(machine.completed)

    def test_content_change_during_settle_returns_to_active(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        partial = turn("assistant", "assistant:conversation-turn-3", 3, "partial")
        final = turn("assistant", "assistant:conversation-turn-3", 3, "partial plus final")

        machine.observe(page(self.old_user, self.old_assistant, new_user, partial), 1.0)
        machine.observe(page(self.old_user, self.old_assistant, new_user, final), 1.5)

        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_ACTIVE)
        machine.observe(page(self.old_user, self.old_assistant, new_user, final), 1.6)
        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_SETTLING)

    def test_old_turn_mutation_does_not_change_bound_assistant(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        new_assistant = turn("assistant", "assistant:conversation-turn-3", 3, "new answer")
        machine.observe(page(self.old_user, self.old_assistant, new_user, new_assistant, generating=True), 1.0)
        mutated_old = turn("assistant", self.old_assistant.key, 1, "OLD_SUCCESS changed")

        machine.observe(page(self.old_user, mutated_old, new_user, new_assistant, generating=True), 2.0)

        self.assertEqual(machine.assistant_turn_key, new_assistant.key)
        self.assertEqual(machine.assistant_text_hash, new_assistant.text_hash)

    def test_multiple_matching_user_turns_fail_closed(self):
        machine = self.machine()
        user_a = turn("user", "user:conversation-turn-2", 2, "new question")
        user_b = turn("user", "user:conversation-turn-3", 3, "new question")

        machine.observe(page(self.old_user, self.old_assistant, user_a, user_b), 1.0)

        self.assertEqual(machine.state, ResponseState.TURN_ASSOCIATION_FAILED)
        self.assertEqual(machine.error_code, "REQUEST_TURN_ASSOCIATION_AMBIGUOUS")

    def test_bound_assistant_disappearance_waits_while_generation_is_active(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        new_assistant = turn("assistant", "assistant:conversation-turn-3", 3, "new answer")
        machine.observe(page(self.old_user, self.old_assistant, new_user, new_assistant, generating=True), 1.0)
        without_assistant = page(self.old_user, self.old_assistant, new_user, generating=True)

        machine.observe(without_assistant, 2.0)
        machine.observe(without_assistant, 3.0)

        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_ACTIVE)

        generation_stopped = page(self.old_user, self.old_assistant, new_user, generating=False)
        machine.observe(generation_stopped, 4.0)
        machine.observe(generation_stopped, 5.0)

        self.assertEqual(machine.state, ResponseState.TURN_ASSOCIATION_FAILED)
        self.assertEqual(machine.error_code, "REQUEST_ASSISTANT_TURN_REPLACED")

    def test_explicit_page_failure_terminates_immediately(self):
        machine = self.machine()

        machine.observe(page(self.old_user, self.old_assistant, failure_code="AUTH_LOGIN_REQUIRED"), 1.0)

        self.assertEqual(machine.state, ResponseState.LOGIN_REQUIRED)
        self.assertEqual(machine.error_code, "AUTH_LOGIN_REQUIRED")

    def test_deadline_is_the_only_long_wall_clock_termination(self):
        machine = self.machine()
        new_user = turn("user", "user:conversation-turn-2", 2, "new question")
        new_assistant = turn("assistant", "assistant:conversation-turn-3", 3, "thinking")
        machine.observe(page(self.old_user, self.old_assistant, new_user, new_assistant, generating=True), 1.0)

        machine.check_time(600.0)

        self.assertEqual(machine.state, ResponseState.DEADLINE_EXCEEDED)
        self.assertEqual(machine.error_code, "REQUEST_DEADLINE_EXCEEDED")

    def test_terminal_state_cannot_be_overwritten(self):
        machine = self.machine()
        machine.fail("BROWSER_PAGE_CRASHED")
        machine.observe(page(self.old_user, self.old_assistant), 2.0)

        self.assertEqual(machine.state, ResponseState.PAGE_CRASHED)
        self.assertEqual(machine.error_code, "BROWSER_PAGE_CRASHED")
