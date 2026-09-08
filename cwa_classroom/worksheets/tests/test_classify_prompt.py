"""The chunk classification prompt must tell Claude to set has_image by NECESSITY
(only when the figure carries information the text doesn't), not eagerly for any
question that happens to sit near a visual. The eager wording caused a nearby
figure (e.g. a line graph) to be stapled onto a self-contained question.

Zero-token: the Anthropic client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

from worksheets import services


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        resp = MagicMock()
        block = MagicMock()
        block.type = 'tool_use'
        block.name = 'classify_worksheet_questions'
        block.input = {'questions': []}
        resp.content = [block]
        resp.usage.input_tokens = 1
        resp.usage.output_tokens = 1
        return resp


def _capture_prompt(shape_naming=False):
    captured = {}
    client = MagicMock()

    def stream(**kwargs):
        captured['messages'] = kwargs['messages']
        return _FakeStream()

    client.messages.stream.side_effect = stream
    pages = [{'page_num': 1, 'screenshot': 'x', 'screenshot_w': 10,
              'screenshot_h': 10, 'text': 't'}]
    services._classify_page_chunk(client, 'sys', pages, 1, shape_naming=shape_naming)
    return ' '.join(b['text'] for b in captured['messages'][0]['content']
                    if b.get('type') == 'text')


def test_chunk_prompt_uses_necessity_not_eager_wording():
    txt = _capture_prompt()
    assert 'has_image=true ONLY when' in txt                       # necessity rule
    assert 'prefer has_image=false' in txt
    assert 'for each question with a shape' not in txt.lower()     # old eager wording gone
    # Guards the cross-question mislocation that produced the wrong image.
    assert "another question's figure" in txt
    assert 'answer options' in txt


def test_shape_naming_prompt_still_requests_images():
    # Name-the-shape mode legitimately wants one boxed image per shape.
    txt = _capture_prompt(shape_naming=True)
    assert 'has_image=true' in txt
