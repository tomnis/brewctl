# 1. Brew history and recipes

## Problem

Brew state lives entirely in the module-global `cur_brew: Brew | None` in
`backend/src/brewctl/api/server.py`. Consequences:

- A restart of the api container loses all knowledge of the brew that just ran.
- `GET /api/brew/{brew_id}/quality` recomputes metrics from InfluxDB, so it works only as long as
  the retention policy keeps the raw scale points. There is no durable record of the score.
- There is no way to answer "what did I do last time", "which strategy scored best", or "run that
  again" — the two brews being compared no longer exist anywhere.
- `StartBrew.tsx` makes the user re-enter target weight, vessel weight, target flow rate, strategy,
  and every strategy parameter on each brew.

InfluxDB is the right store for the high-rate weight series and the wrong store for a handful of
brew records with parameters and notes. Those want a relational table.

## Design

### Storage

SQLite via SQLAlchemy (or plain `sqlite3` — the schema is small enough that an ORM is optional),
file path from a new `BREWCTL_DB_PATH` env var, defaulting to `./brewctl.db`. Mount it as a Docker
volume in `docker-compose.yml` so it survives container replacement.

Two tables.

`brews`:

| column | type | notes |
|---|---|---|
| `id` | text pk | the existing UUID from `start_brew` |
| `state` | text | terminal `BrewState` value |
| `strategy` | text | `BrewStrategyType` value |
| `strategy_params` | json text | as submitted |
| `target_flow_rate` | real | |
| `target_weight` | real | |
| `vessel_weight` | real | |
| `epsilon` | real | |
| `scale_interval` | real | |
| `valve_interval` | real | |
| `time_started` | timestamp | |
| `time_completed` | timestamp null | |
| `final_weight` | real null | |
| `error_message` | text null | |
| `quality_json` | json text null | serialized `BrewQualityMetrics` |
| `recipe_id` | text null fk | recipe this brew was started from, if any |
| `notes` | text null | user-entered, editable after the fact |
| `bean` | text null | free text: bean, roaster, roast date, grind |

`recipes`:

| column | type | notes |
|---|---|---|
| `id` | text pk | uuid |
| `name` | text unique | |
| `params_json` | json text | a serialized `StartBrewRequest` |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |
| `archived` | bool | soft delete, so old brews keep a valid `recipe_id` |

Write path: insert the row at brew start (state `BREWING`), update it on completion, error, or
kill. The update is a natural fit at the three places that already mutate `cur_brew.status` —
the `STOP` branch of `brew_step_task`, the error handler, and `kill_brew`.

Quality metrics get computed once at completion (`brew_quality.py` already does the maths) and
stored in `quality_json`, rather than being recomputed from Influx on every request. Keep the
existing on-the-fly path as a fallback for brews that predate the table.

### Recovery on restart

At api startup, look for a row in state `BREWING` or `PAUSED`. Do not attempt to resume — the
valve position and the physical state of the vessel are unknown. Mark it `ERROR` with
`error_message = "interrupted by api restart"` and log it. This keeps the history honest and
prevents a zombie row from blocking the "brew already in progress" check.

### API

```
GET    /api/brews?limit=&offset=&strategy=&since=   -> [BrewRecord]
GET    /api/brews/{id}                              -> BrewRecord (incl. quality)
PATCH  /api/brews/{id}                              -> edit notes / bean only
DELETE /api/brews/{id}
GET    /api/brews/{id}/series                       -> weight+flow trace from Influx, for charting

GET    /api/recipes                                 -> [Recipe]
POST   /api/recipes                                 -> Recipe
PUT    /api/recipes/{id}
DELETE /api/recipes/{id}                            -> sets archived
POST   /api/recipes/{id}/brew                       -> starts a brew from the recipe
```

`POST /api/recipes/{id}/brew` is a thin wrapper: load `params_json` into a `StartBrewRequest`,
call the same code path as `start_brew`, and set `recipe_id` on the new row. Keep it as one
endpoint rather than making the frontend fetch-then-post, so "brew again" is atomic.

Also add `POST /api/brews/{id}/save-as-recipe` — the common flow is "that one was good, save it",
not "design a recipe up front".

### Frontend

- New `BrewHistory` route: table of past brews (date, strategy, target, achieved, score), sortable,
  click through to detail.
- Detail view reuses `TrendChart.tsx` fed from `/api/brews/{id}/series` instead of live SSE. The
  chart component should be refactored to take data as a prop rather than subscribing itself; the
  live view then passes SSE data in.
- Compare mode: select two brews, overlay both traces plus the target flow line on one chart.
- `StartBrew.tsx` gains a recipe dropdown at the top: selecting one fills every field, and the
  fields stay editable (an edited recipe brew still records `recipe_id`, with the actual params
  stored on the brew row — so the record is accurate even when the recipe drifted).

## Files touched

- new `backend/src/brewctl/api/db.py` — engine, schema, migrations-on-startup
- new `backend/src/brewctl/api/repository.py` — brew and recipe CRUD
- new `backend/src/brewctl/api/routes/brews.py`, `routes/recipes.py` — or append to `server.py`,
  though at 976 lines it is well past the point where splitting out routers is overdue
- `backend/src/brewctl/api/server.py` — insert/update calls at brew start, stop, kill, error;
  startup recovery
- `backend/src/brewctl/api/config.py` — `BREWCTL_DB_PATH`
- `backend/requirements/api.txt` — SQLAlchemy, if used
- `docker-compose.yml` — volume for the db file
- `frontend/src/components/brew/StartBrew.tsx`, `TrendChart.tsx`
- new `frontend/src/components/history/`

## Testing

- Repository unit tests against an in-memory SQLite database.
- Extend `backend/tests/api/conftest.py` so the `reset_globals` fixture also points the repository
  at a fresh temp database per test.
- A full mock brew (`MockScale`/`MockValve`) that asserts exactly one row is written and that its
  terminal state and quality JSON are correct.
- Restart-recovery test: insert a `BREWING` row, run startup, assert it is `ERROR`.

## Open questions

- Retention: unbounded history is fine at this scale (a few brews a week), so no pruning for now.
- Should the series endpoint cache the Influx result into the row once the brew completes, so
  history survives Influx retention expiry? Probably yes, as a downsampled trace (1 point/sec) in a
  `series_json` column. Deferred — decide after seeing how large the JSON gets.
