import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from apple_mail_mcp import _sanitize_for_applescript as san


def test_strips_c0_and_c1_controls():
    assert san("a\x00b\x08c\x1fd\x7fe\x85f\x9fg") == "abcdefg"

def test_keeps_tab_newline_cr():
    assert san("a\tb\nc\rd") == "a\tb\nc\rd"

def test_escapes_backslash_before_quote():
    # \ -> \\ first, then " -> \" ; input \" must become \\\"
    assert san('\\"') == '\\\\\\"'

def test_truncates_after_stripping():
    assert len(san("x" * 600)) == 500

def test_plain_string_unchanged():
    assert san("invoice from Alice") == "invoice from Alice"
