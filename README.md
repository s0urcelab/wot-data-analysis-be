# WoT Data API

Python 3.9+ service using Flask and SQLite. It provides tank catalogue data, mastery history, daily changes, player lookup, plugin version lookup, and scheduled data collection. Comments and badge processing are outside this service.

## Local run

```powershell
python -m pip install -r requirements.txt
python app.py
```

The API listens on `http://localhost:7001`. The default database file is `wot.sqlite3` in this directory. Set `DATABASE_PATH` to use another file. The scheduler refreshes the vehicle catalogue at 08:00 and collects mastery rankings at 12:00 Asia/Shanghai time. Set `ENABLE_SCHEDULER=false` to disable in-process scheduling.

## Migrate the existing MongoDB data

The migration imports `all_tanks`, `tanksgg_list`, and `history_mastery`, and skips `comments`. History is grouped by Shanghai calendar day and tank. Mastery values are merged across duplicate rows; if the same value conflicts, the row with the later MongoDB ObjectId wins. MongoDB is read only.

```powershell
$env:MONGODB_URI = 'mongodb://<host>:27017/wot'
python .\migrate_mongo_to_sqlite.py
```

The migration refuses to overwrite a database that already contains imported observations. `--replace` explicitly clears the SQLite tank catalogue, collection runs, and observations before reimporting. Set `DATABASE_PATH` or pass `--sqlite` to choose the destination file.

## Container

```sh
docker build -t wot-data-api .
docker run --name wot-data-api -p 7001:7001 \
  -e DATABASE_PATH=/data/wot.sqlite3 \
  -v wot-data:/data \
  wot-data-api
```

Gunicorn uses one worker because the app writes to a local SQLite database and runs its scheduler in-process. `MOD_VERSION_URL` overrides the plugin version endpoint.

## API v1

All successful responses are JSON. Errors use `{ "error": { "code": "...", "message": "..." } }`.

### `GET /api/v1/health`

Returns `{ "status": "ok" }`.

### `GET /api/v1/meta`

Returns available nations, vehicle types, tiers, and `last_updated`. Optional `player_id` and `nickname` add an external player summary.

### `GET /api/v1/tanks`

Optional filters: `nation`, `type`, `tier`, `premium` (`0` or `1`), `collector_vehicle` (`0` or `1`), and `player_id`. Pagination: `page` and `page_size` (`20`, `40`, or `100`). `sort` accepts a tank field such as `mastery_95`, `rank`, or `tier`; `order` is `asc` or `desc`.

Response: `{ "items": [...], "pagination": { "page": 1, "page_size": 20, "total": 123 } }`. Items include `id`, tank metadata, current mastery values, and rank. With `player_id`, matching items include `player_stats`.

### `GET /api/v1/tanks/{tank_id}/history`

Returns completed observations in date order. Each item includes `date`, `collected_at`, `mastery_65`, `mastery_85`, `mastery_95`, and `ace`.

### `GET /api/v1/today-changes`

Compares the latest completed collection for `date` with the latest completed collection on the previous calendar day. `date` defaults to today in Asia/Shanghai; `threshold` accepts `65`, `85`, or `95` and defaults to `95`. Pagination uses `page` and `page_size`. Items include `current_value`, `previous_value`, and signed `delta`; the default order is largest absolute change first.

### `POST /api/v1/players/search`

JSON body: `{ "nickname": "..." }`. Returns matching game accounts.

### `GET /api/v1/players/{player_id}/summary?nickname=...`

Returns battle count, win ratio, global rating, and efficiency data from the external services.

### `POST /api/v1/collections/run`

Starts a manual catalogue refresh and mastery collection. Returns HTTP 202 with `{ "status": "accepted" }`; returns HTTP 409 if another collection is running.

### `GET /api/v1/plugin/version`

Returns the newest directory name from the configured plugin version endpoint.

## Temporary frontend compatibility API

The existing frontend can keep its current API calls. These five endpoints are available both at the root and under `/api` (for example, `/tankList` and `/api/tankList`). The frontend development proxy currently strips `/api`; production can use an empty `API_PREFIX` or `/api`.

Responses use the legacy envelope `{ "errCode": 0, "data": ... }`. Business errors return HTTP 200 with a nonzero `errCode`, a `msg`, and an endpoint-appropriate empty `data`, so existing frontend handlers can read the error. The `/api/v1` routes retain their own response envelopes and HTTP error statuses.

| Endpoint | Compatibility behavior |
| --- | --- |
| `GET /tankList` | Accepts `page`, `size` (20/40/100), existing tank filters, `player_id`, `sort`, and Ant Design `order=ascend/descend`. Returns `data.list` and `data.total`; tank IDs are `_id`, flags are numeric `premium`/`collector_vehicle`, and player badges use `pl.mastery`/`pl.moe`. |
| `GET /preData` | Accepts optional `pid` and `pn`. Returns `nations`, `types`, `tiers`, `lastUpdate`, and optional `player` with `battTotal`, `winRate`, `wgr`, numeric `eff`, and numeric `effDelta`. Unavailable player summaries return `player: null`. |
| `POST /bindUser` | JSON body: `{ "nickname": "..." }`. Returns the account array directly in `data`, preserving `account_id`, `account_name`, and `clan_tag`. Error codes: 20001 for invalid/short nicknames, 20002 for no match, 20003 for upstream failure. |
| `GET /history?id=...` | Returns `data.list` with `date`, `mastery_65`, `mastery_85`, `mastery_95`, and `ace`, ordered by date and restricted to completed collection runs. |
| `GET /modVersion` | Returns the plugin version string directly in `data`. |

The adapters reuse v1 handlers and SQLite data. A player with no recorded vehicles receives an empty tank list. Upload/download badge processing and comments are excluded. Historical data follows the refactored database's migrated observations; this layer does not recreate MongoDB fields discarded during migration.

Run the compatibility and v1 regression checks with `python -m unittest test_compat -v`. Tests use temporary SQLite databases, disable scheduling, and mock external player/version services.
