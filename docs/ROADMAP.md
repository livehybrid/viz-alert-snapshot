# Roadmap & Status — viz-alert-snapshot

Phased plan with elaborated steps and live status. Legend: ✅ done · 🟡 in
progress · ⬜ not started · 🅿️ parked.

---

## Phase 1 — Render + email alert action  (🟡 hardening)

Goal: an alert action that renders the alerting results as a single native
Splunk viz PNG and emails it, via the bundled Chromium. **Foundation, proven.**

| # | Step | Status |
|---|------|--------|
| 1.1 | `snapshot.py`: results → `ds.test` → one-panel Studio definition → PNG via bundled `ChromiumEngine` | ✅ proven (line/area/column/table/pie) |
| 1.2 | `mailer.py`: reuse Splunk `[email]` settings, send inline+attached PNG | ✅ written, ⬜ not live-tested |
| 1.3 | `render_viz_email.py`: alert action `--execute`, gzip-CSV results, render, email | ✅ written |
| 1.4 | `alert_actions.conf` + alert config HTML form (viz type, recipients, size, theme) | ✅ |
| 1.5 | Harden: field selection, empty/large results, per-result vs all-results, structured errors | 🟡 |
| 1.6 | README for native-viz-only / on-prem decision | 🟡 |
| 1.7 | **Live validation**: install on a test Splunk, fire an alert, confirm email lands | ⬜ gated on user (prod box) |

**Known constraints baked in:** `screenshot_delay = 0` for `ds.test`; native
viz only; SMTP auth password caveat (encrypted Splunk secret can't be reused →
sends unauthenticated, logged).

---

## Phase 2 — Configuration UI  (⬜ next)

Goal: a Splunk-native React UI to point an existing (or new) saved search at a
visualization, **preview the exact image that will be sent**, and wire the alert
action — no hand-editing conf. Done = "configuration panels working, can edit
existing searches and create new ones with the alert action configured."

| # | Step | Status |
|---|------|--------|
| 2.1 | Migrate app to UCC single-package layout (mirror CIMPlicity) | 🟡 scaffolded, needs build |
| 2.2 | KV store: `collections.conf` + `transforms.conf` for `alert_viz_configs` | ✅ |
| 2.3 | Preview REST handler `bin/preview.py` (config → PNG b64), `restmap.conf` + `web.conf` | ✅ |
| 2.4 | ~~Searches REST handler~~ — UI uses stock `saved/searches` REST directly (no custom handler) | ✅ n/a |
| 2.5 | Config REST handler (CRUD KV via batch_save raw-JSON helper) | ✅ |
| 2.6 | Template-based `home` view + `home.html` template + nav + app.conf | ✅ |
| 2.7 | React app: search picker (`@splunk/react-ui`) | ✅ scaffold |
| 2.8 | React: viz type + options (JSON) + size/theme/data-strategy | ✅ scaffold (options form: later) |
| 2.9 | React: **live preview** panel (calls `/preview`, shows PNG, loading/error/empty) | ✅ scaffold |
| 2.10 | React: create-new-search flow | ⬜ |
| 2.11 | Save: upsert KV doc ✅ ; also enable `action.render_and_notify` + params on the saved search | 🟡 KV save done; action-enable: later |
| 2.12 | Webpack build wired (`ui/` → `appserver/static/pages/home.js`) | ✅ config in place, ⬜ not yet built |

> **P2 frontend is scaffolded, not built.** React source + build config mirror
> the CIMPlicity reference. Needs `npm install` (@splunk registry) + a **dev
> Splunk** to build and iterate — must not be built/installed against the
> production box. See `ui/README.md`.

**Preview data strategy** (2.9): fresh last-results → on-demand run → `ds.test`
sample, so a never-run search still previews. Configurable per config.

| 2.13 | **Post-search (post-process) pipeline** — optional SPL piped onto the alert results before rendering (raw error events → `\| timechart count`). Fire-time via `\| loadjob <sid> \| <post>`; preview shows raw table → processed table → viz | ✅ (fire-time loadjob untested live) |

---

## Phase 3 — Multi-channel destinations  (⬜ after P2)

Goal: send the rich alert image to email + Telegram + Slack + Teams. We own
small senders rather than piggybacking other modular actions.

| # | Step | Status |
|---|------|--------|
| 3.1 | `render_and_notify` alert action: render once, read KV config, fan out to destinations[] | ✅ (fire-time untested live) |
| 3.2 | Sender interface + `bin/lib/senders/{email,telegram,slack,webhook}.py` + registry/dispatch | ✅ |
| 3.3 | Secrets via `storage/passwords` (`secrets.py`) + `settings_api` endpoint | ✅ |
| 3.4 | UI: destinations editor + Channels credential modal | ✅ |
| 3.5 | Telegram `sendPhoto`; Slack external-upload; generic webhook (json/multipart); email | ✅ code (needs creds/relay to test) |
| 3.6 | Per-destination test-send button | ⬜ |
| 3.7 | Auto-enable `render_and_notify` on the saved search from Save (opt-in toggle) | ⬜ (manual for now: add the action to the alert) |
| 3.8 | MS Teams (Adaptive Card / hosted image) | ⬜ |

---

## Phase 4 — Custom (sideloaded) viz  (🅿️ parked)

Out of scope by decision (native viz only). If revisited: drive the bundled
Chromium binary over CDP with an app-local host page (the bundled exporter's
`--custom-headless-command` driver won't host an external page — proven). Notes
preserved in git history (`custom_host.py` / `custom_render.py` prototypes).

---

## Cross-cutting

- **CI/packaging**: GitHub Actions (build → version → `ucc-gen package` →
  optional AppInspect → publish), mirroring CIMPlicity's workflow. ⬜
- **Docker dev stack** for local Splunk testing (avoid touching prod). ⬜
- **AppInspect**: see `ARCHITECTURE.md` §7; only if a vetted listing is wanted.
