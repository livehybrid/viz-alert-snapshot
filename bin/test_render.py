#!/usr/bin/env python
"""
test_render.py — dry-run the renderer without an alert or email.

Renders a single viz from sample (or piped) results to a PNG file, using the
bundled Chromium. Run under Splunk's python so the exporter libs resolve:

  $SPLUNK_HOME/bin/splunk cmd python3 \
      $SPLUNK_HOME/etc/apps/viz-alert-snapshot/bin/test_render.py \
      --viz splunk.line --out /tmp/snap.png

  # or pipe your own results (CSV with header) on stdin:
  ... | head | $SPLUNK_HOME/bin/splunk cmd python3 .../test_render.py --stdin
"""
import os
import sys
import csv
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import snapshot  # noqa: E402

SAMPLE = [
    {'_time': '2026-06-01T%02d:00:00.000Z' % h, 'gCO2': v}
    for h, v in enumerate([120, 138, 165, 150, 175, 210, 245, 230, 260, 248, 275, 290])
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--viz', default='splunk.line')
    ap.add_argument('--out', default='/tmp/viz_snapshot.png')
    ap.add_argument('--width', type=int, default=800)
    ap.add_argument('--height', type=int, default=450)
    ap.add_argument('--title', default='Snapshot Test')
    ap.add_argument('--theme', default='dark')
    ap.add_argument('--options', default='{}')
    ap.add_argument('--delay', type=int, default=0)
    ap.add_argument('--stdin', action='store_true', help='read CSV results from stdin')
    args = ap.parse_args()

    rows = list(csv.DictReader(sys.stdin)) if args.stdin else SAMPLE
    if not snapshot.exporter_available():
        sys.exit('splunk-visual-exporter not found — run under a Splunk with Dashboard Studio export.')

    png, definition, errors = snapshot.render_results_to_png(
        args.viz, rows, width=args.width, height=args.height, title=args.title,
        options=json.loads(args.options), theme=args.theme, screenshot_delay=args.delay)
    with open(args.out, 'wb') as f:
        f.write(png)
    print('Wrote %s (%d bytes) — %d rows, viz=%s%s'
          % (args.out, len(png), len(rows), args.viz,
             (' engine_notes=%s' % errors[:2]) if errors else ''))


if __name__ == '__main__':
    main()
