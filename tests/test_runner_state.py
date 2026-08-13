import unittest

from chatgpt_browser_cli.models import ErrorCode, TaskStatus, UiSnapshot
from chatgpt_browser_cli.runner import decide_terminal_state


class RunnerStateTests(unittest.TestCase):
    def test_continue_control_without_new_answer_is_not_stopped(self):
        snapshot = UiSnapshot(assistant_count=1, latest_assistant_text="old answer", is_running=False, stopped_indicator=True)
        self.assertIsNone(decide_terminal_state(snapshot, initial_assistant_count=1, stable_observations=3, required_stable_observations=2))

    def test_stopped_requires_new_answer_and_returns_error_code(self):
        snapshot = UiSnapshot(assistant_count=2, latest_assistant_text="partial", is_running=False, stopped_indicator=True)
        result = decide_terminal_state(snapshot, initial_assistant_count=1, stable_observations=1, required_stable_observations=2)
        self.assertEqual(result.status, TaskStatus.STOPPED)
        self.assertEqual(result.error_code, ErrorCode.GENERATION_STOPPED)

    def test_completion_respects_configured_stability_threshold(self):
        snapshot = UiSnapshot(assistant_count=2, latest_assistant_text="final", is_running=False)
        self.assertIsNone(decide_terminal_state(snapshot, initial_assistant_count=1, stable_observations=2, required_stable_observations=3))
        result = decide_terminal_state(snapshot, initial_assistant_count=1, stable_observations=3, required_stable_observations=3)
        self.assertEqual(result.status, TaskStatus.COMPLETED)

    def test_needs_user_action_preserves_detected_error_code(self):
        snapshot = UiSnapshot(needs_user_action="Complete 2FA", error_code=ErrorCode.TWO_FACTOR_REQUIRED)
        result = decide_terminal_state(snapshot, initial_assistant_count=0, stable_observations=0, required_stable_observations=2)
        self.assertEqual(result.status, TaskStatus.NEEDS_USER_ACTION)
        self.assertEqual(result.error_code, ErrorCode.TWO_FACTOR_REQUIRED)


if __name__ == "__main__":
    unittest.main()
