#!/usr/bin/env python3
"""
Apple Mail MCP Server  v1.1.0
==============================

CAN DO:
  • Search emails by keyword — matches subject line and sender (From) field
  • List all mailboxes / folders available in Apple Mail
  • Read the full content of a specific email by its opaque ID
    (subject, sender, To, CC, date, read-status, body text)

CANNOT DO (hard limits — not configurable):
  • Delete, trash, move, or archive any email
  • Send, reply, forward, or compose any message
  • Write files, export data, or save anything to disk
  • Make network requests, HTTP calls, or connect to any external service
  • Access, extract, or decode email attachments
  • Provide analytics, statistics, or aggregate counts
  • Modify Apple Mail preferences, rules, or account settings

Transport:  stdio (local subprocess only — no network listener)
Interface:  AppleScript via subprocess.  No third-party email libraries.
Security:   All user-supplied strings are sanitised before being embedded
            in AppleScript to prevent script injection.
"""

import asyncio
import base64
import json
import re
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator, ConfigDict

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

VERSION = "1.1.0"

# ASCII control characters used as delimiters in AppleScript output.
# Chosen because they are semantically correct (ASCII RS/US) and virtually
# never appear in email subject lines or sender addresses.
_FIELD_SEP  = "\x1f"   # ASCII Unit Separator  — field boundary
_ROW_SEP    = "\x1e"   # ASCII Record Separator — row / message boundary
_BODY_MARKER = "---BODY_START---"

# Regex to strip dangerous C0 control characters while keeping
# printable whitespace (TAB 0x09, LF 0x0a, CR 0x0d).
_CTRL_STRIP_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# ──────────────────────────────────────────────────────────────────────────────
# MCP server initialisation
# ──────────────────────────────────────────────────────────────────────────────

mcp = FastMCP("apple_mail_mcp")

# ──────────────────────────────────────────────────────────────────────────────
# Input sanitisation
# ──────────────────────────────────────────────────────────────────────────────


def _sanitize_for_applescript(value: str, max_length: int = 500) -> str:
    """Make *value* safe to embed inside an AppleScript double-quoted string.

    Steps
    -----
    1. Strip C0 control characters (null bytes, BEL, BS, VT, FF, SO–US, DEL).
    2. Truncate to *max_length* to prevent resource exhaustion.
    3. Escape backslashes first (prevents additional escape-sequence injection).
    4. Escape double-quotes (the primary AppleScript injection vector — a
       bare ``"`` would close the string literal and allow arbitrary code).
    """
    value = _CTRL_STRIP_RE.sub("", value)
    value = value[:max_length]
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    return value


# ──────────────────────────────────────────────────────────────────────────────
# Opaque email reference  (account + mailbox + Message-ID → base64 blob)
# ──────────────────────────────────────────────────────────────────────────────


