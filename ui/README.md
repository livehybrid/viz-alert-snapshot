# Visual Alerts — configuration UI (React)

Source for the app's `home` view. Built with `@splunk/react-ui` +
`@splunk/splunk-utils`, mirroring the `apps/cimplicity-ai-app` reference and the
`splunk-react-app` skill.

> **Status: scaffolded, not yet built/validated.** The React source and build
> config are in place; they need an `npm install` against the `@splunk` registry
> and a dev Splunk to iterate. Do **not** build/install against the production
> Splunk — stand up a Docker dev Splunk first.

## Build

```bash
cd ui
npm install                 # pin @splunk/* to versions your registry provides
npm run build               # → ../appserver/static/pages/home.js
```

The template `appserver/templates/home.html` loads
`/static/app/viz-alert-snapshot/pages/home.js` after the DOM, so React mounts
reliably (no blank-view race).

## What it does

- Lists saved searches (stock `saved/searches` REST).
- Pick a search → loads any existing config (`GET /viz_alert/config/<name>`).
- Choose viz type, size, theme, preview-data strategy, and viz options JSON.
- **Preview** → `POST /viz_alert/preview` renders the *exact* PNG the alert will
  send (server-side, bundled Chromium) and shows it.
- **Save** → `POST /viz_alert/config` upserts the KV doc.

## Next steps (see ../docs/ROADMAP.md, Phase 2)

- Wire "Save" to also enable `action.render_and_notify` on the saved search
  (stock `saved/searches/<name>` POST).
- Replace the options JSON textarea with a per-viz options form.
- Create-new-search flow.
- Destinations editor (Phase 3).
- Consider full UCC single-package migration for one canonical
  `ucc-gen build`/`package` pipeline (currently classic layout + this UI build).
