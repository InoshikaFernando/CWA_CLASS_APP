"""A content-safety refusal from Claude (stop_reason == 'refusal') must surface a
clear message rather than the generic "no structured data" error — otherwise a
blocked worksheet looks identical to a parse failure.

Zero-token: the Anthropic client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

import pytest

from worksheets import services


class _RefusalStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        resp = MagicMock(stop_reason='refusal')
        resp.content = []  # no tool_use, no text — as a refusal returns
        return resp


def test_classify_chunk_refusal_raises_clear_message():
    client = MagicMock()
    client.messages.stream.side_effect = lambda **kw: _RefusalStream()
    pages = [{'page_num': 1, 'screenshot': 'x', 'screenshot_w': 10,
              'screenshot_h': 10, 'text': 't'}]

    with pytest.raises(ValueError) as exc:
        services._classify_page_chunk(client, 'sys', pages, 1)

    msg = str(exc.value).lower()
    assert 'declined' in msg or 'safety' in msg