def _encode_email_ref(account: str, mailbox: str, message_id: str) -> str:
    """Return a URL-safe base64 string encoding all three location fields."""
    payload = {"a": account, "m": mailbox, "i": message_id}
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _decode_email_ref(ref: str) -> tuple[str, str, str]:
    """Decode a reference from ``_encode_email_ref``.

    Returns
    -------
    (account, mailbox, message_id)

    Raises
    ------
    ValueError if the reference is malformed.
    """
    try:
        # urlsafe_b64decode needs padding; add it idempotently.
        padded = ref + "==" * ((4 - len(ref) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        return str(payload["a"]), str(payload["m"]), str(payload["i"])
    except Exception as exc:
        raise ValueError(
            f"Invalid email_id — could not decode: {exc}. "
            "Use the email_id returned by mail_search_emails."
        ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# AppleScript runner
# ──────────────────────────────────────────────────────────────────────────────


async def _run_applescript(script: str, timeout: float = 60.0) -> str:
    """Execute *script* via ``osascript`` and return stdout as a string.

    Raises
    ------
    RuntimeError on non-zero exit code or timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(
            f"AppleScript timed out after {timeout:.0f} s. "
            "Try a more specific keyword or a smaller limit."
        )

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"AppleScript failed (exit {proc.returncode}): {err}")

    return stdout.decode("utf-8", errors="replace").strip()


# ──────────────────────────────────────────────────────────────────────────────
# AppleScript templates
# ──────────────────────────────────────────────────────────────────────────────

_SCRIPT_LIST_MAILBOXES = """\
tell application "Mail"
    set fs to (ASCII character 31)
    set rs to (ASCII character 30)
    set rows to {}
    repeat with anAccount in every account
        set acctName to name of anAccount
        repeat with aMailbox in every mailbox of anAccount
            set end of rows to acctName & fs & (name of aMailbox)
        end repeat
    end repeat
    if (count of rows) is 0 then return ""
    set AppleScript's text item delimiters to rs
    set out to rows as text
    set AppleScript's text item delimiters to ""
    return out
end tell
"""


def _script_search_emails(
    keyword_safe: str,
    limit: int,
    account_safe: str = "",
    mailbox_safe: str = "",
) -> str:
    """Build the AppleScript for searching emails.

    Uses Mail's native indexed ``search <mailbox> for <keyword>`` command instead
    of iterating all messages, making it dramatically faster on large mailboxes.

    *keyword_safe*, *account_safe*, and *mailbox_safe* must already have been
    processed by ``_sanitize_for_applescript``.

    When *mailbox_safe* is empty, system mailboxes (Trash, Junk, etc.) are
    excluded automatically. When a specific *mailbox_safe* is given, that
    exclusion is skipped so the user can explicitly search Trash if desired.

    Python f-string: ``{{}}`` → ``{}``  (empty AppleScript list literal).
    """
    return f"""\
tell application "Mail"
    set fs to (ASCII character 31)
    set rs to (ASCII character 30)
    set kw to "{keyword_safe}"
    set maxResults to {limit}
    set filterAccount to "{account_safe}"
    set filterMailbox to "{mailbox_safe}"
    set skipNames to {{"Trash", "Deleted Messages", "Junk", "Spam", "Bulk Mail", "Junk E-mail"}}
    set rows to {{}}
    set resultCount to 0
    repeat with anAccount in every account
        if resultCount >= maxResults then exit repeat
        set acctName to name of anAccount
        if filterAccount is "" or acctName is filterAccount then
            repeat with aMailbox in every mailbox of anAccount
                if resultCount >= maxResults then exit repeat
                set mbxName to name of aMailbox
                set shouldSkip to false
                if filterMailbox is not "" then
                    if mbxName is not filterMailbox then set shouldSkip to true
                else
                    if skipNames contains mbxName then set shouldSkip to true
                end if
                if not shouldSkip then
                    try
                        set matchedMsgs to search aMailbox for kw
                        repeat with aMsg in matchedMsgs
                            if resultCount >= maxResults then exit repeat
                            try
                                set msgId to message id of aMsg
                                set msgSubj to subject of aMsg
                                set msgFrom to sender of aMsg
                                set msgDate to (date received of aMsg) as string
                                set isReadStr to "false"
                                if read status of aMsg then set isReadStr to "true"
                                set end of rows to acctName & fs & mbxName & fs & msgId & fs & msgSubj & fs & msgFrom & fs & msgDate & fs & isReadStr
                                set resultCount to resultCount + 1
                            end try
                        end repeat
                    end try
                end if
            end repeat
        end if
    end repeat
    if (count of rows) is 0 then return ""
    set AppleScript's text item delimiters to rs
    set out to rows as text
    set AppleScript's text item delimiters to ""
    return out
end tell
"""


def _script_read_email(
    account_safe: str, mailbox_safe: str, msg_id_safe: str
) -> str:
    """Build the AppleScript to fetch a single email's full content."""
    return f"""\
tell application "Mail"
    set acctTarget to "{account_safe}"
    set mbxTarget  to "{mailbox_safe}"
    set idTarget   to "{msg_id_safe}"
    set found to false
    repeat with anAccount in every account
        if (name of anAccount) = acctTarget then
            repeat with aMailbox in every mailbox of anAccount
                if (name of aMailbox) = mbxTarget then
                    try
                        set matched to (messages of aMailbox whose message id = idTarget)
                        if (count of matched) > 0 then
                            set aMsg to item 1 of matched
                            set msgSubject to subject of aMsg
                            set msgSender  to sender of aMsg
                            set msgDate    to (date received of aMsg) as string
                            set msgContent to content of aMsg
                            set isReadStr  to "false"
                            if read status of aMsg then set isReadStr to "true"
                            set toStr to ""
                            repeat with r in (to recipients of aMsg)
                                if toStr is not "" then set toStr to toStr & ", "
                                try
                                    set toStr to toStr & (name of r) & " <" & (address of r) & ">"
                                on error
                                    try
                                        set toStr to toStr & (address of r)
                                    end try
                                end try
                            end repeat
                            set ccStr to ""
                            repeat with r in (cc recipients of aMsg)
                                if ccStr is not "" then set ccStr to ccStr & ", "
                                try
                                    set ccStr to ccStr & (name of r) & " <" & (address of r) & ">"
                                on error
                                    try
                                        set ccStr to ccStr & (address of r)
                                    end try
                                end try
                            end repeat
                            set nl to (ASCII character 10)
                            set out to "SUBJECT: " & msgSubject & nl & \\
                                       "FROM: "    & msgSender  & nl & \\
                                       "TO: "      & toStr      & nl & \\
                                       "CC: "      & ccStr      & nl & \\
                                       "DATE: "    & msgDate    & nl & \\
                                       "READ: "    & isReadStr  & nl & \\
                                       "---BODY_START---" & nl  & \\
                                       msgContent
                            set found to true
                            return out
                        end if
                    end try
                    exit repeat
                end if
            end repeat
            exit repeat
        end if
    end repeat
    if not found then
        return "ERROR: Message not found in the specified account/mailbox"
    end if
end tell
"""


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic input models
# ──────────────────────────────────────────────────────────────────────────────


class ListMailboxesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    response_format: str = Field(
        default="markdown",
        description="Output format: 'markdown' (default, human-readable) or 'json' (machine-readable).",
        pattern=r"^(markdown|json)$",
    )


class SearchEmailsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    keyword: str = Field(
        ...,
        description=(
            "Keyword to search for. Matched case-insensitively against the "
            "email subject line and the sender (From) field across all mailboxes."
        ),
        min_length=1,
        max_length=200,
    )
    limit: int = Field(
        default=20,
        description="Maximum number of results to return (1–100). Default: 20.",
        ge=1,
        le=100,
    )
    account: Optional[str] = Field(
        default=None,
        description=(
            "Restrict the search to this account name only "
            "(e.g. 'iCloud', 'Yahoo'). "
            "Omit to search across all accounts."
        ),
        max_length=200,
    )
    mailbox_name: Optional[str] = Field(
        default=None,
        description=(
            "Restrict the search to this mailbox name only "
            "(e.g. 'INBOX', 'Sent Messages'). "
            "Omit to search all non-system mailboxes. "
            "Use with 'account' to target a specific mailbox precisely."
        ),
        max_length=200,
    )
    response_format: str = Field(
        default="markdown",
        description="Output format: 'markdown' (default) or 'json'.",
        pattern=r"^(markdown|json)$",
    )

    @field_validator("keyword")
    @classmethod
    def keyword_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("keyword must not be blank or whitespace only")
        return v.strip()


class ReadEmailInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email_id: str = Field(
        ...,
        description=(
            "Opaque email reference returned by mail_search_emails. "
            "Pass it back exactly as received — do not modify or construct it manually."
        ),
        min_length=4,
        max_length=4096,
    )
    response_format: str = Field(
        default="markdown",
        description="Output format: 'markdown' (default) or 'json'.",
        pattern=r"^(markdown|json)$",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool: mail_list_mailboxes
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="mail_list_mailboxes",
    annotations={
        "title": "List Apple Mail Mailboxes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mail_list_mailboxes(params: ListMailboxesInput) -> str:
    """List all mailboxes/folders available in Apple Mail, grouped by account.

    Queries Apple Mail via AppleScript to retrieve every configured account
    and all mailboxes within each account (INBOX, Sent Messages, Drafts,
    custom folders, etc.). Strictly read-only — no emails are modified and
    no network calls are made.

    Args:
        params (ListMailboxesInput): Input containing:
            - response_format (str): 'markdown' (default) or 'json'.

    Returns:
        str: Formatted list of all accounts and their mailboxes.

        Markdown example:
            # Apple Mail Mailboxes

            ## iCloud
            - INBOX
            - Sent Messages
            - Drafts

        JSON example:
            [
              {"account": "iCloud", "mailbox": "INBOX"},
              {"account": "iCloud", "mailbox": "Sent Messages"}
            ]

    Examples:
        - Use when: "What mailboxes do I have?" → default params
        - Use when: "List my email folders as JSON" → response_format="json"

    Error Handling:
        Returns an error string if Mail.app cannot be reached or there are
        no configured accounts. Prompts the user to open Mail.app if needed.
    """
    try:
        raw = await _run_applescript(_SCRIPT_LIST_MAILBOXES)
    except RuntimeError as exc:
        return f"Error accessing Apple Mail: {exc}"

    if not raw:
        return (
            "No mailboxes found. "
            "Make sure Apple Mail is open and at least one account is configured."
        )

    records: list[dict[str, str]] = []
    for row in raw.split(_ROW_SEP):
        parts = row.split(_FIELD_SEP, 1)
        if len(parts) == 2 and any(p.strip() for p in parts):
            records.append({"account": parts[0], "mailbox": parts[1]})

    if not records:
        return "No mailboxes found."

    if params.response_format == "json":
        return json.dumps(records, indent=2, ensure_ascii=False)

    lines: list[str] = ["# Apple Mail Mailboxes", ""]
    current_account: Optional[str] = None
    for rec in records:
        if rec["account"] != current_account:
            current_account = rec["account"]
            lines.append(f"## {current_account}")
        lines.append(f"- {rec['mailbox']}")

    lines.append("")
    account_count = len({r["account"] for r in records})
    lines.append(
        f"*{len(records)} mailbox(es) across {account_count} account(s)*"
    )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Tool: mail_search_emails
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="mail_search_emails",
    annotations={
        "title": "Search Apple Mail Emails",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mail_search_emails(params: SearchEmailsInput) -> str:
    """Search Apple Mail for emails whose subject or sender matches a keyword.

    Searches across all configured accounts and all mailboxes using Apple
    Mail's native indexed search, which is fast even on mailboxes with
    hundreds of thousands of messages. System mailboxes (Trash, Junk, Spam)
    are excluded by default unless explicitly targeted via mailbox_name.
    Returns matching emails with opaque email_id values that can be passed to
    mail_read_email to retrieve the full message content.

    Args:
        params (SearchEmailsInput): Input containing:
            - keyword (str): Search term (1–200 chars). Required.
            - limit (int): Max results to return (default 20, max 100).
            - account (str): Optional. Restrict to one account (e.g. 'Yahoo').
            - mailbox_name (str): Optional. Restrict to one mailbox (e.g. 'INBOX').
            - response_format (str): 'markdown' (default) or 'json'.

    Returns:
        str: Matching emails with subject, sender, date, read-status, and email_id.

        Markdown example:
            # Search Results: "invoice"

            Found 3 email(s) matching "invoice"

            1. **Invoice for March**
               - From: billing@example.com
               - Mailbox: iCloud / INBOX
               - Date: Monday, 3 March 2025 at 09:14:02
               - Read: Yes
               - ID: `eyJhIjoiaUNsb3VkIi...`

        JSON example:
            [
              {
                "email_id": "eyJhIjoiaUNsb3VkIi...",
                "account": "iCloud",
                "mailbox": "INBOX",
                "subject": "Invoice for March",
                "sender": "billing@example.com",
                "date": "Monday, 3 March 2025 at 09:14:02",
                "read": true
              }
            ]

    Examples:
        - Use when: "Find emails from Alice" → keyword="Alice"
        - Use when: "Search for invoice emails, top 5" → keyword="invoice", limit=5
        - Use when: "Search only Yahoo INBOX" → account="Yahoo", mailbox_name="INBOX"
        - Don't use when: You already have an email_id (use mail_read_email).

    Error Handling:
        - Returns an error string if Mail.app cannot be reached.
        - Returns a "No emails found" message if there are no matches.
        - Pydantic validates all inputs before any AppleScript runs.
    """
    keyword_safe  = _sanitize_for_applescript(params.keyword)
    account_safe  = _sanitize_for_applescript(params.account or "")
    mailbox_safe  = _sanitize_for_applescript(params.mailbox_name or "")
    script = _script_search_emails(keyword_safe, params.limit, account_safe, mailbox_safe)

    try:
        raw = await _run_applescript(script)
    except RuntimeError as exc:
        return f"Error accessing Apple Mail: {exc}"

    if not raw:
        return f'No emails found matching "{params.keyword}".'

    results: list[dict] = []
    for row in raw.split(_ROW_SEP):
        parts = row.split(_FIELD_SEP)
        if len(parts) < 7:
            continue
        account, mailbox, msg_id, subject, sender, date_str, is_read_str = parts[:7]
        if not account.strip() and not mailbox.strip():
            continue
        try:
            email_ref = _encode_email_ref(account, mailbox, msg_id)
        except Exception:
            continue
        results.append(
            {
                "email_id": email_ref,
                "account": account,
                "mailbox": mailbox,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "read": is_read_str.strip().lower() == "true",
            }
        )

    if not results:
        return f'No emails found matching "{params.keyword}".'

    if params.response_format == "json":
        return json.dumps(results, indent=2, ensure_ascii=False)

    lines: list[str] = [
        f'# Search Results: "{params.keyword}"',
        "",
        f'Found {len(results)} email(s) matching "{params.keyword}"',
        "",
    ]
    for i, r in enumerate(results, 1):
        read_label = "Yes" if r["read"] else "No"
        lines += [
            f"{i}. **{r['subject']}**",
            f"   - From: {r['sender']}",
            f"   - Mailbox: {r['account']} / {r['mailbox']}",
            f"   - Date: {r['date']}",
            f"   - Read: {read_label}",
            f"   - ID: `{r['email_id']}`",
            "",
        ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Tool: mail_read_email
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="mail_read_email",
    annotations={
        "title": "Read Apple Mail Email Content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mail_read_email(params: ReadEmailInput) -> str:
    """Read the full content of a specific Apple Mail email by its ID.

    Decodes the opaque email_id produced by mail_search_emails, locates the
    message in Apple Mail, and returns its complete content: subject, sender,
    recipients (To, CC), date received, read-status, and full body text.

    Strictly read-only — the message read-status is NOT changed by this call.

    Args:
        params (ReadEmailInput): Input containing:
            - email_id (str): Opaque ID from mail_search_emails. Required.
            - response_format (str): 'markdown' (default) or 'json'.

    Returns:
        str: Full email content.

        Markdown example:
            # Email: Invoice for March

            - **From**: billing@example.com
            - **To**: you@icloud.com
            - **CC**: (none)
            - **Date**: Monday, 3 March 2025 at 09:14:02
            - **Read**: Yes
            - **Mailbox**: iCloud / INBOX

            ## Body

            Hi there, please find your invoice attached...

        JSON example:
            {
              "subject": "Invoice for March",
              "sender": "billing@example.com",
              "to": "you@icloud.com",
              "cc": "",
              "date": "Monday, 3 March 2025 at 09:14:02",
              "read": true,
              "account": "iCloud",
              "mailbox": "INBOX",
              "body": "Hi there, please find your invoice attached..."
            }

    Examples:
        - Use when: "Read the email about invoices" (after searching)
          → pass the email_id from search results
        - Don't use when: You don't have an email_id yet
          → use mail_search_emails first

    Error Handling:
        - Returns an error if the email_id is malformed or expired.
        - Returns an error if the message cannot be found (e.g. deleted since search).
        - Returns an error if Mail.app cannot be reached.
    """
    try:
        account, mailbox, message_id = _decode_email_ref(params.email_id)
    except ValueError as exc:
        return f"Error: {exc}"

    account_safe = _sanitize_for_applescript(account, max_length=500)
    mailbox_safe = _sanitize_for_applescript(mailbox, max_length=500)
    msg_id_safe  = _sanitize_for_applescript(message_id, max_length=1000)

    script = _script_read_email(account_safe, mailbox_safe, msg_id_safe)

    try:
        raw = await _run_applescript(script, timeout=30.0)
    except RuntimeError as exc:
        return f"Error accessing Apple Mail: {exc}"

    if raw.startswith("ERROR:"):
        return f"Error: {raw[6:].strip()}"

    # Split header metadata from body content at the known marker.
    if _BODY_MARKER in raw:
        header_raw, body = raw.split(_BODY_MARKER, 1)
        body = body.lstrip("\n")
    else:
        header_raw = raw
        body = ""

    # Parse labelled header lines ("KEY: value").
    headers: dict[str, str] = {}
    for line in header_raw.splitlines():
        if ": " in line:
            key, _, value = line.partition(": ")
            headers[key.strip()] = value.strip()

    subject  = headers.get("SUBJECT", "(no subject)")
    sender   = headers.get("FROM", "")
    to_field = headers.get("TO", "")
    cc_field = headers.get("CC", "")
    date_str = headers.get("DATE", "")
    is_read  = headers.get("READ", "false").lower() == "true"

    if params.response_format == "json":
        return json.dumps(
            {
                "subject": subject,
                "sender":  sender,
                "to":      to_field,
                "cc":      cc_field,
                "date":    date_str,
                "read":    is_read,
                "account": account,
                "mailbox": mailbox,
                "body":    body,
            },
            indent=2,
            ensure_ascii=False,
        )

    read_label = "Yes" if is_read else "No"
    cc_display = cc_field if cc_field else "(none)"
    lines: list[str] = [
        f"# Email: {subject}",
        "",
        f"- **From**: {sender}",
        f"- **To**: {to_field}",
        f"- **CC**: {cc_display}",
        f"- **Date**: {date_str}",
        f"- **Read**: {read_label}",
        f"- **Mailbox**: {account} / {mailbox}",
        "",
        "## Body",
        "",
        body,
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
