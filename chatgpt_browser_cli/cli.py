from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .logging_utils import configure_logging
from .models import RunResult, TaskStatus
from .runner import ChatGPTBrowser


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delegate one task to ChatGPT.com using Playwright.")
    parser.add_argument("prompt", nargs="?", help="Task to submit; if omitted, read stdin.")
    parser.add_argument("--file", action="append", default=[], help="Attachment path; repeatable.")
    parser.add_argument("--model", default="", help="Visible model name to select and verify.")
    parser.add_argument("--profile-dir", default="~/.chatgpt-browser-profile", help="Persistent Chromium profile directory.")
    parser.add_argument("--cookies", default=None, help="Import cookies from JSON before opening ChatGPT.com; values are never printed.")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Maximum generation monitoring time.")
    parser.add_argument("--poll-seconds", type=float, default=1.5, help="UI polling interval.")
    parser.add_argument("--auth-wait-seconds", type=int, default=0, help="In headed mode, wait this long for manual login/CAPTCHA/2FA before returning.")
    parser.add_argument("--stable-observations", type=int, default=2, help="Unchanged idle observations required before declaring completion.")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO", help="Diagnostic log verbosity.")
    parser.add_argument("--log-file", default=None, help="Write diagnostic logs to this file instead of stderr.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON status output.")
    parser.add_argument("--executable-path", default=None, help="Explicit Chromium/Chrome executable path.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", help="Run Chromium without a visible window.")
    mode.add_argument("--headed", action="store_true", help="Run Chromium with a visible window.")
    return parser.parse_args(argv)


def resolve_headless(args: argparse.Namespace, environ: Mapping[str, str]) -> bool:
    if getattr(args, "headless", False):
        return True
    if getattr(args, "headed", False):
        return False
    return _truthy(environ.get("CHATGPT_BROWSER_HEADLESS"))


def format_result(result: RunResult, *, json_mode: bool = False) -> str:
    if json_mode:
        return json.dumps({"status": result.status.value, "result": result.result, "reason": result.reason, "required_action": result.required_action, "error_code": result.error_code.value}, ensure_ascii=False)
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


def _default_executable() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if path := shutil.which(name):
            return path
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    logger = configure_logging(args.log_level, log_file=Path(args.log_file) if args.log_file else None)
    headless = resolve_headless(args, os.environ)
    logger.info("starting ChatGPT browser CLI mode=%s", "headless" if headless else "headed")
    runner = ChatGPTBrowser(profile_dir=Path(args.profile_dir), headless=headless, executable_path=args.executable_path or _default_executable(), timeout_seconds=args.timeout_seconds, poll_seconds=args.poll_seconds, cookies_path=Path(args.cookies) if args.cookies else None, auth_wait_seconds=args.auth_wait_seconds, stable_observations=args.stable_observations, logger=logger)
    result = runner.run(prompt, files=[Path(path) for path in args.file], requested_model=args.model)
    print(format_result(result, json_mode=args.json))
    return 0 if result.status == TaskStatus.COMPLETED else 2
