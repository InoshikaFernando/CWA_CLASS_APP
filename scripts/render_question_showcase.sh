#!/usr/bin/env bash
#
# render_question_showcase.sh — record the interactive maths question types.
#
# Drives a real student through one homework carrying every question type this
# app has that a worksheet PDF cannot do (long division with its working ladder,
# the prime-factor ladder, long multiplication, a draggable protractor, a
# Cartesian plane, a symmetry grid, a number line, a table of values, a sketched
# parabola), records the browser, and writes the result to artifacts/demo/.
#
#   ./scripts/render_question_showcase.sh                 # the full cut
#   ./scripts/render_question_showcase.sh --pace 0.4      # a fast rehearsal
#   ./scripts/render_question_showcase.sh --out /tmp/ad   # somewhere else
#
# It is the Playwright test ui_tests/maths/test_question_showcase.py underneath,
# so the run FAILS if any answer it types is marked wrong — a capture of a
# widget that has stopped grading is worse than no capture.
#
# Output:
#   artifacts/demo/question-types-showcase.webm   always (Playwright records VP8)
#   artifacts/demo/question-types-showcase.mp4    when an H.264 ffmpeg is found
#
# The ffmpeg Playwright bundles can only write WebM, so the MP4 needs a real
# one: whatever `ffmpeg` is on PATH, else the static binary that ships with the
# `imageio-ffmpeg` package (`pip install imageio-ffmpeg`). Without either you
# still get the WebM — most editors and every modern browser take it — and this
# script says so rather than failing at the last step.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO_ROOT/artifacts/demo"
PACE="1"

while [ $# -gt 0 ]; do
  case "$1" in
    --pace) PACE="$2"; shift 2 ;;
    --out)  OUT_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT/cwa_classroom"

echo "==> Recording (pace ${PACE}) — this drives the browser in real time"
CWA_DEMO_VIDEO=1 \
CWA_DEMO_PACE="$PACE" \
CWA_DEMO_OUT="$OUT_DIR" \
DB_ENGINE=sqlite \
  python -m pytest ui_tests/maths/test_question_showcase.py -n 0 -q

WEBM="$OUT_DIR/question-types-showcase.webm"
MP4="$OUT_DIR/question-types-showcase.mp4"

# Find an ffmpeg that can write H.264. Playwright's bundled build cannot — it is
# compiled with libvpx and the WebM muxer only — so it is deliberately not tried.
FFMPEG="$(command -v ffmpeg || true)"
if [ -z "$FFMPEG" ]; then
  FFMPEG="$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
fi

if [ -z "$FFMPEG" ]; then
  echo
  echo "==> No H.264 ffmpeg found, so no MP4 was written."
  echo "    Install one (apt install ffmpeg, or pip install imageio-ffmpeg) and"
  echo "    re-run, or use the WebM directly: $WEBM"
  exit 0
fi

echo "==> Transcoding to MP4 with $FFMPEG"
# yuv420p + even dimensions: QuickTime, PowerPoint and most social uploaders
# reject anything else. faststart puts the index first so it streams.
"$FFMPEG" -y -loglevel error -i "$WEBM" \
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p" \
  -c:v libx264 -preset slow -crf 20 -profile:v high -level 4.0 \
  -movflags +faststart -r 30 -an "$MP4"

echo
echo "==> Done"
ls -lh "$WEBM" "$MP4"
