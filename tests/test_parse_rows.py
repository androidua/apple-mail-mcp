import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from apple_mail_mcp import _parse_search_rows

FS, RS = "\x1f", "\x1e"

def row(acct="A", mbx="INBOX", mid="m1", subj="Hello", sender="s@x",
        date="Mon", read="true", epoch="-100"):
    return FS.join([acct, mbx, mid, subj, sender, date, read, epoch])

def test_parses_well_formed_row():
    rows, skipped = _parse_search_rows([row()])
    assert skipped == 0 and len(rows) == 1
    r = rows[0]
    assert (r["account"], r["mailbox"], r["message_id"]) == ("A", "INBOX", "m1")
    assert r["subject"] == "Hello" and r["read"] is True and r["epoch_rel"] == -100

def test_field_sep_inside_subject_reassembled():
    raw = FS.join(["A", "INBOX", "m1", "part1", "part2", "s@x", "Mon", "true", "-5"])
    rows, skipped = _parse_search_rows([raw])
    assert rows[0]["subject"] == "part1\x1fpart2" and skipped == 0

def test_short_row_skipped():
    rows, skipped = _parse_search_rows(["only\x1ftwo"])
    assert rows == [] and skipped == 1

def test_bad_epoch_defaults_to_zero():
    rows, _ = _parse_search_rows([row(epoch="junk")])
    assert rows[0]["epoch_rel"] == 0

def test_scientific_notation_epoch_parsed():
    rows, _ = _parse_search_rows([row(epoch="-1.5E+3")])
    assert rows[0]["epoch_rel"] == -1500

def test_multiple_outputs_concatenate():
    rows, _ = _parse_search_rows([row(mid="m1") + RS + row(mid="m2"), row(acct="B")])
    assert len(rows) == 3
