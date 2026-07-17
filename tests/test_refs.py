import sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from apple_mail_mcp import _encode_email_ref, _decode_email_ref


def test_roundtrip_ascii():
    ref = _encode_email_ref("Yahoo!", "INBOX", "abc@example.com")
    assert _decode_email_ref(ref) == ("Yahoo!", "INBOX", "abc@example.com")

def test_roundtrip_unicode_mailbox():
    ref = _encode_email_ref("Google", "Особисті", "id@x")
    assert _decode_email_ref(ref) == ("Google", "Особисті", "id@x")

def test_malformed_raises_valueerror():
    with pytest.raises(ValueError):
        _decode_email_ref("!!!not-base64!!!")

def test_missing_key_raises_valueerror():
    import base64, json
    bad = base64.urlsafe_b64encode(json.dumps({"a": "x"}).encode()).decode()
    with pytest.raises(ValueError):
        _decode_email_ref(bad)
