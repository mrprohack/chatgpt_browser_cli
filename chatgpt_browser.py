from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Sequence

from playwright.sync_api import BrowserContext, Locator, Page, Playwright, TimeoutError as PWTimeout, sync_playwright

CHATGPT_URL = "https://chatgpt.com/"
DELEGATION_ENV = "CHATGPT_BROWSER_DELEGATION_ACTIVE"


class TaskStatus(str, Enum):
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    NEEDS_USER_ACTION = "NEEDS USER ACTION"


@dataclass(frozen=True)
class RunResult:
    status: TaskStatus
    result: str = ""
    reason: str = ""
    required_action: str = ""


@dataclass(frozen=True)
class UiSnapshot:
    assistant_count: int = 0
    latest_assistant_text: str = ""
    is_running: bool = False
    stopped_indicator: bool = False
    fatal_error: str = ""
    needs_user_action: str = ""


def decide_terminal_state(snapshot: UiSnapshot, *, initial_assistant_count: int, stable_observations: int) -> Optional[RunResult]:
    if snapshot.needs_user_action:
        return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=snapshot.needs_user_action)
    if snapshot.fatal_error:
        return RunResult(TaskStatus.FAILED, reason=snapshot.fatal_error)
    if snapshot.stopped_indicator:
        return RunResult(TaskStatus.STOPPED, snapshot.latest_assistant_text, "ChatGPT generation appears to have been stopped or interrupted.")
    has_new_answer = snapshot.assistant_count > initial_assistant_count and bool(snapshot.latest_assistant_text.strip())
    if has_new_answer and not snapshot.is_running and stable_observations >= 2:
        return RunResult(TaskStatus.COMPLETED, result=snapshot.latest_assistant_text.strip())
    return None


def format_result(result: RunResult) -> str:
    if result.status == TaskStatus.COMPLETED:
        return f"### ChatGPT Task Status\n**COMPLETED**\n\n### Result\n{result.result}".rstrip()
    if result.status == TaskStatus.STOPPED:
        partial = result.result or "No usable partial output was available."
        reason = result.reason or "The run stopped before completion."
        return f"### ChatGPT Task Status\n**STOPPED**\n\n### Partial Result\n{partial}\n\n### Reason\n{reason}".rstrip()
    if result.status == TaskStatus.NEEDS_USER_ACTION:
        action = result.required_action or "User interaction is required in the browser."
        return f"### ChatGPT Task Status\n**NEEDS USER ACTION**\n\n### Required Action\n{action}".rstrip()
    return f"### ChatGPT Task Status\n**FAILED**\n\n### Reason\n{result.reason or 'The browser automation failed.'}".rstrip()


