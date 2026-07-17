import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from apple_mail_mcp import _script_search_emails

def test_epoch_emitted():
    s = _script_search_emails("kw", 20)
    assert "set refDate to (current date)" in s
    assert "(d - refDate)" in s

def test_expanded_skip_names_present():
    s = _script_search_emails("kw", 20)
    for name in ("All Mail", "[Gmail]All Mail", "Important", "Starred",
                 "Bulk", "Junk Email", "Deleted Items", "Outbox",
                 "Trash", "Junk", "Spam"):
        assert f'"{name}"' in s

def test_include_all_disables_skip():
    s = _script_search_emails("kw", 20, include_all=True)
    assert "set includeAll to true" in s

def test_per_mailbox_cap_variable():
    s = _script_search_emails("kw", 33)
    assert "set perMailboxCap to 33" in s
    assert "resultCount" not in s  # old per-account counter must be gone
