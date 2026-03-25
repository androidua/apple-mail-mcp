# Apple Mail MCP Server (READ ONLY)

A minimal, **read-only** MCP (Model Context Protocol) server that lets Claude Desktop interact with Apple Mail on macOS. Uses AppleScript via `subprocess` — no third-party email libraries, no network calls.

## Version

Current: **1.1.4**

Versioning follows [Semantic Versioning](https://semver.org/):
- **MAJOR** — breaking changes to the tool API or behaviour
- **MINOR** — new tools or non-breaking feature additions
- **PATCH** — bug fixes and security hardening

## What it can do

| Tool | Description |
|------|-------------|
| `mail_list_mailboxes` | List every account and mailbox configured in Apple Mail |
| `mail_search_emails` | Search emails by keyword across all mailboxes (uses Mail's native search index); optional `account` and `mailbox_name` filters for scoped searches |
| `mail_read_email` | Read the full content of a specific email by its opaque ID |

## What it will never do

- Delete, trash, move, or archive any email
- Send, reply, forward, or compose any message
- Write any file to disk or export data
- Make network requests or external connections
- Access or decode email attachments
- Provide analytics or aggregate statistics

## Prerequisites

- macOS (Apple Mail is macOS-only)
- Python 3.10 or later
- Apple Mail configured with at least one account
- Claude Desktop (or any MCP-compatible client)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/androidua/apple-mail-mcp.git
cd apple-mail-mcp
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. Verify the server starts cleanly

```bash
venv/bin/python apple_mail_mcp.py
```

Press `Ctrl-C` to stop. If no errors appear, the server is ready.

### 4. Grant macOS Automation permission

The first time the server runs, macOS will ask whether this process may control Apple Mail. Click **OK**. You can manage this later in:

> **System Settings → Privacy & Security → Automation**

### 5. Configure Claude Desktop

Open (or create) `~/Library/Application Support/Claude/claude_desktop_config.json` and add the block shown below under `"mcpServers"`.

```json
{
  "mcpServers": {
    "apple_mail": {
      "command": "/path/to/apple-mail-mcp/venv/bin/python",
      "args": [
        "/path/to/apple-mail-mcp/apple_mail_mcp.py"
      ]
    }
  }
}
```

Replace `/path/to/apple-mail-mcp` with the absolute path to the directory where you cloned the repository (e.g. `/Users/yourname/projects/apple-mail-mcp`).

Restart Claude Desktop after saving the file.

## Usage examples

Once connected, you can ask Claude things like:

- *"List all my email mailboxes"*
- *"Search my emails for messages from Alice"*
- *"Find emails with 'invoice' in the subject, show me the top 5"*
- *"Read the email about the project kickoff"* (after a search returns an ID)

## Security notes

- **No destructive operations.** Every AppleScript is read-only.
- **Input sanitisation.** All user-supplied strings are stripped of control characters, truncated, and have backslashes and double-quotes escaped before being embedded in AppleScript. This prevents script-injection attacks.
- **Local only.** The server uses stdio transport and never opens a network socket.
- **No credentials stored.** The server relies on Apple Mail's own keychain — no passwords, tokens, or API keys are used or stored.

## Performance

`mail_search_emails` uses AppleScript's `whose` clause — a declarative predicate evaluated by Mail's Objective-C runtime — to filter messages by subject and sender. This is fast even on accounts with hundreds of thousands of messages, and works correctly on macOS 26 / Mail 16 (which removed the older `search <mailbox> for <keyword>` AppleScript command). System mailboxes (Trash, Junk, Spam) are skipped by default.

To further scope a search, pass the optional `account` and/or `mailbox_name` parameters — e.g. restrict to `account="Yahoo"` and `mailbox_name="INBOX"` to avoid scanning all accounts.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `AppleScript failed … not allowed to send Apple events` | Go to **System Settings → Privacy & Security → Automation** and enable Mail for your Python process. |
| `No mailboxes found` | Open Apple Mail and ensure at least one account is signed in. |
| Tool times out | Use `account` and/or `mailbox_name` to scope the search, or reduce `limit`. |
| `Invalid email_id` | Always pass the `email_id` back exactly as returned by `mail_search_emails`. |

## Project structure

```
apple-mail-mcp/
├── apple_mail_mcp.py   # MCP server — single file, all tools
├── requirements.txt    # Pinned dependencies
├── README.md           # This file
└── venv/               # Local virtual environment (not committed)
```

## Changelog

### 1.1.4 — 2026-03-25
- **Fix (regression):** revert `_script_read_email` to proven account/mailbox iteration — direct AppleScript addressing (`mailbox X of account Y`) was unreliable for non-standard account types (Gmail, Exchange, shared accounts)
- **Fix (regression):** revert `mail_search_emails` JSON output to flat array `[...]` — the `{"results": [...]}` wrapper introduced in v1.1.3 broke Claude AI's ability to extract `email_id` values from results
- **Fix:** improve AppleScript error categorisation — errors now return actionable messages (Mail not running, Automation permission denied, item not found) instead of a generic fallback; raw AppleScript error text is still logged internally

### 1.1.3 — 2026-03-25
- **Fix (reliability):** close asyncio pipe transports before `await proc.wait()` on timeout — prevents file descriptor accumulation under repeated Mail.app timeouts
- **Fix (reliability):** anchor `---BODY_START---` split to a leading newline — prevents a subject line containing that exact string from corrupting header parsing in `mail_read_email`
- **Fix (security):** parse search output fields from both ends of the delimiter-split record — a `\x1f` byte in a subject no longer shifts sender/date/is_read columns
- **Fix (security):** extend `_CTRL_STRIP_RE` to cover C1 controls U+0080–U+009F (including U+0085 NEL which Python's `splitlines()` treats as a line terminator)
- **Fix (security):** log raw `osascript` stderr internally; return a generic error string to callers instead of forwarding script fragments
- **Perf:** replace nested account/mailbox iteration in `_script_read_email` with direct AppleScript object addressing (`mailbox X of account Y`) — O(1) lookup instead of O(accounts × mailboxes) name scan
- **Docs:** correct `whose` docstring — it is O(n) per mailbox, not indexed; low `limit` does not reduce scan cost
- **UX:** search results now report a warning when rows were silently skipped due to parse errors

### 1.1.2 — 2026-03-09
- **Fix:** replaced backslash line-continuation characters (`\`) in the
  `_script_read_email` AppleScript template with sequential assignments —
  AppleScript uses `¬` for continuation, not `\`; the invalid characters caused
  all `mail_read_email` calls to fail with AppleScript syntax error -2741

### 1.1.1 — 2026-03-09
- **Fix:** replaced `search <mailbox> for <keyword>` AppleScript command with a
  `whose` clause filter — the `search` command was removed in Mail 16 (macOS 26)
  and caused all `mail_search_emails` calls to fail with an AppleScript syntax error

### 1.1.0 — 2026-03-09
- **Performance:** `mail_search_emails` now uses Apple Mail's native indexed
  search (`search <mailbox> for <keyword>`) instead of brute-force message
  iteration — dramatically faster on large mailboxes (e.g. Yahoo with 20+ years
  of email)
- **Feature:** added optional `account` and `mailbox_name` parameters to
  `mail_search_emails` for scoped searches (e.g. search only Yahoo / INBOX)
- **Default exclusion:** Trash, Deleted Messages, Junk, Spam, Bulk Mail are
  skipped automatically unless explicitly targeted via `mailbox_name`

### 1.0.0 — 2026-03-09
- Initial release
- Tools: `mail_list_mailboxes`, `mail_search_emails`, `mail_read_email`
- Read-only, AppleScript-based, no network calls
- Input sanitisation against AppleScript injection
