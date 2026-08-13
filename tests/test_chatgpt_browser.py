import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_browser import ChatGPTBrowser, RunResult, TaskStatus, UiSnapshot, decide_terminal_state, format_result, load_cookie_file


class StateMachineTests(unittest.TestCase):
    def test_completed_requires_stable_new_answer(self):
        snap = UiSnapshot(2, "Final answer", False)
        result = decide_terminal_state(snap, initial_assistant_count=1, stable_observations=2)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(result.result, "Final answer")

    def test_running_not_completed(self):
        self.assertIsNone(decide_terminal_state(UiSnapshot(2, "Typing", True), initial_assistant_count=1, stable_observations=5))

    def test_old_answer_not_completed(self):
        self.assertIsNone(decide_terminal_state(UiSnapshot(1, "Old", False), initial_assistant_count=1, stable_observations=5))

    def test_stopped(self):
        result = decide_terminal_state(UiSnapshot(2, "Partial", False, True), initial_assistant_count=1, stable_observations=3)
        self.assertEqual(result.status, TaskStatus.STOPPED)

    def test_needs_action_precedence(self):
        result = decide_terminal_state(UiSnapshot(needs_user_action="Complete 2FA", fatal_error="error"), initial_assistant_count=0, stable_observations=0)
        self.assertEqual(result.status, TaskStatus.NEEDS_USER_ACTION)

    def test_failure(self):
        self.assertEqual(decide_terminal_state(UiSnapshot(fatal_error="Network error"), initial_assistant_count=0, stable_observations=0).status, TaskStatus.FAILED)


class FormattingTests(unittest.TestCase):
    def test_formats(self):
        self.assertIn("**COMPLETED**", format_result(RunResult(TaskStatus.COMPLETED, result="Hello")))
        self.assertIn("### Partial Result", format_result(RunResult(TaskStatus.STOPPED, result="Partial", reason="Stopped")))
        self.assertIn("### Required Action", format_result(RunResult(TaskStatus.NEEDS_USER_ACTION, required_action="Log in")))


class CookieTests(unittest.TestCase):
    def test_raw_cookie_list_normalizes_browser_export(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cookies.json"
            p.write_text(json.dumps([{"name":"session","value":"secret-test-value","domain":".chatgpt.com","expirationDate":2000000000.0,"sameSite":"no_restriction","hostOnly":False}]))
            cookies = load_cookie_file(p)
        self.assertEqual(cookies[0]["path"], "/")
        self.assertEqual(cookies[0]["expires"], 2000000000.0)
        self.assertEqual(cookies[0]["sameSite"], "None")
        self.assertNotIn("hostOnly", cookies[0])

    def test_storage_state_shape(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({"cookies":[{"name":"a","value":"b","url":"https://chatgpt.com"}]}))
            self.assertEqual(load_cookie_file(p)[0]["url"], "https://chatgpt.com")

    def test_invalid_shape(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text('{"nope": []}')
            with self.assertRaises(ValueError):
                load_cookie_file(p)

    def test_unknown_same_site_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cookies.json"
            p.write_text(json.dumps([{"name":"session","value":"VERY_SECRET_COOKIE","domain":".chatgpt.com","sameSite":"broken"}]))
            cookies = load_cookie_file(p)
        self.assertNotIn("sameSite", cookies[0])


class GuardTests(unittest.TestCase):
    def test_anti_recursion(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"CHATGPT_BROWSER_DELEGATION_ACTIVE":"true"}):
            result = ChatGPTBrowser(profile_dir=Path(td), headless=True, timeout_seconds=1).run("hello")
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("Anti-recursion", result.reason)


@unittest.skipUnless(shutil.which("chromium") or shutil.which("google-chrome"), "system Chromium/Chrome not installed")
class DomIntegrationTests(unittest.TestCase):
    def _exe(self):
        return shutil.which("chromium") or shutil.which("google-chrome")

    def test_dom_helpers(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<div id="prompt-textarea" contenteditable="true" role="textbox"></div><button data-testid="send-button">Send</button><div data-message-author-role="assistant">First</div><div data-message-author-role="assistant">Final</div>')
                runner = ChatGPTBrowser(profile_dir=Path(td), headless=True, executable_path=self._exe())
                self.assertIsNotNone(runner._find_composer(page))
                self.assertEqual(runner._assistant_messages(page), ["First", "Final"])
                self.assertEqual(runner._needs_user_action(page), "")
            finally:
                context.close()

    def test_cookie_import(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            cookie_file = Path(td) / "cookies.json"
            cookie_file.write_text(json.dumps([{"name":"test_cookie","value":"test_value","url":"https://chatgpt.com","sameSite":"Lax"}]))
            context = p.chromium.launch_persistent_context(str(Path(td)/"profile"), headless=True, executable_path=self._exe())
            try:
                runner = ChatGPTBrowser(profile_dir=Path(td)/"other", headless=True, executable_path=self._exe(), cookies_path=cookie_file)
                self.assertIsNone(runner._import_cookies(context))
                self.assertEqual([(c["name"], c["value"]) for c in context.cookies("https://chatgpt.com")], [("test_cookie","test_value")])
            finally:
                context.close()

    def test_model_selection_verified(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<button id="picker" aria-label="Model selector">Default</button><button id="gpt5">GPT-5</button><script>gpt5.onclick=()=>{picker.textContent="GPT-5";gpt5.setAttribute("aria-selected","true")}</script>')
                runner = ChatGPTBrowser(profile_dir=Path(td), headless=True, executable_path=self._exe())
                self.assertIsNone(runner._select_model(page, "GPT-5"))
            finally:
                context.close()

    def test_user_turn_not_assistant(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<article data-testid="conversation-turn-1">User prompt only</article>')
                self.assertEqual(ChatGPTBrowser(profile_dir=Path(td))._assistant_messages(page), [])
            finally:
                context.close()

    def test_captcha_detection(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<body><div>Verify you are human</div></body>')
                self.assertIn("human-verification", ChatGPTBrowser(profile_dir=Path(td))._needs_user_action(page))
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