def load_cookie_file(path: Path) -> list[dict]:
    """Load raw-list or Playwright-style JSON cookies without logging values."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Cookie file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cookie file is not valid JSON: {exc.msg}") from exc
    cookies = payload.get("cookies") if isinstance(payload, dict) else payload
    if not isinstance(cookies, list):
        raise ValueError('Cookie JSON must be a list or an object containing a "cookies" list.')

    allowed = {"name", "value", "url", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
    same_site = {"strict": "Strict", "lax": "Lax", "none": "None", "no_restriction": "None", "unspecified": "Lax"}
    out: list[dict] = []
    for index, raw in enumerate(cookies, 1):
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not isinstance(raw.get("value"), str):
            raise ValueError(f"Cookie entry #{index} must be an object with string name and value fields.")
        cookie = {k: raw[k] for k in allowed if k in raw}
        if "expires" not in cookie and raw.get("expirationDate") is not None:
            cookie["expires"] = raw["expirationDate"]
        if cookie.get("domain") and "path" not in cookie:
            cookie["path"] = "/"
        if isinstance(cookie.get("sameSite"), str):
            mapped = same_site.get(cookie["sameSite"].strip().lower())
            if mapped:
                cookie["sameSite"] = mapped
            else:
                cookie.pop("sameSite", None)
        if not cookie.get("url") and not cookie.get("domain"):
            raise ValueError(f"Cookie entry #{index} must contain either url or domain.")
        out.append(cookie)
    if not out:
        raise ValueError("Cookie file contains no cookies.")
    return out


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class ChatGPTBrowser:
    COMPOSER = ("#prompt-textarea", '[data-testid="prompt-textarea"]', 'textarea[placeholder*="Ask" i]', 'div[contenteditable="true"][role="textbox"]')
    SEND = ('button[data-testid="send-button"]', 'button[aria-label*="Send" i]')
    STOP = ('button[data-testid="stop-button"]', 'button[aria-label*="Stop" i]', 'button:has-text("Stop generating")')
    CONTINUE = ('button:has-text("Continue generating")', 'button:has-text("Continue")')

    def __init__(self, *, profile_dir: Path, headless: bool = False, executable_path: Optional[str] = None,
                 timeout_seconds: int = 900, poll_seconds: float = 1.5, cookies_path: Optional[Path] = None) -> None:
        self.profile_dir = profile_dir.expanduser().resolve()
        self.headless = headless
        self.executable_path = executable_path
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.cookies_path = cookies_path.expanduser().resolve() if cookies_path else None

    @staticmethod
    def _first_visible(page: Page, selectors: Iterable[str]) -> Optional[Locator]:
        for selector in selectors:
            try:
                loc = page.locator(selector)
                for i in range(min(loc.count(), 8)):
                    if loc.nth(i).is_visible(timeout=250):
                        return loc.nth(i)
            except Exception:
                pass
        return None

    def _find_composer(self, page: Page) -> Optional[Locator]:
        return self._first_visible(page, self.COMPOSER)

    def _assistant_messages(self, page: Page) -> list[str]:
        result: list[str] = []
        loc = page.locator('[data-message-author-role="assistant"]')
        try:
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible(timeout=150):
                    text = item.inner_text(timeout=500).strip()
                    if text:
                        result.append(text)
        except Exception:
            pass
        return result

    def _needs_user_action(self, page: Page) -> str:
        if self._find_composer(page):
            return ""
        if self._first_visible(page, ('iframe[src*="captcha" i]', 'iframe[src*="challenges.cloudflare.com" i]', '[class*="captcha" i]')):
            return "Complete the CAPTCHA / human-verification challenge in the opened browser."
        try:
            body = page.locator("body").inner_text(timeout=1200).lower()
        except Exception:
            body = ""
        if any(x in body for x in ("verify you are human", "security check", "captcha")):
            return "Complete the human-verification/security check in the opened browser."
        if any(x in body for x in ("two-factor", "2fa", "verification code", "authenticator")):
            return "Complete the two-factor authentication step in the opened browser."
        if page.locator('input[type="password"]').count() or self._first_visible(page, ('a:has-text("Log in")', 'button:has-text("Log in")')):
            return "Log in to ChatGPT in the opened browser, then rerun using the same profile or cookie file."
        return ""

    def _fatal_error(self, page: Page) -> str:
        phrases = ("Something went wrong", "There was an error generating a response", "Unable to load", "Network error", "Rate limit", "You have reached your limit")
        try:
            body = page.locator("body").inner_text(timeout=1200).lower()
        except Exception:
            return ""
        for phrase in phrases:
            if phrase.lower() in body:
                return f"ChatGPT displayed an error: {phrase}"
        return ""

    def _snapshot(self, page: Page) -> UiSnapshot:
        messages = self._assistant_messages(page)
        return UiSnapshot(len(messages), messages[-1] if messages else "", bool(self._first_visible(page, self.STOP)),
                          bool(self._first_visible(page, self.CONTINUE)), self._fatal_error(page), self._needs_user_action(page))

    def _select_model(self, page: Page, requested: str) -> Optional[RunResult]:
        if not requested.strip():
            return None
        selectors = ('button[aria-label*="model" i]', 'button[data-testid*="model" i]')
        picker = self._first_visible(page, selectors)
        if not picker:
            return RunResult(TaskStatus.FAILED, reason=f'Requested model "{requested}", but no model selector was found.')
        try:
            picker.click(timeout=2500)
            options = page.get_by_text(requested, exact=False)
            chosen = next((options.nth(i) for i in range(min(options.count(), 20)) if options.nth(i).is_visible(timeout=250)), None)
            if chosen is None:
                raise RuntimeError("model unavailable")
            chosen.click(timeout=3000)
            time.sleep(0.4)
            picker = self._first_visible(page, selectors)
            if picker and requested.casefold() in picker.inner_text(timeout=1000).casefold():
                return None
            selected = page.locator('[aria-selected="true"], [aria-checked="true"], [data-state="checked"], [data-state="selected"]')
            for i in range(min(selected.count(), 30)):
                if requested.casefold() in selected.nth(i).inner_text(timeout=500).casefold():
                    return None
        except Exception:
            pass
        return RunResult(TaskStatus.FAILED, reason=f'Requested model "{requested}" could not be selected and verified.')

    def _upload_files(self, page: Page, files: Sequence[Path]) -> Optional[RunResult]:
        if not files:
            return None
        paths = [str(p.expanduser().resolve()) for p in files]
        if any(not Path(p).is_file() for p in paths):
            return RunResult(TaskStatus.FAILED, reason="One or more requested attachments do not exist.")
        try:
            inp = page.locator('input[type="file"]')
            if not inp.count():
                button = self._first_visible(page, ('button[aria-label*="Attach" i]', 'button[aria-label*="file" i]', 'button:has-text("Add files")'))
                if button:
                    button.click(timeout=2000)
                    time.sleep(0.3)
            inp = page.locator('input[type="file"]')
            if not inp.count():
                return RunResult(TaskStatus.FAILED, reason="ChatGPT file input was not available.")
            inp.first.set_input_files(paths, timeout=5000)
            time.sleep(0.8)
            return None
        except Exception as exc:
            return RunResult(TaskStatus.FAILED, reason=f"Could not attach requested file(s): {exc}")

    def _submit_prompt(self, page: Page, prompt: str) -> Optional[RunResult]:
        composer = self._find_composer(page)
        if not composer:
            action = self._needs_user_action(page)
            return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=action) if action else RunResult(TaskStatus.FAILED, reason="ChatGPT composer was not found.")
        try:
            composer.click(timeout=2000)
            try:
                composer.fill(prompt, timeout=5000)
            except Exception:
                composer.press("Control+A")
                composer.type(prompt, delay=0)
            send = self._first_visible(page, self.SEND)
            send.click(timeout=3000) if send else composer.press("Enter")
            return None
        except Exception as exc:
            return RunResult(TaskStatus.FAILED, reason=f"Could not submit the task to ChatGPT: {exc}")

    def _launch_context(self, p: Playwright) -> BrowserContext:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        kwargs = {"headless": self.headless, "viewport": {"width": 1440, "height": 1000}}
        if self.executable_path:
            kwargs["executable_path"] = self.executable_path
        return p.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)

    def _import_cookies(self, context: BrowserContext) -> Optional[RunResult]:
        if not self.cookies_path:
            return None
        try:
            context.add_cookies(load_cookie_file(self.cookies_path))
            return None
        except Exception as exc:
            return RunResult(TaskStatus.FAILED, reason=f"Could not import cookies from {self.cookies_path}: {exc}")

    def run(self, prompt: str, *, files: Sequence[Path] = (), requested_model: str = "") -> RunResult:
        if _env_truthy(DELEGATION_ENV):
            return RunResult(TaskStatus.FAILED, reason="Anti-recursion guard: CHATGPT_BROWSER_DELEGATION_ACTIVE is already set.")
        if not prompt.strip():
            return RunResult(TaskStatus.FAILED, reason="The task prompt is empty.")
        old_flag = os.environ.get(DELEGATION_ENV)
        os.environ[DELEGATION_ENV] = "true"
        context: Optional[BrowserContext] = None
        try:
            with sync_playwright() as p:
                context = self._launch_context(p)
                if cookie_error := self._import_cookies(context):
                    return cookie_error
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(5000)
                try:
                    page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30000)
                except PWTimeout:
                    pass
                except Exception as exc:
                    return RunResult(TaskStatus.FAILED, reason=f"Could not open ChatGPT.com: {exc}")

                ready_deadline = time.monotonic() + 15
                while time.monotonic() < ready_deadline and not self._find_composer(page):
                    if action := self._needs_user_action(page):
                        return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=action)
                    if fatal := self._fatal_error(page):
                        return RunResult(TaskStatus.FAILED, reason=fatal)
                    time.sleep(0.5)
                if not self._find_composer(page):
                    return RunResult(TaskStatus.FAILED, reason="ChatGPT loaded, but a usable composer did not appear.")
                if result := self._select_model(page, requested_model):
                    return result
                if result := self._upload_files(page, files):
                    return result

                initial_count = len(self._assistant_messages(page))
                if result := self._submit_prompt(page, prompt.strip()):
                    return result

                deadline, last_text, stable, saw_running = time.monotonic() + self.timeout_seconds, "", 0, False
                while time.monotonic() < deadline:
                    snap = self._snapshot(page)
                    saw_running = saw_running or snap.is_running
                    if snap.latest_assistant_text:
                        stable = stable + 1 if snap.latest_assistant_text == last_text else 1
                        last_text = snap.latest_assistant_text
                    else:
                        stable = 0
                    if terminal := decide_terminal_state(snap, initial_assistant_count=initial_count, stable_observations=stable):
                        return terminal
                    time.sleep(self.poll_seconds)

                final = self._snapshot(page)
                if final.latest_assistant_text:
                    reason = "Monitoring timeout reached while ChatGPT still appeared active." if final.is_running or saw_running else "Monitoring timeout reached before completion could be verified."
                    return RunResult(TaskStatus.STOPPED, final.latest_assistant_text, reason)
                return RunResult(TaskStatus.FAILED, reason="Monitoring timeout reached and no ChatGPT answer was observed.")
        except Exception as exc:
            return RunResult(TaskStatus.FAILED, reason=f"Unrecoverable browser error: {exc}")
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if old_flag is None:
                os.environ.pop(DELEGATION_ENV, None)
            else:
                os.environ[DELEGATION_ENV] = old_flag


def _default_executable() -> Optional[str]:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if path := shutil.which(name):
            return path
    return None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delegate one task to ChatGPT.com using Playwright.")
    parser.add_argument("prompt", nargs="?", help="Task to submit; if omitted, read stdin.")
    parser.add_argument("--file", action="append", default=[], help="Attachment path; repeatable.")
    parser.add_argument("--model", default="", help="Visible model name to select and verify.")
    parser.add_argument("--profile-dir", default="~/.chatgpt-browser-profile", help="Persistent Chromium profile directory.")
    parser.add_argument("--cookies", default=None, help="Import cookies from JSON before opening ChatGPT.com; values are never printed.")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=1.5)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--executable-path", default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    runner = ChatGPTBrowser(profile_dir=Path(args.profile_dir), headless=args.headless,
                            executable_path=args.executable_path or _default_executable(),
                            timeout_seconds=max(1, args.timeout_seconds), poll_seconds=max(0.2, args.poll_seconds),
                            cookies_path=Path(args.cookies) if args.cookies else None)
    result = runner.run(prompt, files=[Path(p) for p in args.file], requested_model=args.model)
    print(format_result(result))
    return 0 if result.status == TaskStatus.COMPLETED else 2


if __name__ == "__main__":
    raise SystemExit(main())
