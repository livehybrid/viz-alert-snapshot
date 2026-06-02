# Architecture — viz-alert-snapshot (Rich Visual Alerts for Splunk)

> Status of this document: living. Updated as phases land. See `ROADMAP.md` for
> phased steps + status.

## 1. What this is

A Splunk Enterprise (on-prem) app that turns an alert's results into a **real
Splunk visualization image** and delivers it to one or more destinations
(email first; Slack / Teams / Telegram later). It includes a **configuration UI**
so users can point an existing saved search / alert / report at a visualization,
**preview exactly what will be sent**, and wire it up — without hand-editing conf.

The differentiator is the **preview-fidelity loop**: the preview is produced by
the *same server render* that fires on the alert, so what you see is what gets
sent.

## 2. Decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Render engine | **Reuse Splunk's bundled headless Chromium** (the `splunk-visual-exporter` app) | No bundled browser to ship/maintain; genuine Splunk pixels |
| Bundle our own Chromium? | **No** | Explicit: avoid shipping a 300 MB binary |
| Viz scope | **Native `splunk.*` visualizations only** | The bundled exporter only renders core viz; custom viz is out of scope |
| Custom (sideloaded) viz | **Parked** | Bundled exporter can't host them; CDP route exists but is out of scope (see ROADMAP P4, parked) |
| Distribution | **On-prem / private** (Splunk Enterprise) | Server-side viz rendering is inherently on-prem; no public Cloud API |
| UI stack | **Splunk React UI only** (`@splunk/react-ui`, `@splunk/react-page`, `@splunk/splunk-utils`) | Per `splunk-react-app` skill; native look + a11y; no other component libs |
| App build base | **UCC (`ucc-gen`) + Webpack single-package** | Per `splunk-react-app` skill; CIMPlicity is the in-repo reference |
| Config storage | **KV store** collection, keyed by saved search | Multi-value, queryable, per-user/app scoping |
| Secrets | **Splunk `storage/passwords`** | Encrypted at rest, app-scoped |

## 3. Render engine

```
results (gzip CSV / search job)
  → results_to_dstest()      # → ds.test {fields, columns}
  → build_definition()       # one-panel Dashboard Studio definition,
  |                          #   layout.options.width/height = the PNG size
  → render → PNG bytes
```

Two render backends behind one interface (`bin/lib/snapshot.py`):

1. **In-process `ChromiumEngine`** (current, proven). Imports
   `export_utils.chromium.engine.ChromiumEngine` from the bundled
   `splunk-visual-exporter` app and calls `get_screenshot(definition, theme,
   …, file_format='png')`. Fast, no auth round-trip; `ds.test` embeds the data.
   - ⚠️ **AppInspect caveat:** importing another app's private module fails
     Splunk **Cloud** vetting and can break across Splunk upgrades. Acceptable
     for **private / on-prem** distribution (our target). Isolated in
     `snapshot.py` so it can be swapped.

2. **`POST /services/pdfgen/render`** (planned, AppInspect-cleaner). Supported
   REST endpoint; for Studio PNG it renders a *saved* dashboard, so this path
   creates a transient one-panel Studio dashboard (ds.test data) in the app
   namespace, renders `type=png`, then deletes it. Migrate here if/when a
   Splunkbase-vetted listing is wanted. Tracked in ROADMAP.

**Key constraints learned (do not regress):**
- `screenshot_delay` must be **0** for `ds.test` — data is synchronous, any
  delay blocks until the Chromium timeout.
- Set the API global / readiness **after** the page settles (native path
  handles this internally).
- Native viz only — a custom viz type renders the "Unsupported visualization"
  placeholder.

## 4. Components

```
┌──────────────────────────────────────────────────────────────────┐
│  Config UI  (React, Splunk UI)   /app/<appId>/home                 │
│   • browse/edit saved searches, create new                         │
│   • choose viz type + options on the search's fields               │
│   • LIVE PREVIEW  ──calls──▶ Preview REST ──uses──▶ Render engine   │
│   • choose destinations                                            │
│   • Save ──▶ KV store  +  enable alert action on the saved search  │
└───────────────┬───────────────────────────────────────────────────┘
                │ (persistent REST, session-scoped)
┌───────────────▼───────────────┐   ┌──────────────────────────────┐
│  REST handlers (splunkd)       │   │  KV store: alert_viz_configs │
│   • /preview  (config→PNG)     │   │   one doc per saved search   │
│   • /searches (list/save)      │   └──────────────────────────────┘
│   • /config   (CRUD KV)        │
└───────────────┬───────────────┘
                │
┌───────────────▼───────────────────────────────────────────────────┐
│  Alert action  render_and_notify  (--execute, JSON payload)        │
│   results → render engine → PNG → senders[] (fan-out)              │
└───────────────┬───────────────────────────────────────────────────┘
                │
        ┌───────┴───────┬──────────┬───────────┐
     email           telegram     slack       teams      (P3)
   (Splunk [email])  sendPhoto   files.upload  card
```

