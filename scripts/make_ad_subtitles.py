"""Turn the ad script into an SRT subtitle track for the capture.

    python scripts/make_ad_subtitles.py
    python scripts/make_ad_subtitles.py --out /tmp/ad.srt

Reads the "Full script" table in ``docs/QUESTION_TYPES_AD_SCRIPT.md`` — the one
source of the lines and their cue times — and writes an SRT beside the video.

Why this exists, rather than a hand-typed SRT: the cue times come from the
render, and every re-render moves them. A subtitle file typed once goes stale
silently, which is the worst way for a caption to be wrong. Re-run this after a
re-render and the lines follow.

Two uses, and the second is the bigger one:

* a cue track for the recording session — the reader sees the line and the
  moment it has to land in;
* captions for the finished ad. Most social video is watched with the sound
  off, so the captions carry the message whether or not the voice-over is ever
  recorded.

Each line ends before the next one starts, and no earlier than the time it
takes to say it at a child's pace. If a line cannot fit before the next cue,
the script says so rather than overlapping them, because two captions on screen
at once is the one failure a viewer definitely notices.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_MD = REPO_ROOT / 'docs' / 'QUESTION_TYPES_AD_SCRIPT.md'
DEFAULT_OUT = REPO_ROOT / 'artifacts' / 'demo' / 'question-types-showcase.srt'

#: Words a child reads per second, unhurried. Used only to decide how long a
#: caption stays up; the cue times themselves come from the render.
WORDS_PER_SECOND = 2.5
#: Held after the words end, so a caption does not vanish on the last syllable.
TAIL = 0.6
#: Clear of the next caption, so two are never up together.
GAP = 0.3
MIN_DURATION = 1.2

ROW = re.compile(r'^\|\s*(\d+):(\d{2})\s*\|(.*)$')


def parse_rows(markdown: str):
    """(start_seconds, voice, line) for every timed row of the script table."""
    rows = []
    in_table = False
    for raw in markdown.splitlines():
        if raw.startswith('## Full script'):
            in_table = True
            continue
        if in_table and raw.startswith('##'):
            break
        if not in_table:
            continue
        match = ROW.match(raw.strip())
        if not match:
            continue
        minutes, seconds, rest = match.groups()
        cells = [c.strip() for c in rest.split('|')]
        # Columns after the time: gap, on-screen, voice, line.
        if len(cells) < 4:
            continue
        voice, line = cells[2], cells[3].strip('"“”')
        if not line:
            continue
        rows.append((int(minutes) * 60 + int(seconds), voice, line))
    return rows


def stamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    milliseconds = int(round((seconds - whole) * 1000))
    return (f'{whole // 3600:02d}:{whole % 3600 // 60:02d}:'
            f'{whole % 60:02d},{milliseconds:03d}')


def build(rows, video_end: float):
    blocks, warnings = [], []
    for index, (start, voice, line) in enumerate(rows):
        spoken = len(line.split()) / WORDS_PER_SECOND + TAIL
        next_start = rows[index + 1][0] if index + 1 < len(rows) else video_end
        room = next_start - GAP - start
        if spoken > room:
            warnings.append(
                f'  {stamp(start)} {voice}: needs ~{spoken:.1f}s, has '
                f'{room:.1f}s — "{line}"')
        end = start + max(min(spoken, room), MIN_DURATION)
        blocks.append(
            f'{index + 1}\n{stamp(start)} --> {stamp(end)}\n{line}\n')
    return '\n'.join(blocks), warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--script', type=Path, default=SCRIPT_MD)
    parser.add_argument('--end', type=float, default=188.0,
                        help='Video length in seconds (default: the 3:08 cut).')
    args = parser.parse_args()

    rows = parse_rows(args.script.read_text(encoding='utf-8'))
    if not rows:
        raise SystemExit(
            f'No timed lines found in {args.script}. The "Full script" table is '
            f'what this reads; if its shape changed, this needs to change too.')

    srt, warnings = build(rows, args.end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(srt, encoding='utf-8')
    print(f'{len(rows)} captions written to {args.out}')
    if warnings:
        print('\nLines that will be rushed at 2.5 words a second — shorten them '
              'or move the cue:')
        print('\n'.join(warnings))


if __name__ == '__main__':
    main()
