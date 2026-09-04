---
name: testing-halyard-console
description: How to bring up and browser-test the Halyard operator console (FastAPI + Vite) locally, including DB reset gotchas, useful API endpoints for cross-checking the UI, and the frontend/backend field contracts that have broken pages before.
---

# Testing the Halyard operator console

## Bring-up

```bash
cd /path/to/halyard
make dev                 # API on 127.0.0.1:8000 (docs at /docs)
cd app && npm run dev    # console on port 5173, proxies /api
```

- Vite binds `[::1]`, so browse **`http://localhost:5173`**, not `127.0.0.1:5173`.
- No auth, no secrets are needed. **Devin Secrets Needed:** none.
- Kill stale listeners on 5173/5174 before starting, or Vite silently moves ports.
- Test at 1440x900 (screen-share dimensions); maximize with
  `wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`.

## Automated checks (run before any manual pass)

```bash
cd app && npm run lint     # tsc
cd app && npm test         # vitest, presenter unit tests in src/presentation/*.test.ts
cd app && npm run e2e      # playwright, e2e/console.spec.ts — needs the API on :8000
```

- The Playwright suite creates two LIVE requests and selects a route, so reset
  the database afterwards (see below) before recording a demo.
- Presentation logic lives in `app/src/presentation/` (labels, presenters); pages
  under `app/src/pages/` should only render what the presenters return.

## Database

- `make reset && make ingest` restores the pristine corpus (200 imported, 0 live).
- **Restart the API afterwards** — a running uvicorn keeps serving the pre-reset
  database and will report the old counts.
- Verify with:
  `curl -s '127.0.0.1:8000/api/queue?view=all' | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['total'],len([r for r in d['items'] if r['request_id'].startswith('LIVE')]))"`
  (the payload key is `items`, not `requests`).
- Route selection and intake mutate the DB; always reset at the end of a run.
- Queue items are keyed `request_id` (not `key`); `?q=` narrows rows, e.g.
  `/api/queue?view=all&q=LIVE` finds live rows past the 50-row page.
- A backgrounded `make dev` dies with the shell unless started as
  `(setsid nohup make dev > /tmp/api.log 2>&1 < /dev/null &)`.

## Useful endpoints for cross-checking the UI

- `GET /api/accounts/{id}/view` — the account page payload (`/api/accounts/{id}` is
  a different, thinner shape).
- `GET /api/requests/{request_key}/paths` — candidate paths, under a `paths` key.
- `GET /api/metrics/leadership` / `GET /api/queue?view=<view>` — metric and queue counts to
  compare against leadership drill-downs.

## Contracts that have broken the UI before

- `known_people[]` from `/api/accounts/{id}/view` is built by
  `halyard/services/search.py:person_summary()` and now includes `title` / `title_family` (additive, PR #8); other fields may still be missing.
  Frontend code that assumes `title` (e.g. `app/src/presentation/accountPresenter.ts`) throws and
  blanks the whole account page. When a new card reads a field, curl the endpoint
  first and confirm the field actually exists.
- Connector objects on the **paths** payload carry `stated_monthly_capacity` but
  **not** `recent_asks_30d` / `over_capacity` (those only exist on the leadership
  `connector_load` payload). UI that renders ask counts on route cards will show
  `0 asks` and a false "capacity available" verdict. Cross-check any connector-load
  copy on request detail against the leadership "Connector goodwill in use" table.
- Good way to force load states: pick a roster connector with a small stated
  capacity (e.g. Owen Trask, capacity 2) and select their route on N requests via
  "Investigate this route" until the leadership row flips
  Capacity available → At stated capacity → Above stated capacity.

## Things worth checking every visual pass

- Legacy/imported rows must read as neutral context (`· legacy backlog`,
  `? remediation date passed`), never red `! overdue`; leadership legacy backlog
  lives in its own dashed panel and is excluded from the live SLA cards.
- Every colour-coded badge should carry a glyph and words, not colour alone.
- Route/coverage copy must never imply a guaranteed introduction, relationship
  strength or intro probability.
- Check `document.documentElement.scrollWidth == clientWidth` at 1440x900 for
  horizontal overflow; the queue table has its own internal horizontal scroller,
  and its right-hand columns (next action) clip by design.
