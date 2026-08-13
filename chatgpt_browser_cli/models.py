from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskStatus(str, Enum):
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    NEEDS_USER_ACTION = "NEEDS USER ACTION"


class ErrorCode(str, Enum):
    NONE = "NONE"
    EMPTY_PROMPT = "EMPTY_PROMPT"
    ANTI_RECURSION = "ANTI_RECURSION"
    BROWSER_LAUNCH_FAILED = "BROWSER_LAUNCH_FAILED"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
    COMPOSER_NOT_FOUND = "COMPOSER_NOT_FOUND"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    ATTACHMENT_MISSING = "ATTACHMENT_MISSING"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    SUBMIT_FAILED = "SUBMIT_FAILED"
    COOKIE_IMPORT_FAILED = "COOKIE_IMPORT_FAILED"
    CHATGPT_ERROR = "CHATGPT_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    GENERATION_STOPPED = "GENERATION_STOPPED"
    TIMEOUT = "TIMEOUT"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


@dataclass(frozen=True)
class RunResult:
    status: TaskStatus
    result: str = ""
    reason: str = ""
    required_action: str = ""
    error_code: ErrorCode = ErrorCode.NONE


@dataclass(frozen=True)
class UiSnapshot:
    assistant_count: int = 0
    latest_assistant_text: str = ""
    is_running: bool = False
    stopped_indicator: bool = False
    fatal_error: str = ""
    needs_user_action: str = ""
    error_code: ErrorCode = ErrorCode.NONE
