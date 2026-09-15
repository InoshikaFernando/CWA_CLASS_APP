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


def _capture_prompt():
    captured = {}
    client = MagicMock()

    def stream(**kwargs):
        captured['messages'] = kwargs['messages']
        return _FakeStream()

    client.messages.stream.side_effect = stream
    pages = [{'page_num': 1, 'screenshot': 'x', 'screenshot_w': 10,
              'screenshot_h': 10, 'text': 't'}]
    services._classify_page_chunk(client, 'sys', pages, 1)
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


def test_chunk_prompt_asks_for_one_name_the_shape_item_per_shape():
    # There is no separate shape mode any more: the same request tells the model
    # that a sheet of shapes is one name_the_shape question per shape, each with
    # its own tight box, alongside the page's ordinary questions.
    txt = _capture_prompt()
    assert 'name_the_shape' in txt
    assert 'PER shape' in txt
    assert 'has_image=true' in txt
