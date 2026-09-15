"""A label next to a figure is cropped whole or left out — never sliced.

The crop is clamped to the model's box. A narrow text block within reach of
the drawing used to be absorbed as a label and then clamped, so a loose box
around a rectangular prism kept "Volume = l" and "Surface Ar" from the
formulas beside it. Now a label the box just missed (an axis number a few
points outside) is taken in full, and a block that reaches further than
``label_reach`` past the box is left out entirely.
"""
import fitz

from worksheets.services import _smart_diagram_rect


def _page(label_text, label_x):
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.draw_rect(fitz.Rect(100, 100, 200, 200), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.insert_text((label_x, 150), label_text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    doc = fitz.open(stream=data, filetype='pdf')
    return doc, doc[0]


def _label_rect(page):
    return fitz.Rect(page.get_text('blocks')[0][:4])


def test_a_short_label_just_outside_the_box_is_taken_whole():
    doc, page = _page('h', 206)                 # a side label 6 pt right of the figure
    label = _label_rect(page)
    search = fitz.Rect(95, 95, 208, 205)        # the box clips the label in half
    assert search.x1 < label.x1
    clip = _smart_diagram_rect(page, search)
    assert clip is not None
    assert clip.contains(label)                 # whole label, past the box edge
    doc.close()


def test_a_block_reaching_far_past_the_box_is_left_out_not_sliced():
    doc, page = _page('Volume = lwh   Surface Area = 2(lw + wh + hl)', 216)
    label = _label_rect(page)
    search = fitz.Rect(95, 95, 240, 205)        # the box cuts through the formulas
    clip = _smart_diagram_rect(page, search)
    assert clip is not None
    # Not sliced: the crop stops at the figure plus its margins (6 pt from the
    # tight rect, 4 pt from the label growth), well before the text.
    assert clip.x1 <= 200 + 6 + 4 + 0.5
    assert not clip.intersects(label)
    doc.close()


def test_a_label_inside_the_box_behaves_as_before():
    doc, page = _page('h', 206)
    label = _label_rect(page)
    search = fitz.Rect(90, 90, 260, 210)
    clip = _smart_diagram_rect(page, search)
    assert clip.contains(label) and search.contains(clip)
    doc.close()
