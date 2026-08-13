from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_cookie_file(path: Path) -> list[dict[str, Any]]:
    """Load common browser/Playwright JSON cookie exports without logging values."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Cookie file does not exist: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cookie file is not valid JSON: {exc.msg}") from exc

    cookies = payload.get("cookies") if isinstance(payload, dict) else payload
    if not isinstance(cookies, list):
        raise ValueError('Cookie JSON must be a list or an object containing a "cookies" list.')

    allowed = {
        "name",
        "value",
        "url",
        "domain",
        "path",
        "expires",
        "httpOnly",
        "secure",
        "sameSite",
    }
    same_site = {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
        "unspecified": "Lax",
    }

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(cookies, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"Cookie entry #{index} must be an object.")
        if not isinstance(raw.get("name"), str) or not isinstance(raw.get("value"), str):
            raise ValueError(f"Cookie entry #{index} must contain string name and value fields.")

        cookie = {key: raw[key] for key in allowed if key in raw}
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
        normalized.append(cookie)

    if not normalized:
        raise ValueError("Cookie file contains no cookies.")
    return normalized


def cookie_secrets(cookies: list[dict[str, Any]]) -> list[str]:
    """Return non-empty cookie values so log filters can redact them."""
    return [value for cookie in cookies if isinstance((value := cookie.get("value")), str) and value]
