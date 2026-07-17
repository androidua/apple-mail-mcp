# CLAUDE.md — Apple Mail MCP Server

## Project overview

Read-only Apple Mail MCP server. Exposes three tools to Claude Desktop via stdio transport. Uses AppleScript via `subprocess` — no third-party email libraries, no network calls.

## Commands

```bash
# Start the server manually (for testing)
venv/bin/python apple_mail_mcp.py

# Syntax check
venv/bin/python -m py_compile apple_mail_mcp.py && echo "OK"

# Run the unit test suite (pure functions — no live Mail needed)
venv/bin/python -m pytest -q

# Reinstall dependencies into a fresh venv (runtime + dev)
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# Freeze current deps (after adding a new package)
venv/bin/pip freeze > requirements.txt
```

## Architecture

**Single file:** all server logic lives in `apple_mail_mcp.py`. Do not split into multiple files.

**Transport:** stdio only. The server never opens a network socket.

**AppleScript execution:**
- Run via `asyncio.create_subprocess_exec("osascript", "-e", script)`
- 60-second async timeout with `proc.kill()` on expiry
- All user strings pass through `_sanitize_for_applescript()` before embedding
- **Line continuation:** AppleScript uses `¬` (U+00AC), NOT `\`. When scripts are passed via `osascript -e`, the parser is strict — a `\` at end of line produces error -2741 ("Expected expression but found unknown token"). Always use sequential assignment statements instead of multi-line expressions.

**Search strategy (`mail_search_emails`):**
- **Pipeline (v1.3.0):** each mailbox emits up to `limit` newest matches (per-**mailbox** cap, NOT per-account) → Python `_parse_search_rows()` parses the delimited rows → `_merge_results()` dedups by `(account, message_id)`, sorts newest-first, truncates to `limit`. This replaced the old "concatenate per-account outputs, truncate at limit in account order" loop, which let the first responding account fill the whole result list and silently drop other accounts (bug B1). Any message in the true global top-`limit` is within the newest `limit` of its own mailbox, so per-mailbox collection + global sort is exact.
- **Sortable timestamp:** each row carries a relative-seconds field `(date received) - refDate`, where `refDate = (current date)` is captured once at script start. It is always a small negative integer. **Never emit absolute epochs** — AppleScript mangles large integers (32-bit/scientific-notation hazard); relative seconds avoid that and need no GMT correction. `_parse_search_rows` reads it via `int(float(...))`.
- **Skip list (default):** `Trash, Deleted Messages, Deleted Items, Junk, Junk Email, Junk E-mail, Spam, Bulk Mail, Bulk, All Mail, [Gmail]All Mail, Important, Starred, Outbox`. Covers real-world junk/trash names across iCloud/Yahoo/Gmail/Hotmail plus Gmail duplicate-view mailboxes (fixes B2/B3). `include_all_mailboxes=true` opts back in; an explicit `mailbox_name` bypasses the skip list.
- **`whose` clause** builds its predicate dynamically from active filters (keyword, `since_days`, `before_days`). **Why `whose` instead of `search`:** Mail 16 (macOS 26) removed the `search <mailbox> for <keyword>` command.
- `whose` is O(n) per mailbox at the Objective-C layer (~0.5–1.5k msgs/sec) — it fully materialises the match list before the per-mailbox cap applies. Low `limit` reduces output size, not scan cost. Because there is no global early-exit anymore, all non-skipped mailboxes are scanned; date-only wide-window searches are the slow case.
- `before_days` bounds the near edge of the window (`date received <= (current date) - (N * days)`); requires `since_days` and must be `< since_days` (enforced by the validator). Use it to page older mail without re-fetching.
- **Multi-account parallel execution:** when no `account` filter is set, the tool first calls `_SCRIPT_LIST_ACCOUNTS` to enumerate accounts, then runs one search script per account via `asyncio.gather(return_exceptions=True)` with a 45 s per-account timeout. A slow/offline IMAP account cannot block or crash results from other accounts. Timed-out accounts are listed as a warning in the response.
- When `account` is specified, a single script runs with a 60 s timeout (no gather overhead).
- **Do NOT call `proc.stdout.close()` or `proc.stderr.close()` on timeout** — `asyncio.StreamReader` has no `.close()` method. Use only `proc.kill()` + `await proc.wait()`.

**Progressive date window strategy (important for AI callers):**
Large `since_days` values (e.g. 365) on big IMAP accounts cause timeouts even with the 45 s per-account budget. Always start narrow and expand:
1. `since_days=7` → if fewer results than needed, try
2. `since_days=30` → if still not enough, try
3. `since_days=90` → last resort: `since_days=365`

Never jump straight to `since_days=365` for vague queries like "recent emails". This strategy is documented in the tool docstring so Claude AI follows it automatically.

**Email references:** opaque base64url-encoded JSON blobs `{"a": account, "m": mailbox, "i": message_id}`. Never expose raw Apple Mail message IDs to callers.

**Delimiters used inside AppleScript output:**
- `\x1f` — field separator (ASCII Unit Separator)
- `\x1e` — row separator (ASCII Record Separator)
- `---BODY_START---` — separates email headers from body in `mail_read_email`

## Input sanitisation (must not be weakened)

`_sanitize_for_applescript(value, max_length=500)`:
1. Strip C0 **and C1** control characters (U+0000–U+001F except `\t`, `\n`, `\r`, and U+007F–U+009F) via `_CTRL_STRIP_RE`
2. Truncate to `max_length`
3. Escape `\` → `\\`
4. Escape `"` → `\"`

