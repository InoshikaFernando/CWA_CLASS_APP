"""A content-safety refusal from Claude (stop_reason == 'refusal') must surface a
clear message rather than the generic "no structured data" error — so a blocked
PDF is distinguishable from a genuine parse failure.

Zero-token: the Anthropic client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

import pytest

from ai_import.services import _classify_page_batch


class _RefusalStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        resp = MagicMock(stop_reason='refusal')
        resp.content = []  # no tool_use, no text — as a refusal returns
        return resp


def test_classify_batch_refusal_raises_clear_message():
    client = MagicMock()
    client.messages.stream.side_effect = lambda **kw: _RefusalStream()
    pages = [{'page_num': 1, 'screenshot': 'x', 'text': 't', 'images': []}]

    with pytest.raises(ValueError) as exc:
        _classify_page_batch(client, 'sys', pages, total_page_count=1)

    msg = str(exc.value).lower()
    assert 'declined' in msg or 'safety' in msg
