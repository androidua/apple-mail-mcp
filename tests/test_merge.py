import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from apple_mail_mcp import _merge_results

def r(acct, mbx, mid, epoch):
    return {"account": acct, "mailbox": mbx, "message_id": mid,
            "subject": "s", "sender": "x@y", "date": "d",
            "read": True, "epoch_rel": epoch}

def test_cross_account_interleave_by_recency():
    """Regression for B1: newest-first across accounts, not first-account-wins."""
    rows = [r("A", "INBOX", "a1", -100), r("A", "INBOX", "a2", -300),
            r("B", "INBOX", "b1", -50),  r("B", "INBOX", "b2", -200)]
    out = _merge_results(rows, limit=3)
    assert [(x["account"], x["message_id"]) for x in out] == [
        ("B", "b1"), ("A", "a1"), ("B", "b2")]

def test_dedup_same_account_prefers_inbox_over_all_mail():
    """Regression for B2: Gmail label duplicates collapse to one row."""
    rows = [r("G", "All Mail", "m1", -10), r("G", "INBOX", "m1", -10),
            r("G", "Important", "m1", -10)]
    out = _merge_results(rows, limit=10)
    assert len(out) == 1 and out[0]["mailbox"] == "INBOX"

def test_same_message_id_across_accounts_not_deduped():
    rows = [r("A", "INBOX", "m1", -10), r("B", "INBOX", "m1", -10)]
    assert len(_merge_results(rows, limit=10)) == 2

def test_truncates_after_sort():
    rows = [r("A", "INBOX", f"m{i}", -i) for i in range(10, 0, -1)]
    out = _merge_results(rows, limit=4)
    assert [x["epoch_rel"] for x in out] == [-1, -2, -3, -4]

def test_custom_label_dupe_prefers_inbox():
    rows = [r("G", "Робочі", "m1", -10), r("G", "INBOX", "m1", -10)]
    out = _merge_results(rows, limit=10)
    assert out[0]["mailbox"] == "INBOX"