This prevents AppleScript injection. Never bypass or remove these steps.

## Tools

| Tool | Input model | What it does |
|------|-------------|--------------|
| `mail_list_mailboxes` | `ListMailboxesInput` | Lists all accounts and mailboxes; optional `include_counts` for per-mailbox message counts |
| `mail_search_emails` | `SearchEmailsInput` | Search by keyword and/or date window; at least one of keyword/`since_days` required; optional `account`, `mailbox_name`, `before_days`, `include_all_mailboxes`; results merged/deduped/sorted newest-first across accounts (parallel per-account execution) |
| `mail_read_email` | `ReadEmailInput` | Reads full email by opaque `email_id` (60 s timeout) |

**`SearchEmailsInput` key fields:**
- `keyword` — optional (was required pre-v1.2.0); matched against subject and sender
- `since_days` — optional integer 1–365; filters by `date received >= (current date) - (N * days)`
- `before_days` — optional integer 1–365; upper (near-edge) window bound; requires `since_days` and must be `< since_days`
- `include_all_mailboxes` — bool (default false); search normally-skipped junk/trash/duplicate-view mailboxes too
- At least one of `keyword` / `since_days` must be provided (enforced by `model_validator`)
- Body content search is intentionally unsupported — `whose content contains` forces full body download for every message

**`ListMailboxesInput`:** `include_counts` (bool, default false) adds per-mailbox message counts as search-scoping metadata (~10 s for ~66 mailboxes; 120 s timeout when enabled).

**Tests:** `tests/` holds pytest unit tests for the pure functions (`_sanitize_for_applescript`, email-ref codec, `_parse_search_rows`, `_merge_results`, `_script_search_emails` builder). The single-file rule applies to **server logic only** — tests live in `tests/`. `pytest` is pinned in `requirements-dev.txt` (dev-only; never add it to `requirements.txt`). **Never verify code changes through the connected `apple_mail` MCP tools** — that process runs the old server; use an in-process driver via `venv/bin/python`.

All tools are annotated `readOnlyHint=True`, `destructiveHint=False`.

## Hard constraints — never violate

- **No destructive operations** — no delete, trash, move, archive
- **No write operations** — no send, reply, forward, compose
- **No file I/O** — no writing to disk, no export
- **No network calls** — no HTTP requests, no sockets
- **No attachment access** — no decoding or reading attachments
- **No analytics** — no aggregate statistics beyond per-mailbox message counts (`include_counts`), which exist only for search scoping

## Versioning

Semantic versioning: `MAJOR.MINOR.PATCH`
- **MAJOR** — breaking change to tool API or behaviour
- **MINOR** — new tool or non-breaking feature
- **PATCH** — bug fix or security hardening

Update `VERSION = "x.y.z"` in `apple_mail_mcp.py`, add a changelog entry in `README.md`, and update `CLAUDE.md` to reflect any architectural or tool changes — all in the same commit.

## Git workflow

This is a **solo project** — always commit and push directly to `main`. Never create branches or pull requests.

```bash
git add -A
git commit -m "type: description"
git tag vX.Y.Z          # on releases only
git push origin main --tags
```

Commit types: `feat`, `fix`, `docs`, `refactor`, `chore`.

Always include a `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` trailer in every commit message.

## Dependencies

All packages pinned to exact versions in `requirements.txt`. After any `pip install` run `venv/bin/pip freeze > requirements.txt` and commit the updated file.

Key packages: `mcp==1.26.0`, `pydantic==2.12.5`.
