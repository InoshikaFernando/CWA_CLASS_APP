"""Screen-capture helpers for the question-type showcase (marketing capture).

``test_question_showcase.py`` drives a real student through one homework
carrying every interactive maths question type and records the browser while it
happens. A normal UI test clicks as fast as Playwright can; a recording made
that way is unwatchable — nothing lands anywhere the eye can follow, and the
widgets that make these question types worth showing flick past in one frame.

So this module adds the three things a capture needs and a test does not:

* a **synthetic cursor** that travels to each target before the click, so the
  viewer sees the intent and not just the result;
* a **caption card** naming the question type being demonstrated;
* **pacing** — every step waits, scaled by ``pace`` so one number re-times the
  whole video.

All of it is injected into the page from the outside (``add_init_script``), so
nothing in the app's own templates or JavaScript knows the capture exists and
the recording shows the product exactly as a student gets it.
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path


def ensure_video_encoder():
    """Point Playwright at whatever ffmpeg build the image actually shipped.

    Video recording is encoded by a bundled ffmpeg whose build number is pinned
    per Playwright release. Managed images (Claude Code on the web, some CI
    images) pre-bake the browsers under ``PLAYWRIGHT_BROWSERS_PATH`` and block
    re-downloading, and the ffmpeg they baked is not always the build this
    playwright asks for. The mismatch fails ``new_page()`` with a bare
    "Executable doesn't exist at .../ffmpeg-1010/ffmpeg-linux" and a suggestion
    to run ``playwright install``, which the image will not allow — it reads
    like a broken install rather than a renamed file.
    ``conftest._preinstalled_chromium`` solves exactly this for the browser;
    this solves it for the recorder, by linking the newest build present to the
    name Playwright is looking for.

    Returns the path it made available, or None when there was nothing to do
    (expected build present, no pre-baked root, or the root is read-only — in
    which case the caller gets Playwright's own error, which is the honest one).
    """
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not root or not os.path.isdir(root):
        return None

    import playwright
    manifest = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    try:
        revisions = [b["revision"] for b in json.loads(manifest.read_text())["browsers"]
                     if b.get("name") == "ffmpeg"]
    except (OSError, ValueError, KeyError):
        return None
    if not revisions:
        return None

    wanted = Path(root) / f"ffmpeg-{revisions[0]}"
    if list(wanted.glob("ffmpeg-*")):
        return None                                   # the pinned build is there

    def build_number(path):
        match = re.search(r"-(\d+)/", path)
        return int(match.group(1)) if match else 0

    candidates = sorted(
        glob.glob(os.path.join(root, "ffmpeg-*/ffmpeg-*")), key=build_number)
    if not candidates:
        return None
    try:
        wanted.parent.mkdir(parents=True, exist_ok=True)
        if wanted.is_symlink() or wanted.exists():
            return None
        os.symlink(Path(candidates[-1]).parent, wanted)
    except OSError:
        return None
    return str(wanted)


# The overlay. Injected via add_init_script so it survives every navigation
# (login → take page → results page) without the test re-installing it.
_OVERLAY_JS = r"""
(() => {
  const CSS = `
    #cwa-demo-layer { position: fixed; inset: 0; z-index: 2147483000;
                      pointer-events: none; font-family: ui-sans-serif,
                      system-ui, -apple-system, "Segoe UI", sans-serif; }
    #cwa-demo-cursor { position: absolute; left: 0; top: 0; width: 26px;
                       height: 26px; margin: -13px 0 0 -13px; border-radius: 50%;
                       border: 2px solid rgba(37, 99, 235, .9);
                       background: rgba(59, 130, 246, .22);
                       box-shadow: 0 2px 10px rgba(15, 23, 42, .25);
                       transition: transform .42s cubic-bezier(.4, 0, .2, 1);
                       opacity: 0; }
    #cwa-demo-cursor.on { opacity: 1; }
    #cwa-demo-cursor.tap { animation: cwa-demo-tap .4s ease-out; }
    @keyframes cwa-demo-tap {
      0%   { box-shadow: 0 0 0 0 rgba(37, 99, 235, .55); }
      100% { box-shadow: 0 0 0 26px rgba(37, 99, 235, 0); }
    }
    /* Centred, not bottom-left: the app's sidebar owns the left gutter and a
       caption card sitting on top of its links looks like a rendering bug. */
    #cwa-demo-caption { position: absolute; left: 50%; bottom: 32px;
                        width: max-content; max-width: 34rem;
                        padding: 14px 22px; border-radius: 16px;
                        background: rgba(15, 23, 42, .92); color: #fff;
                        box-shadow: 0 18px 40px rgba(15, 23, 42, .35);
                        opacity: 0; transform: translate(-50%, 10px);
                        transition: opacity .45s ease, transform .45s ease; }
    #cwa-demo-caption.on { opacity: 1; transform: translate(-50%, 0); }
    #cwa-demo-caption .t { font-size: 21px; font-weight: 700;
                           letter-spacing: -.01em; line-height: 1.15; }
    #cwa-demo-caption .s { margin-top: 5px; font-size: 13.5px; line-height: 1.45;
                           color: rgba(226, 232, 240, .92); }
    /* Top-right, under the app header — the bottom-right corner is where the
       product keeps its own floating buttons. */
    #cwa-demo-chip { position: absolute; right: 32px; top: 78px;
                     padding: 7px 14px; border-radius: 999px; font-size: 12px;
                     font-weight: 600; letter-spacing: .04em;
                     text-transform: uppercase; color: #1e3a8a;
                     background: rgba(255, 255, 255, .94);
                     border: 1px solid rgba(37, 99, 235, .25);
                     box-shadow: 0 8px 22px rgba(15, 23, 42, .16);
                     opacity: 0; transition: opacity .4s ease; }
    #cwa-demo-chip.on { opacity: 1; }
    .cwa-demo-spot { position: relative; z-index: 1;
                     box-shadow: 0 0 0 3px rgba(37, 99, 235, .55),
                                 0 18px 45px rgba(37, 99, 235, .18) !important;
                     transition: box-shadow .4s ease; }
  `;

  function install() {
    if (!document.body || document.getElementById('cwa-demo-layer')) return;
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const layer = document.createElement('div');
    layer.id = 'cwa-demo-layer';
    layer.innerHTML =
      '<div id="cwa-demo-cursor"></div>' +
      '<div id="cwa-demo-caption"><div class="t"></div><div class="s"></div></div>' +
      '<div id="cwa-demo-chip"></div>';
    document.body.appendChild(layer);
  }

  const el = (id) => document.getElementById(id);

  window.__demoCursor = (x, y) => {
    install();
    const c = el('cwa-demo-cursor');
    if (!c) return;
    c.classList.add('on');
    c.style.transform = 'translate(' + x + 'px,' + y + 'px)';
  };

  window.__demoTap = () => {
    const c = el('cwa-demo-cursor');
    if (!c) return;
    c.classList.remove('tap');
    void c.offsetWidth;          // restart the animation
    c.classList.add('tap');
  };

  window.__demoCaption = (title, subtitle) => {
    install();
    const box = el('cwa-demo-caption');
    if (!box) return;
    box.querySelector('.t').textContent = title || '';
    box.querySelector('.s').textContent = subtitle || '';
    box.classList.add('on');
  };

  window.__demoCaptionHide = () => {
    const box = el('cwa-demo-caption');
    if (box) box.classList.remove('on');
  };

  window.__demoChip = (text) => {
    install();
    const chip = el('cwa-demo-chip');
    if (!chip) return;
    chip.textContent = text || '';
    chip.classList.toggle('on', Boolean(text));
  };

  window.__demoSpotlight = (node) => {
    install();
    document.querySelectorAll('.cwa-demo-spot')
            .forEach((n) => n.classList.remove('cwa-demo-spot'));
    if (!node) return;
    node.classList.add('cwa-demo-spot');
    const box = node.getBoundingClientRect();
    // Centre the card when it fits; otherwise put its top just under the header.
    const top = box.height < window.innerHeight - 120
      ? window.scrollY + box.top - (window.innerHeight - box.height) / 2
      : window.scrollY + box.top - 90;
    window.scrollTo({ top: Math.max(top, 0), behavior: 'smooth' });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }
})();
"""


class Showcase:
    """Drives a Playwright page at human speed, with a visible cursor.

    Every wait is multiplied by ``pace``, so ``CWA_DEMO_PACE=0.4`` renders a
    rehearsal cut in under a minute and ``1.0`` renders the real thing.
    """

    def __init__(self, page, pace: float = 1.0):
        self.page = page
        self.pace = pace

    # -- installation -------------------------------------------------------
    def install(self):
        """Arm the overlay for this page and every page it navigates to."""
        self.page.add_init_script(_OVERLAY_JS)
        return self

    def _ensure(self):
        """Install the overlay into the page as it stands right now.

        ``add_init_script`` only fires on the NEXT navigation, so the very first
        page — and any page loaded before install() ran — needs this.
        """
        self.page.evaluate(_OVERLAY_JS)

    # -- pacing -------------------------------------------------------------
    def beat(self, seconds: float = 0.6):
        self.page.wait_for_timeout(int(seconds * 1000 * self.pace))
        return self

    # -- narration ----------------------------------------------------------
    def caption(self, title: str, subtitle: str = "", hold: float = 1.6):
        self._ensure()
        self.page.evaluate(
            "([t, s]) => window.__demoCaption(t, s)", [title, subtitle])
        return self.beat(hold)

    def caption_off(self, hold: float = 0.3):
        self.page.evaluate("() => window.__demoCaptionHide && window.__demoCaptionHide()")
        return self.beat(hold)

    def chip(self, text: str):
        self._ensure()
        self.page.evaluate("(t) => window.__demoChip(t)", text)
        return self

    def spotlight(self, locator, hold: float = 0.9):
        """Ring and centre a question card."""
        self._ensure()
        locator.evaluate("(el) => window.__demoSpotlight(el)")
        return self.beat(hold)

    # -- pointer ------------------------------------------------------------
    def point_at(self, locator, hold: float = 0.45):
        """Glide the synthetic cursor onto ``locator`` (and the real one too)."""
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:                       # pragma: no cover — never in a pass
            raise AssertionError(
                f"nothing to point at: {locator} has no box, so the capture "
                f"would show a cursor jump to nowhere")
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        self._ensure()
        self.page.evaluate("([x, y]) => window.__demoCursor(x, y)", [x, y])
        self.page.mouse.move(x, y)            # so :hover states show up too
        return self.beat(hold)

    def click(self, locator, settle: float = 0.45):
        self.point_at(locator)
        self.page.evaluate("() => window.__demoTap()")
        locator.click()
        return self.beat(settle)

    def write(self, locator, text: str, delay: int = 110, settle: float = 0.4):
        """Click into a field and type it out one key at a time."""
        self.point_at(locator, hold=0.35)
        self.page.evaluate("() => window.__demoTap()")
        locator.click()
        locator.press_sequentially(str(text), delay=int(delay * self.pace))
        return self.beat(settle)

    def drag(self, locator, dx: float, dy: float, steps: int = 24,
             settle: float = 0.4):
        """Drag ``locator`` by (dx, dy) slowly enough to read on screen."""
        self.point_at(locator, hold=0.35)
        box = locator.bounding_box()
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        for i in range(1, steps + 1):
            nx, ny = x + dx * i / steps, y + dy * i / steps
            self.page.mouse.move(nx, ny)
            self.page.evaluate("([x, y]) => window.__demoCursor(x, y)", [nx, ny])
            self.page.wait_for_timeout(int(14 * self.pace))
        self.page.mouse.up()
        return self.beat(settle)
