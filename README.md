# Apple Mail MCP Server

A minimal, **read-only** MCP (Model Context Protocol) server that lets Claude Desktop interact with Apple Mail on macOS. Uses AppleScript via `subprocess` — no third-party email libraries, no network calls.

## Version

Current: **1.0.0**

Versioning follows [Semantic Versioning](https://semver.org/):
- **MAJOR** — breaking changes to the tool API or behaviour
- **MINOR** — new tools or non-breaking feature additions
- **PATCH** — bug fixes and security hardening

## What it can do

| Tool | Description |
|------|-------------|
| `mail_list_mailboxes` | List every account and mailbox configured in Apple Mail |
| `mail_search_emails` | Search emails by keyword (subject + sender) across all mailboxes |
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
      "command": "/Users/dmytrobondarenko/Desktop/ai-projects/apple-mail-mcp/venv/bin/python",
      "args": [
        "/Users/dmytrobondarenko/Desktop/ai-projects/apple-mail-mcp/apple_mail_mcp.py"
      ]
    }
  }
}
```

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

The `mail_search_emails` tool iterates through messages in every mailbox. For very large mailboxes this may take several seconds. Use the `limit` parameter (default 20, max 100) to keep searches fast.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `AppleScript failed … not allowed to send Apple events` | Go to **System Settings → Privacy & Security → Automation** and enable Mail for your Python process. |
| `No mailboxes found` | Open Apple Mail and ensure at least one account is signed in. |
| Tool times out | Reduce `limit` or search a less-populated mailbox. |
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

### 1.0.0 — 2026-03-09
- Initial release
- Tools: `mail_list_mailboxes`, `mail_search_emails`, `mail_read_email`
- Read-only, AppleScript-based, no network calls
- Input sanitisation against AppleScript injection
