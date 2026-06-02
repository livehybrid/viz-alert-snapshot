# viz-alert-snapshot — Rich Visual Alerts for Splunk

Turn a Splunk alert's results into a **real Splunk visualization image** and
deliver it where your team actually looks — starting with **email**, and (on the
roadmap) **Telegram, Slack and Teams** — rendered server-side with Splunk's own
**bundled headless Chromium**. No external browser, no bundled binary.

> **Vision:** a Splunk-native config UI where you point any saved search / alert
> at a visualization, **preview the exact image that will be sent**, pick your
> destinations, and go. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
> [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Status

- ✅ **Phase 1 (foundation):** custom alert action that renders results as a
  single native Splunk viz PNG and emails it. Render path proven across
  line/area/column/table/pie.
- 🟡 Email path written; live end-to-end (SMTP + fired alert) not yet validated.
- ⬜ **Phase 2:** React configuration UI with live server-render preview.
- ⬜ **Phase 3:** multi-channel destinations (Telegram/Slack/Teams).

## Decisions (why it's built this way)

- **On-prem / Splunk Enterprise.** Server-side viz rendering needs a server-side
  browser; there is no public Cloud API for it.
- **Reuse Splunk's bundled Chromium** (`splunk-visual-exporter`). We do **not**
  bundle our own browser.
- **Native `splunk.*` visualizations only.** The bundled exporter renders core
  viz; custom/sideloaded viz is out of scope (parked — see ROADMAP P4).

## How it works

```
Alert fires
  └─ render_viz_email.py (--execute, JSON payload on stdin)
       ├─ read results (results_file, gzip CSV)
       ├─ results  ──►  ds.test { fields, columns }        (lib/snapshot.py)
       ├─ wrap in a one-panel Dashboard Studio definition
       │     layout.options.width/height = the PNG size = just the viz
       ├─ ChromiumEngine.get_screenshot(definition, file_format='png')
       │     (the bundled Chromium in the splunk-visual-exporter app)
       └─ email the PNG inline + attached            (lib/mailer.py)
```

Data is embedded as `ds.test`, so the render needs no live search and no auth
round-trip — and you get genuine Splunk viz pixels (same fonts, axes, theme as
Dashboard Studio's own PDF/PNG export).

## Requirements

- **Splunk Enterprise on-prem** with the `splunk-visual-exporter` app present
  (ships with Dashboard Studio export). This app does **not** bundle a browser.
- Splunk email settings configured (Settings → Server settings → Email) — reused
  for delivery.
- Not for Splunk Cloud (can't import the internal exporter from an app there).

## Use (Phase 1)

1. Install the app, restart Splunk.
2. On any alert: **Add Actions → Render Viz & Email PNG**.
3. Pick the viz type (line/area/column/bar/pie/single value/table/markdown),
   recipients, size, theme, and optional viz `options` JSON.

The alerting search's result fields become the viz's data — e.g. a
`… | timechart …` with **Line** gives a time-series PNG; `… | stats … by x`
with **Bar/Column** gives a categorical chart.

## Dry-run without an alert

```bash
$SPLUNK_HOME/bin/splunk cmd python3 \
  $SPLUNK_HOME/etc/apps/viz-alert-snapshot/bin/test_render.py \
  --viz splunk.line --out /tmp/snap.png
# or feed your own CSV results (with header) on stdin:
#   <csv> | $SPLUNK_HOME/bin/splunk cmd python3 .../test_render.py --stdin --viz splunk.column
```

## Notes & limitations

- **Internal engine.** `splunk-visual-exporter` / `ChromiumEngine` is a
  Splunk-bundled internal component; its API can change between Splunk versions.
  `lib/snapshot.py` isolates that dependency. (A more portable path via
  `POST /services/pdfgen/render` is on the roadmap for AppInspect-clean shipping.)
- **`screenshot_delay = 0`.** `ds.test` data is synchronous; any delay makes the
  headless render block until timeout. Leave at 0.
- **SMTP auth.** Delivery reuses Splunk's `[email]` settings. If the stored
  password is Splunk-encrypted it can't be reused here, so the action sends
  without auth (works for unauthenticated internal relays). Logged when it happens.
- **Native viz only.** Sideloaded custom viz render as the "Unsupported
  visualization" placeholder via this path.

## Developer notes

### KV store / REST — `splunk.rest`, **not** the `splunklib` SDK

We talk to the KV store (and splunkd generally) with Splunk's built-in
**`splunk.rest.simpleRequest`** — *not* the Splunk SDK for Python (`splunklib`).
This is deliberate:

- **`splunklib` isn't bundled with Splunk Enterprise.** Using it means *vendoring*
  the SDK (~1–2 MB) into `bin/lib/` and managing its connection/auth/TLS ourselves.
  (`preview.py` originally tried `splunklib.client` and hit `ModuleNotFoundError`
  — the SDK simply isn't installed.)
- **`splunk.rest` is always present in-splunkd** (REST handlers, alert actions),
  so there's no vendored dependency and no extra AppInspect surface.
- **It verifies TLS via Splunk's configured CA.** `simpleRequest` builds its SSL
  context from `server.conf` (`sslRootCAPath`), so internal calls are verified
  without disabling verification or hardcoding `etc/auth/cacert.pem`.
- **KV `batch_save` needs a raw JSON body**, which `simpleRequest(..., jsonargs=…)`
  sends with the correct `Content-Type` (the `splunk-react-app` pattern recommends
  this, not the SDK).

If the SDK's ergonomics are ever wanted (e.g. consistency with apps that vendor
`splunklib`), vendor it under `bin/lib/` and swap out `lib/kvstore.py` — the rest
of the app only calls `kvstore.{query,get,upsert,delete}()`.

## Layout (Phase 1)

```
viz-alert-snapshot/
├── docs/{ARCHITECTURE.md, ROADMAP.md}
├── app.manifest
├── default/
│   ├── app.conf
│   ├── alert_actions.conf
│   └── data/ui/alerts/render_viz_email.html   # alert-action config form
├── bin/
│   ├── render_viz_email.py                     # the alert action
│   ├── test_render.py                          # CLI dry-run harness
│   └── lib/
│       ├── snapshot.py                         # results→ds.test→definition→PNG
│       └── mailer.py                           # Splunk email settings + send
├── metadata/default.meta
└── README.md
```

> Phase 2 migrates this to the UCC + Webpack single-package layout (per the
> `splunk-react-app` pattern) so the React UI, REST handlers, and KV store share
> one canonical build. See `docs/ARCHITECTURE.md` §5.