### 4.1 Alert action (`render_and_notify`)
- Invoked by Splunk as `--execute` with a JSON payload on stdin
  (`payload_format = json`), results at `payload['results_file']` (gzip CSV).
- Reads config: from alert-action params (P1) → from KV store keyed by
  `search_name` (P2+).
- Renders one PNG, then fans out to each configured destination.
- P1 ships the `render_viz_email` action (email only); P3 generalizes to
  `render_and_notify` with a destinations list.

### 4.2 Config UI (P2)
- UCC + Webpack app; template-based `home` view (NOT Simple XML) so React mounts
  after the DOM (avoids the blank-view bug).
- `@splunk/react-ui` + `@splunk/react-page` for all chrome; `@splunk/splunk-utils`
  (`createRESTURL`, `getDefaultFetchInit`) for API.
- Search picker reads `/servicesNS/-/<appId>/saved/searches`.
- Viz config: type (line/area/column/bar/pie/single/table…) + options form.
- **Preview**: posts the config to `/preview`; shows the returned PNG. Data
  source for preview: last results of the search if fresh → on-demand run →
  `ds.test` sample (so a never-run search still previews).
- Save: upsert KV doc (batch_save, raw JSON) + set
  `action.render_and_notify = 1` and params on the saved search via REST.

### 4.3 Preview REST handler (P2)
- `PersistentServerConnectionApplication`, one module (`bin/preview.py`).
- Input: `{ search_name | spl, viz_type, options, width, height, theme,
  data_strategy }`. Output: `{ png_b64 }` or `{ error }`.
- Reuses `snapshot.render_results_to_png` — identical to fire-time render.

### 4.4 Senders (P3)
- One module per channel under `bin/lib/senders/`. Common interface
  `send(settings, recipients, subject, body, png_bytes)`.
- email → reuse Splunk `[email]` (alert_actions.conf) — already built.
- telegram → Bot API `sendPhoto` (we have Telegram infra in this repo).
- slack → `files.upload` (token) or webhook + hosted image.
- teams → MessageCard / Adaptive Card with image.
- Credentials via `storage/passwords` (app-scoped, encrypted).

## 5. Target directory layout (UCC single-package, per skill)

```
viz-alert-snapshot/
├── globalConfig.json            # UCC config (package root, not in ucc-app/)
├── package.json / lerna.json    # JS workspace (mirror CIMPlicity)
├── ucc-app/                     # UCC source
│   ├── app.manifest
│   ├── default/
│   │   ├── app.conf             # default_view = home
│   │   ├── alert_actions.conf   # render_and_notify
│   │   ├── restmap.conf         # [script:viz_alert_*] preview/searches/config
│   │   ├── web.conf             # expose the script endpoints
│   │   ├── collections.conf     # alert_viz_configs
│   │   ├── transforms.conf      # collection field mapping
│   │   └── data/ui/{views,nav}/ # home.xml (html view), default.xml (nav)
│   ├── appserver/templates/home.html
│   └── bin/                     # alert action + REST handlers + lib/
├── src/main/webapp/pages/home/  # React entry (Webpack)
└── dist/                        # packaged <appId>-<version>.tar.gz
```

> P1 currently uses the simpler `default/ + bin/` layout (proven, shippable on
> its own). Migration to the UCC layout happens at the start of P2 so the React
> UI, REST handlers, and KV store share one canonical build.

## 6. Build & packaging (per `splunk-react-app` skill)

1. `ucc-gen build --source ucc-app -o build/`
2. Patch `build/<appId>/default/app.conf`: `is_visible = true`
3. Copy `build/<appId>/*` → `src/main/resources/splunk/`
4. Webpack: entries from `src/main/webapp/pages/` → `stage/appserver/static/pages/[name].js`; CopyWebpackPlugin app tree → `stage/`
5. `ucc-gen package --path <appId>/ -o dist/` → `dist/<appId>-<version>.tar.gz`

## 7. AppInspect / Cloud notes (for if we ever vet)

- Private/on-prem (our target) is fine with the in-process render import.
- For Cloud vetting: switch render to `/services/pdfgen/render`; no dotfiles in
  the tarball; `metadata/default.meta` write roles `sc_admin`/`power` (not
  `admin`); `[install] is_configured = false`; `chmod 755 dirs / 644 files`;
  add `[triggers]` reloads for any custom `.conf`.

## 8. Live-system safety

The target Splunk is **production**. Build/repo/dry-run-render work is safe.
**Installing the app, restarting splunkd, firing real alerts, and sending real
messages are gated on explicit user go-ahead** (and external sends require
confirmation per repo guardrails).
