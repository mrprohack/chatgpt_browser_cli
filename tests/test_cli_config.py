import json
import unittest

from chatgpt_browser_cli.cli import format_result, parse_args, resolve_headless
from chatgpt_browser_cli.models import ErrorCode, RunResult, TaskStatus


class CliModeTests(unittest.TestCase):
    def test_headed_and_headless_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            parse_args(["--headed", "--headless", "hello"])

    def test_headed_flag_forces_visible_browser(self):
        args = parse_args(["--headed", "hello"])
        self.assertFalse(resolve_headless(args, {"CHATGPT_BROWSER_HEADLESS": "1"}))

    def test_headless_flag_forces_headless_browser(self):
        args = parse_args(["--headless", "hello"])
        self.assertTrue(resolve_headless(args, {}))

    def test_environment_is_used_when_no_mode_flag_is_given(self):
        args = parse_args(["hello"])
        self.assertTrue(resolve_headless(args, {"CHATGPT_BROWSER_HEADLESS": "true"}))
        self.assertFalse(resolve_headless(args, {"CHATGPT_BROWSER_HEADLESS": "0"}))

    def test_default_remains_headed(self):
        self.assertFalse(resolve_headless(parse_args(["hello"]), {}))


class JsonFormattingTests(unittest.TestCase):
    def test_json_output_includes_error_code(self):
        result = RunResult(TaskStatus.FAILED, reason="could not navigate", error_code=ErrorCode.NAVIGATION_FAILED)
        payload = json.loads(format_result(result, json_mode=True))
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason"], "could not navigate")
        self.assertEqual(payload["error_code"], "NAVIGATION_FAILED")


class FullParserTests(unittest.TestCase):
    def test_parser_accepts_existing_and_new_flags(self):
        args = parse_args(["--file", "a.pdf", "--file", "b.png", "--model", "GPT-5", "--profile-dir", "/tmp/profile", "--cookies", "/tmp/cookies.json", "--timeout-seconds", "120", "--poll-seconds", "0.5", "--auth-wait-seconds", "30", "--stable-observations", "3", "--log-level", "DEBUG", "--log-file", "/tmp/browser.log", "--json", "--headed", "hello"])
        self.assertEqual(args.file, ["a.pdf", "b.png"])
        self.assertEqual(args.model, "GPT-5")
        self.assertEqual(args.auth_wait_seconds, 30)
        self.assertEqual(args.stable_observations, 3)
        self.assertTrue(args.json)
        self.assertTrue(args.headed)

    def test_top_level_module_reexports_public_api(self):
        import chatgpt_browser
        self.assertTrue(hasattr(chatgpt_browser, "ChatGPTBrowser"))
        self.assertTrue(hasattr(chatgpt_browser, "ErrorCode"))
        self.assertTrue(hasattr(chatgpt_browser, "main"))


if __name__ == "__main__":
    unittest.main()
