# CLAUDE.md — Apple Mail MCP Server

## Project overview

Read-only Apple Mail MCP server. Exposes three tools to Claude Desktop via stdio transport. Uses AppleScript via `subprocess` — no third-party email libraries, no network calls.

## Commands

```bash
# Start the server manually (for testing)
venv/bin/python apple_mail_mcp.py

# Syntax check
venv/bin/python -m py_compile apple_mail_mcp.py && echo "OK"

# Reinstall dependencies into a fresh venv
python3 -m venv venv
venv/bin/pip install -r requirements.txt

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
- Uses AppleScript's `whose` clause: `(messages of aMailbox whose subject contains kw or sender contains kw)`
- The `whose` predicate is evaluated server-side by Mail's Objective-C runtime — it is a declarative filter, not a Python-level iteration
- **Why `whose` instead of `search`:** Mail 16 (macOS 26) removed the `search <mailbox> for <keyword>` command from its AppleScript dictionary. The `whose` clause is the correct replacement.
- Trash, Deleted Messages, Junk, Spam, Bulk Mail, Junk E-mail are skipped by default when no `mailbox_name` filter is set
- Optional `account` and `mailbox_name` parameters scope the search; both are sanitised before embedding

**Email references:** opaque base64url-encoded JSON blobs `{"a": account, "m": mailbox, "i": message_id}`. Never expose raw Apple Mail message IDs to callers.

**Delimiters used inside AppleScript output:**
- `\x1f` — field separator (ASCII Unit Separator)
- `\x1e` — row separator (ASCII Record Separator)
- `---BODY_START---` — separates email headers from body in `mail_read_email`

## Input sanitisation (must not be weakened)

`_sanitize_for_applescript(value, max_length=500)`:
1. Strip C0 control characters (except `\t`, `\n`, `\r`) via regex
2. Truncate to `max_length`
3. Escape `\` → `\\`
4. Escape `"` → `\"`

This prevents AppleScript injection. Never bypass or remove these steps.

## Tools

| Tool | Input model | What it does |
|------|-------------|--------------|
| `mail_list_mailboxes` | `ListMailboxesInput` | Lists all accounts and mailboxes |
| `mail_search_emails` | `SearchEmailsInput` | Indexed keyword search; optional `account` and `mailbox_name` filters |
| `mail_read_email` | `ReadEmailInput` | Reads full email by opaque `email_id` |

All tools are annotated `readOnlyHint=True`, `destructiveHint=False`.

## Hard constraints — never violate

- **No destructive operations** — no delete, trash, move, archive
- **No write operations** — no send, reply, forward, compose
- **No file I/O** — no writing to disk, no export
- **No network calls** — no HTTP requests, no sockets
- **No attachment access** — no decoding or reading attachments
- **No analytics** — no aggregate statistics or counts

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
