# chatgpt-browser CLI (Playwright Python)

A defensive Playwright implementation of the **Submit → Observe → Verify → Return** workflow for delegating one task to `https://chatgpt.com/`.

## What it does

- Opens ChatGPT.com in a persistent Chromium profile.
- Reuses a normal browser login session.
- Can optionally import authentication cookies from a local JSON file with `--cookies`.
- Never prints cookie values, passwords, tokens, or session IDs.
- Stops for login, CAPTCHA, 2FA, passkey/security confirmation, or other user-required auth.
- Optionally attaches files.
- Optionally selects a user-requested model and verifies the visible selection.
- Submits the prompt once.
- Monitors generation instead of assuming success.
- Returns exactly one status: `COMPLETED`, `STOPPED`, `FAILED`, or `NEEDS USER ACTION`.
- Uses an anti-recursion environment flag: `CHATGPT_BROWSER_DELEGATION_ACTIVE=true`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
playwright install chromium
```

If Chromium/Chrome is already installed, the script auto-detects it. You can also pass `--executable-path`.

## Authentication options

### Option 1: persistent browser profile

Use headful mode on the first run:

```bash
python chatgpt_browser.py "Explain TCP slow start in simple terms"
```

If ChatGPT requires login, CAPTCHA, 2FA, passkey, or another security step, the program returns `NEEDS USER ACTION`. Complete the action in the opened browser and rerun with the same `--profile-dir`.

### Option 2: import cookies

Export only cookies from a ChatGPT session you are authorized to use, save them locally, then run:

```bash
python chatgpt_browser.py --cookies cookies.json "Summarize the newest task in this prompt"
```

Supported JSON shapes:

```json
[
  {
    "name": "example",
    "value": "REDACTED",
    "domain": ".chatgpt.com",
    "path": "/",
    "secure": true,
    "httpOnly": true,
    "sameSite": "Lax"
  }
]
```

or a Playwright-style object:

```json
{
  "cookies": [
    {
      "name": "example",
      "value": "REDACTED",
      "domain": ".chatgpt.com",
      "path": "/"
    }
  ]
}
```

Common browser-export fields such as `expirationDate` and lower-case `sameSite` values are normalized automatically.

**Security:** cookie files are login credentials. Keep them local, do not paste them into issues/chat, and do not commit them. This repository's `.gitignore` excludes common cookie/storage-state filenames.

## Examples

Prompt from command line:

```bash
python chatgpt_browser.py "Research the pros and cons of SQLite vs PostgreSQL for a small SaaS"
```

Prompt from stdin:

```bash
cat task.txt | python chatgpt_browser.py
```

Use cookies and headless mode:

```bash
python chatgpt_browser.py --cookies cookies.json --headless "Give me a concise answer"
```

Attach files:

```bash
python chatgpt_browser.py --file report.pdf --file image.png "Analyze these files and return the key findings"
```

Explicit model request:

```bash
python chatgpt_browser.py --model "GPT-5" "Solve this problem carefully"
```

Long-running task:

```bash
python chatgpt_browser.py --timeout-seconds 1800 "Do a deep comparison and return a complete report"
```

## Test

```bash
python -m unittest discover -s tests -v
```

The suite tests the completion state machine, output formatting, cookie parsing/normalization, anti-recursion behavior, and local Playwright DOM behavior. It does not bypass or automate ChatGPT authentication challenges.

## Status output

Successful runs return:

```text
### ChatGPT Task Status
**COMPLETED**

### Result
<final ChatGPT result>
```

Other possible states are `STOPPED`, `FAILED`, and `NEEDS USER ACTION`.

## Notes

ChatGPT.com's DOM can change. This implementation intentionally prefers Playwright locators and accessible attributes, with defensive selector fallbacks. If the UI changes substantially, update the selector lists in `ChatGPTBrowser` rather than weakening completion verification.
