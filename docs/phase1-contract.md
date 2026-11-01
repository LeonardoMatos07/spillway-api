# Phase 1 contract

Single source of truth between the four repositories. Any change here requires updating
`spillway-api` (the schema owner) first.

| Repository | Role |
|---|---|
| `spillway-data` | Airflow: ingests ONS data, computes the aggregates and **only writes** to the tables below |
| `spillway-api` | FastAPI: **schema owner** (Alembic), public reads, newsletter, admin |
| `spillway-web` | Next.js: public portal with ISR, admin area |
| `spillway-infra` | Terraform: AWS `sa-east-1` |

## Conventions

- Table, column, route and parameter names in **English**, `snake_case`.
- Code, documentation, logs and messages in English. Only text shown to site visitors (pages
  and newsletter e-mails) is in Portuguese, and so are the public site URLs.
- `source`: `wind`, `solar` or `total` (sum of both, aggregates only).
- `subsystem`: `N`, `NE`, `S`, `SE`; `SIN` is the national total (only in
  `subsystem_monthly_curtailment`).
- `state`: two-letter uppercase Brazilian state code.
- `month`: `date` holding the first day of the month (`2026-09-01`). In the API, `YYYY-MM`.
- Energy in MWh, money in BRL (`numeric`), percentages from 0 to 100 with 2 decimals.
- ONS timestamps are in Brasília time; `timestamptz` columns store UTC.
- Python: `uv`, `ruff` (lint and format), `mypy`, `pytest`. TypeScript: `pnpm`, ESLint,
  Prettier, Vitest. Commits follow Conventional Commits.
- Versions pinned exactly, published at least two weeks earlier.
- No comments in the code.

## Postgres schema (owner: `spillway-api`, Alembic)

Postgres only keeps what the portal reads. The detailed history lives in S3.

### `plant`
Plants and clusters. Plants dispatched individually (ONS "Type I") are `kind = 'plant'` with a
null `cluster_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | ONS id of the plant or cluster (`CJU_...`) |
| `kind` | `text` NOT NULL | `plant` or `cluster` |
| `name` | `text` NOT NULL | |
| `slug` | `text` NOT NULL UNIQUE | stable: `slug(name)-slug(id)`, e.g. `sao-fernando-4-rnesf4` |
| `source` | `text` NOT NULL | `wind` or `solar` |
| `state` | `char(2)` NOT NULL | |
| `subsystem` | `varchar(3)` NOT NULL | |
| `cluster_id` | `text` NULL FK → `plant.id` | |
| `ceg` | `text` NULL | ANEEL code |
| `capacity_mw` | `numeric(10,3)` NULL | sum of the generating units in operation |
| `connection_point` | `text` NULL | name of the grid connection point (clusters) |
| `operator` | `text` NULL | operating agent |
| `updated_at` | `timestamptz` NOT NULL DEFAULT now() | |

Indexes: `slug` (unique), `(state, source)`, `cluster_id`, and name search through
`lower(name)` (or `pg_trgm`, when available).

### `plant_monthly_curtailment`
One row per plant or cluster and month. For clusters the figures are the official ONS ones
(GNRa); for plants, the allocated GNRa (sum of the plants = cluster).

| Column | Type |
|---|---|
| `plant_id` | `text` FK → `plant.id` |
| `month` | `date` |
| `verified_generation_mwh` | `numeric(14,3)` NOT NULL |
| `curtailed_mwh` | `numeric(14,3)` NOT NULL |
| `curtailment_pct` | `numeric(6,2)` NULL (curtailed / (verified + curtailed) × 100) |
| `curtailed_rel_mwh`, `curtailed_cnf_mwh`, `curtailed_ene_mwh`, `curtailed_other_mwh` | `numeric(14,3)` NOT NULL |
| `estimated_loss_brl` | `numeric(16,2)` NULL |
| `price_basis` | `text` NULL (`PLD`, `CMO`, `PLD_FILLED`, `CMO_FILLED`: the prevailing basis in the month) |
| `restricted_hours` | `numeric(7,1)` NOT NULL |
| `state_avg_curtailment_pct` | `numeric(6,2)` NULL (state and source average in the month, for comparison) |
| `national_rank` | `integer` NULL (per source and month, by curtailed energy; `kind = 'plant'` only) |
| `state_rank` | `integer` NULL (per state, source and month; `kind = 'plant'` only) |
| `updated_at` | `timestamptz` NOT NULL DEFAULT now() |

PK `(plant_id, month)`. Indexes: `(month, national_rank)`, `(month, state_rank)`.

### Forecast tables (ADR 0007)

`spillway-forecast` (`spillway publish`, role `energia_forecast`) writes `forecast_model`, `forecast_run` and `forecast_hourly` in one transaction; the API only reads the latest run with `status = 'ready'`. Routes: `GET /v1/forecast?scope=&source=&days=`, `GET /v1/forecast/scopes`, `GET /v1/forecast/model` (public, short cache, `404` until something is published).

### Flag forecast tables (migration `0016`; tariff-flag forecast spec, stage 1)

Schema only: no route and no writer yet. Stage 0 discovery: `docs/flag-forecast-discovery.md` in `spillway-forecast`. Nothing here stores or serves the CCEE bulletin files, only numeric facts and the bulletin reference (number, URL, date).

- `flag_rule_month` (PK `month`): one row per month, written by the pipeline (`energia_data`) from the InfoBandeira bulletin. `rule_version`, `pld_min_brl_per_mwh`, `pld_max_brl_per_mwh`, `gh_mwmed`, `gf_mwmed`, `gsf` (`numeric(4,2)`), `pld_trigger_brl_per_mwh` (official trigger), `gfom_mwmed` (default 0), `green_upper_brl_per_mwh`, `yellow_upper_brl_per_mwh`, `red1_upper_brl_per_mwh` (the red 2 upper limit is `pld_max_brl_per_mwh`), `flag` (same labels as `tariff_flag_monthly`), `bulletin_number`, `bulletin_url`, `bulletin_published_on`, `revised_on` (when ANEEL revised the colour after publishing), `updated_at`. Checks: PLD range and band order.
- `flag_forecast_run` (`id` identity): `target_month`, `lead_days` (> 0), `generated_at`, `data_through`, `model_version`, `rule_version`, `trigger_p10/p50/p90_brl_per_mwh` (forecast trigger median and 80% interval), `status` (`loading`, `ready`). Unique `(target_month, lead_days, generated_at)`: forecasts are kept with their date, never rewritten. Readers only see `status = 'ready'`.
- `flag_forecast_prob` (PK `(run_id, flag)`, `flag` in `Verde`, `Amarela`, `Vermelha P1`, `Vermelha P2`): `prob` 0..1 plus the band (`band_lower_brl_per_mwh`, `band_upper_brl_per_mwh`) used for that colour.
- `flag_forecast_input` (PK `run_id`): `inputs` JSON with the key inputs of the run.
- `flag_forecast_score` (PK `run_id`): `actual_flag`, `prob_actual`, `brier`, `top_hit`, `scored_at`, written after the official flag appears in `tariff_flag_monthly`.
- Children cascade on `flag_forecast_run`. Writers: `energia_forecast` writes the four `flag_forecast_*` tables (insert/delete; `UPDATE` only of `flag_forecast_run.status`); `energia_data` writes `flag_rule_month`. No existing table was changed.

### News tables (`news_source`, `news_item`, `regulatory_act`)

Public sector news, shown exactly as the source published it, always with the publisher, date, link and license.

- `news_source`: one row per source (`slug` unique: `aneel`, `mme`, `anp`, `epe`, `dou`) with `publisher_name`, `homepage_url`, `feed_url`, `fetch_method` (`rss`, `api`, `listing`, `open-data`), `license_code` / `license_url`, `license_verified_at`, `license_evidence_url` and `active`. Seeded by the migration; nobody writes it at runtime. `dou` is seeded `active = false` until a legitimate open channel exists.
- `news_item`: `url` is canonical and **unique**. Written by the pipeline: `source_id`, `url`, `title`, `summary` (as published), `published_at`, `source_updated_at` (UTC), `fetched_at`, `content_hash`, `topics` (JSON list of slugs). Written by the **API (admin)**: `status` (`published` default, `hidden`, `removed_on_request`), `editor_note`, `editor_note_by`, `editor_note_at`, `related_links` (JSON list of `{label, href}`). The pipeline upserts by `url` and never touches the admin columns.
- `regulatory_act`: official acts from the DOU (`organ`, `act_type`, `act_number`, `act_date`, `title`, `summary`, `body`, full DOU reference `dou_date`, `dou_section`, `dou_edition`, `dou_page`, `dou_url`, `topics`, `content_hash`, `fetched_at`). Unique `(dou_url, content_hash)`. The pipeline writes everything except `status`, which the API (admin) updates.
- Reads: the API serves only `status = 'published'` rows, in public routes under `/v1/news` and `/v1/regulatory-acts`.

### `state_monthly_curtailment`
| Column | Type |
|---|---|
| `state` | `char(2)` |
| `source` | `text` (`wind`, `solar`, `total`) |
| `month` | `date` |
| `verified_generation_mwh`, `curtailed_mwh` | `numeric(16,3)` NOT NULL |
| `curtailment_pct` | `numeric(6,2)` NULL |
| `curtailed_rel_mwh`, `curtailed_cnf_mwh`, `curtailed_ene_mwh`, `curtailed_other_mwh` | `numeric(16,3)` NOT NULL |
| `estimated_loss_brl` | `numeric(16,2)` NULL |
| `affected_plants` | `integer` NOT NULL (plants with curtailment > 0) |
| `updated_at` | `timestamptz` NOT NULL DEFAULT now() |

PK `(state, source, month)`.

### `subsystem_monthly_curtailment`
Same columns as `state_monthly_curtailment`, with `subsystem` (`N`, `NE`, `S`, `SE`, `SIN`)
instead of `state`. PK `(subsystem, source, month)`.

### `load_run`
One row per pipeline load (read by `/v1/admin/load-runs`).

| Column | Type |
|---|---|
| `id` | `bigint` identity PK |
| `dataset` | `text` NOT NULL (source name, e.g. `wind_plant_curtailment`, or `aggregates`) |
| `period` | `date` NULL (processed month) |
| `source_file` | `text` NULL (source URL) |
| `checksum` | `text` NULL (sha256) |
| `row_count` | `integer` NULL |
| `started_at` | `timestamptz` NOT NULL |
| `finished_at` | `timestamptz` NULL |
| `status` | `text` NOT NULL (`running`, `success`, `failed`) |
| `detail` | `text` NULL (quality warnings or error) |

Index `(started_at DESC)`.

### `monthly_report`
| Column | Type |
|---|---|
| `id` | `bigint` identity PK |
| `month` | `date` NOT NULL |
| `title` | `text` NOT NULL |
| `slug` | `text` NOT NULL UNIQUE |
| `summary` | `text` NULL |
| `content` | `text` NOT NULL (Markdown) |
| `published_at` | `timestamptz` NULL (null = draft) |
| `created_at`, `updated_at` | `timestamptz` NOT NULL DEFAULT now() |

### `newsletter_subscriber`
| Column | Type |
|---|---|
| `id` | `bigint` identity PK |
| `email` | `text` NOT NULL UNIQUE (lowercase) |
| `consented_at` | `timestamptz` NOT NULL |
| `confirmed_at` | `timestamptz` NULL |
| `unsubscribed_at` | `timestamptz` NULL |
| `confirmation_token_hash` | `text` NULL (sha256 of the token; the token itself is never stored) |
| `confirmation_token_expires_at` | `timestamptz` NULL |
| `unsubscribe_token_hash` | `text` NOT NULL (one-click unsubscribe, never expires) |
| `signup_source` | `text` NULL |
| `created_at` | `timestamptz` NOT NULL DEFAULT now() |

Retention (LGPD, data minimization): on every `POST /v1/newsletter`, the API deletes the
addresses that never confirmed after the confirmation link expired (48 h) and the ones
unsubscribed for more than 30 days. The portal privacy policy (`/privacidade`) promises these
periods.

### `organization` and `app_user` (Phase 2 groundwork, created empty)
- `organization`: `id uuid` PK, `name text NOT NULL`, `created_at`.
- `app_user`: `id uuid` PK, `cognito_sub text UNIQUE NOT NULL`, `email text UNIQUE NOT NULL`,
  `name text NULL`, `organization_id uuid FK NULL`, `role text NOT NULL`
  (`owner`, `member`, `admin`), `created_at`.

### System generation tables (migration 0008)
Written by `spillway-data` (`system` pipeline). Power values are **average MW** over the hour
(ONS "MWmed", so MWh in an hour); energies are MWh. Hours are Brasilia time (`hour`) plus UTC
(`hour_utc`). `subsystem` uses the same codes as the other tables.
- `subsystem_hourly_balance`: PK `(hour, subsystem)`; `hydro_mw_avg`, `thermal_mw_avg`,
  `wind_mw_avg`, `solar_mw_avg`, `load_mw_avg`, `net_interchange_mw_avg` (nullable). Thermal
  includes nuclear. Subsystems `N`, `NE`, `S`, `SE`.
- `subsystem_monthly_generation`: PK `(month, subsystem, source)`; `source` is `hydro`,
  `thermal`, `wind` or `solar`; subsystem also has `SIN` (sum); `energy_mwh`, `avg_mw`,
  `peak_mw`, `share_pct` (share of the four sources).
- `power_plant`: the whole generation fleet (`id` PK, `name`, `slug` unique, `source_type` in
  `hydro|thermal|nuclear|wind|solar|other`, `fuel_type`, `state`, `subsystem`, `ceg`,
  `capacity_mw`, `updated_at`). `plant` stays the curtailment product (wind and solar only), so
  hydro and thermal plants do not fit it; wind and solar plants use the same id and slug rule.
- `plant_monthly_generation`: PK `(month, plant_id)`, FK `power_plant.id`; `energy_mwh`,
  `avg_mw`, `peak_mw`, `capacity_factor` (energy / (capacity x hours of the month), 0 to 1.05).

### Interchange and thermal dispatch (migration 0009)
- `interchange_hourly`: PK `(hour, origin, destination)`, `scope` (`national` between subsystems,
  `international` from `BR` to a country in upper case), `hour_utc`, `flow_mw_avg`,
  `scheduled_mw_avg`. **Positive flow means origin to destination**; the ONS reports national
  flows as origin/destination pairs (a negative value is a flow in the opposite direction) and
  international ones as the flow to the destination country (negative is an import).
- `interchange_monthly`: PK `(month, origin, destination)`; `energy_mwh` (net, signed),
  `scheduled_energy_mwh`, `avg_mw`, `peak_mw`, `min_mw`. The ONS dictionaries carry no
  transmission limit, so there is no "hours at limit" column.
- `thermal_dispatch_monthly`: PK `(month, plant_code, reason)`; `plant_code` is the planning code
  (`cod_usinaplanejamento`), plus `plant_name`, `ceg`, `fuel_type`, `subsystem`, `verified_mwh`,
  `programmed_mwh`. `reason` is one of `total`, `merit_order`,
  `merit_order_above_inflexibility`, `inflexibility`, `inflexibility_in_merit`,
  `inflexibility_pure`, `electrical_reason`, `energy_security`, `gfom`, `loss_replacement`,
  `export`, `power_reserve`, `gsub`, `unit_commitment`, `constrained_off`. Reasons **overlap**
  (merit order contains its above-inflexibility part; inflexibility is split in two), so only
  read them one at a time or against `total`.

### Hydrology tables (migration 0010)
Energy stored in reservoirs (EAR) is in **MW-month** (`_mw_month`), natural inflow energy (ENA) in
average MW (`_mw_avg`) and as a percentage of the long-term average (`_pct_mlt`); flows are in
m3/s (`_m3s`) and levels in metres (`_m`).
- `reservoir`: the register (`id` PK = ONS `res_id`, `name`, `slug` unique, `reservoir_type`,
  `planning_code`, `station_code`, `plant_name`, `ceg`, `subsystem`, `ree`, `basin`, `river`,
  `commissioned_on`, levels, volumes in hm3, `latitude`, `longitude`). Snapshot, upserted by `id`.
- `subsystem_storage_daily`: PK `(day, subsystem)`; `storage_max_mw_month`, `storage_mw_month`,
  `storage_pct` (0 to 100), `ena_gross_*`, `ena_storable_*`.
- `reservoir_daily`: PK `(day, reservoir_id)`, FK `reservoir.id`; the same storage and ENA columns
  (`storage_pct` has no range check: it is negative below the minimum operating volume and
  above 100 while a reservoir spills; the ONS shows -83% to 379% in 2015)
  per reservoir plus `useful_volume_pct`, `inflow_m3s`, `natural_inflow_m3s`, `outflow_m3s`,
  `turbined_m3s`, `spilled_m3s`, `upstream_level_m`, `downstream_level_m`. The ONS uses three
  reservoir codes: EAR and ENA use the planning code (`cod_resplanejamento`), the hydrological
  data use `id_reservatorio` (= `res_id`); the register maps one to the other.
- `plant_monthly_spilled_energy`: PK `(month, plant_code)` (`plant_code` is the ONS optimisation
  code `cod_usina`), `plant_name`, `subsystem`, `basin`, `river`, `agent`, `spilled_energy_mwh`,
  `spilled_turbinable_energy_mwh`. It does not join `power_plant` (different codes).

### Grid register (migration 0011)
Three tables with the ONS register of the grid. Each is **versioned by snapshot**: the pipeline
reads the whole register once a month and writes a new row only when something changed, so the
expansion of the grid can be replayed. `valid_from` is the snapshot date that first showed the
version, `valid_to` the snapshot date that no longer did (`NULL` = current); a partial unique index
guarantees one current version per item.
- `transmission_line`: PK `(equipment_code, valid_from)`, `row_hash`, `name`, `voltage_kv`,
  `line_type`, `network_type`, `owner_agent`, `from_substation`, `to_substation`, `from_subsystem`,
  `to_subsystem` (`N`, `NE`, `S`, `SE` or `PY`, `AR`, `UY`, `VE` for interconnections),
  `from_state`, `to_state`, `length_km`, `positive_seq_resistance`, `positive_seq_reactance`,
  `positive_seq_shunt` (positive sequence values as published; the ONS does not state the unit),
  the four contracted capacities in **ampere** (`capacity_long_no_limit_a`,
  `capacity_long_with_limit_a`, `capacity_short_no_limit_a`, `capacity_short_with_limit_a`),
  `commissioned_on`, `decommissioned_on`, `planned_on`, `from_bus`, `to_bus`. The eight seasonal
  capacities of the file are not loaded.
- `substation`: PK `(station_id, valid_from)` (a station is one voltage level of a substation),
  `substation_id`, `name`, `voltage_kv`, `subsystem`, `state`, `main_agent`, `bus_number`,
  `latitude`, `longitude`. The coordinates are the ones the ONS publishes (some are empty); nothing
  is geocoded here.
- `transformer_capacity`: PK `(equipment_code, valid_from)`, `name`, `transformer_type`,
  `substation`, `owner_agent`, `subsystem`, `state`, `primary_kv`, `secondary_kv`, `tertiary_kv`,
  `rated_mva`, `network_type`, dates and buses. No endpoint yet.

### How `spillway-data` writes
- `plant`: upsert by `id`.
- `*_monthly_curtailment`: for each processed month, deletes the rows of that `month` and
  inserts the new ones, in one transaction (idempotent).
- `load_run`: one row per source and month, plus one `aggregates` row per month.
- `power_plant`: upsert by `id`. `subsystem_monthly_generation`, `plant_monthly_generation`: same
  delete-and-insert by `month`. `subsystem_hourly_balance`: delete-and-insert by `hour` range.
- `interchange_hourly`: delete-and-insert by `hour` range; `interchange_monthly` and
  `thermal_dispatch_monthly`: by `month`.
- `reservoir`: upsert by `id`. `subsystem_storage_daily` and `reservoir_daily`: delete-and-insert
  by `day` range of the processed month; `plant_monthly_spilled_energy`: by `month`.
- `transmission_line`, `substation`, `transformer_capacity`: versioned snapshots. Closes the
  current rows that changed or disappeared (`valid_to` = snapshot date) and inserts the new or
  changed ones, in one transaction; running the same snapshot date again gives the same result.
- `news_item` / `regulatory_act`: upsert by `url` (or `(dou_url, content_hash)`), only the pipeline columns; `SELECT` on `news_source`.
- Its own database user, with `SELECT, INSERT, UPDATE, DELETE` on these tables only.

## Data lake (S3)

```
bronze/ons/<source>/<partition>/<original file>   as published by ONS
silver/<source>/year=YYYY/month=MM/data.parquet    standardized (and modelled, for curtailment)
gold/<table>/year=YYYY/month=MM/data.parquet       the same aggregates as Postgres
```

## API (`spillway-api`)

Base `/v1`. JSON keys match the column names. `numeric` values are serialized as numbers.
Public routes: no authentication, with `Cache-Control: public, max-age=300, s-maxage=3600,
stale-while-revalidate=86400`. Errors use `{"detail": "..."}` (always a string, including the
422 validation errors). Months (`month`, `start`, `end`, `period`, `ranking_month`) go in and
out as `YYYY-MM`.

| Method | Route | Access | Returns |
|---|---|---|---|
| GET | `/v1/curtailment/subsystems?source=&start=&end=&subsystem=` | Public | `{"items": [subsystem_monthly_curtailment row]}` ordered by `month`, `subsystem`; `source` defaults to `total`; `start`/`end` as `YYYY-MM`; optional `subsystem` (`N`, `NE`, `S`, `SE`, `SIN`; all of them without it) |
| GET | `/v1/curtailment/states/{state}?source=&month=` | Public | `{"series": [state_monthly_curtailment rows], "ranking": [RankedPlant], "ranking_month": "YYYY-MM" or null}`; ranking of `month` (default: latest month with data for the state; `null` when there is none), top 20. `state` accepts lowercase; 404 when it is not a Brazilian state, 422 when it is not two letters |
| GET | `/v1/geo/states/curtailment?source=&month=` | Public (the web shows it to members only, like `/estados`) | Map layer: `{"meta": {source_name, source_url, license, data_source, month, months, updated_at, warnings, omitted, omitted_states}, "items": [{state, curtailment_pct, curtailed_mwh, verified_generation_mwh, estimated_loss_brl, affected_plants}]}`, one item per state with data in `month` (default the latest month of `source`, which defaults to `total`). No geometry: the web draws the IBGE outlines. States without data are not items; `meta.omitted` counts them and `meta.omitted_states` lists them. 404 when `month` has no data, 422 on a malformed month or source |
| GET | `/v1/geo/reservoirs?date=&subsystem=` | Public | GeoJSON `FeatureCollection` of reservoirs that have a position (Point `[lon, lat]`), `properties` {slug, name, plant_name, subsystem, basin, river, useful_volume_hm3, storage_pct, ena_storable_pct_mlt, day} for `date` (default the latest day with data), plus `meta` {source_name, source_url, license, as_of, updated_at, warnings, total, omitted}; reservoirs without coordinates are not features and are counted in `meta.omitted`. 404 when the day has no data |
| GET | `/v1/system/balance?subsystem=&from=&to=` | Public | `{"date_from", "date_to", "points": [subsystem_hourly_balance row]}`, hourly, at most 31 days (422 above); `from`/`to` as `YYYY-MM-DD`, default the last 7 days with data |
| GET | `/v1/system/generation?subsystem=&from=&to=` | Public | `{"points": [subsystem_monthly_generation row]}`; `subsystem` defaults to `SIN`; `from`/`to` as `YYYY-MM`, default the last 12 months |
| GET | `/v1/system/interchange?origin=&destination=&scope=&from=&to=` | Public | `{"points": [interchange_monthly row]}`; `from`/`to` as `YYYY-MM`, default the last 12 months |
| GET | `/v1/system/interchange/hourly?origin=&destination=&from=&to=` | Public | `{"date_from", "date_to", "points": [interchange_hourly row]}`, at most 31 days |
| GET | `/v1/system/thermal-dispatch?subsystem=&reason=&plant=&from=&to=` | Public | `{"points": [...]}` summed per month, subsystem and reason (`plants` = how many plants), or per plant when `plant` (a `plant_code`) is given |
| GET | `/v1/hydro/subsystems?subsystem=&from=&to=` | Public | `{"date_from", "date_to", "points": [subsystem_storage_daily row]}`; days as `YYYY-MM-DD`, default the last 90 days of data, at most 366 |
| GET | `/v1/hydro/reservoirs?subsystem=&basin=` | Public | `{"latest_day", "items": [reservoir + storage_pct and ena_storable_pct_mlt of the latest day]}` |
| GET | `/v1/hydro/reservoirs/{slug}?from=&to=` | Public | `{"reservoir", "points": [reservoir_daily row]}`; 404 for an unknown slug |
| GET | `/v1/hydro/spilled-energy?subsystem=&plant=&month=&limit=` | Public | `{"points": [plant_monthly_spilled_energy row]}` of one month (default the latest), largest turbinable energy first |
| GET | `/v1/grid/lines?voltage_kv=&min_voltage_kv=&state=&subsystem=&as_of=&page=&page_size=` | Public | `{"as_of", "total", "page", "page_size", "items": [transmission_line version]}`, highest voltage first; `state`/`subsystem` match either end; without `as_of` only the current versions |
| GET | `/v1/grid/substations?voltage_kv=&min_voltage_kv=&state=&subsystem=&as_of=&page=&page_size=` | Public | same envelope with `substation` versions |
| GET | `/v1/plants/{slug}/generation?from=&to=` | Public | `{"plant": power_plant, "points": [plant_monthly_generation row]}`; 404 for an unknown slug |
| GET | `/v1/plants?search=&state=&source=&kind=&page=1&page_size=20` | Public | `{"items": [PlantSummary], "total": n, "page": p, "page_size": s}`; `page` ≥ 1, `page_size` from 1 to 100 |
| GET | `/v1/plants/{slug}` | Public | `{"plant": Plant, "cluster": PlantSummary|null, "cluster_plants": [PlantSummary], "series": [plant_monthly_curtailment rows]}` |
| GET | `/v1/ranking?month=&state=&source=&limit=20` | Public | `{"month": "YYYY-MM" or null, "items": [RankedPlant]}` (`limit` ≤ 100; `month` defaults to the latest month with data; `null` and an empty list when there is no data) |
| GET | `/v1/months` | Public | `{"months": ["YYYY-MM", ...]}` months with data, newest first |
| GET | `/v1/reports` | Public | `{"items": [ReportSummary]}` published only |
| GET | `/v1/reports/{slug}` | Public | `Report` (404 for drafts) |
| POST | `/v1/newsletter` | Public, rate limited (5/min per IP, see below) | `202 {"message": "..."}`; body `{"email", "consent": true, "source"?}`; always 202, even when already subscribed (does not leak who is on the list); 429 with `Retry-After: 60` over the limit |
| GET | `/v1/newsletter/confirm?token=` | Public | `{"confirmed": true}` or 400 |
| GET | `/v1/newsletter/unsubscribe?token=` | Public | `{"unsubscribed": true}` or 400 |
| GET | `/v1/admin/load-runs?limit=50` | Admin | `{"items": [load_run row]}`, newest first; `limit` from 1 to 500; `period` as `YYYY-MM` (or null) |
| GET | `/v1/admin/reports` | Admin | `{"items": [AdminReport]}`, all of them including drafts (`published_at` null), by `month` descending |
| POST | `/v1/admin/reports` | Admin | `200 AdminReport`; creates or updates by `slug`; body `{"month": "YYYY-MM", "title", "slug"?, "summary"?, "content", "publish": bool}`. Optional `slug` (`^[a-z0-9]+(-[a-z0-9]+)*$`, up to 200); generated from `title` when missing. `publish: true` keeps the original publication date; `false` turns it back into a draft |
| POST | `/v1/admin/revalidate` | Admin | optional body `{"tags": [...]}` (default: all; unknown tag = 422); clears the API cache and calls `spillway-web`. Always 200 `RevalidateResponse`, even when `spillway-web` fails |
| GET | `/health` | Internal | `{"status": "ok", "database": "ok"}` |

Payloads:
- `PlantSummary`: `id, kind, name, slug, source, state, subsystem, capacity_mw`
- `Plant`: `PlantSummary` + `cluster_id, ceg, connection_point, operator, updated_at`
- `RankedPlant`: `PlantSummary` + `rank, curtailed_mwh, curtailment_pct, estimated_loss_brl`
- `ReportSummary`: `month, title, slug, summary, published_at`; `Report`: + `content`;
  `AdminReport`: `Report` + `created_at, updated_at`
- `RevalidateResponse`: `{"tags": [...], "cache_cleared": true, "entries_removed": n,
  "web_revalidated": bool, "detail": "..." | null}`. `web_revalidated = false` with `detail`
  when `spillway-web` did not answer 2xx or `REVALIDATE_SECRET` is not set.

### Client IP for the newsletter limit

The 5/min limit is per IP and per API instance. The IP is chosen like this:

1. When `WEB_API_SECRET` is set and the request carries an equal `X-Web-Api-Secret`
   (constant-time comparison), the IP in `X-Client-IP` (valid IPv4 or IPv6) is used. This is
   how `spillway-web`, which calls the API from its server (every visitor leaves through the
   same Vercel IP), forwards the visitor IP.
2. Otherwise, with `TRUST_X_FORWARDED_FOR=true`, the rightmost `X-Forwarded-For` entry (the
   one the ALB appends).
3. Otherwise, the connection IP.

`X-Client-IP` without the right secret is ignored. The secret only exists on the API and
`spillway-web` servers; it never reaches the browser.

## Authentication

- Cognito User Pool, e-mail sign-in, mandatory MFA. `admin` group. Self sign-up disabled.
- **Admin (person)**: `spillway-web` signs in with OAuth + PKCE (Auth.js, Cognito provider),
  session in an `httpOnly` cookie; it calls the API from the server with the *access token*.
- **Machine (`spillway-data` → API)**: app client with *client credentials* and the
  `energia-api` resource server with the `energia-api/admin` scope.
- On `/v1/admin/*` the API accepts a Cognito JWT (RS256, pool JWKS, pool `iss`,
  `token_use = access`) that has the `admin` group in `cognito:groups` **or** the
  `energia-api/admin` scope.
- Local: `AUTH_DISABLED=true` opens the admin routes **only** with `ENVIRONMENT=local` (the API
  refuses to start with that flag in any other environment).

## Portal revalidation

1. After each load, `spillway-data` calls `POST {API_URL}/v1/admin/revalidate` with
   `{"tags": ["curtailment", "plants"]}`.
2. The API clears its own cache and calls `POST {WEB_URL}/api/revalidate` with the
   `x-revalidate-secret: {REVALIDATE_SECRET}` header and the same body.
3. `spillway-web` calls `revalidateTag` for each tag. Tags used by the `fetch` calls:
   `curtailment`, `plants`, `reports`.

## Local environment

| Service | Address |
|---|---|
| Postgres | `localhost:5433`, database `warehouse` (user/password `warehouse` in dev) |
| S3 (SeaweedFS) | `http://localhost:8333`, bucket `energy-lake` |
| API | `http://localhost:8000` |
| Web | `http://localhost:3000` |
| Airflow | `http://localhost:8080` |

Main variables: `DATABASE_URL` (API), `WAREHOUSE_DSN` (data), `API_URL`, `WEB_URL`,
`REVALIDATE_SECRET`, `WEB_API_SECRET` (API and web), `COGNITO_REGION`, `COGNITO_USER_POOL_ID`,
`COGNITO_APP_CLIENT_IDS`, `ENVIRONMENT` (`local` or `prod`).

## CI/CD (GitHub Actions)

- Every PR: lint, type checks and tests.
- Merge to `main` on `spillway-api` and `spillway-data`: Docker image pushed to ECR (AWS
  authentication through OIDC) and deployed.
- `spillway-web`: deployed by Vercel (one preview per PR); CI runs lint, types and tests.
- `spillway-infra`: `terraform plan` on PRs; `apply` on `main` with manual approval
  (`production` environment with required reviewers).

### Market prices and quality of supply (migration 0014)

Sources, licenses and who writes what. All of these tables are written by `spillway-data` (role
`energia_data`) and only read by the API.

- `data_source`: registry of datasets with `slug` (PK), `publisher_name`, `dataset_name`,
  `dataset_url`, `license_code`, `license_url`, `license_verified_at`, `attribution_text` and
  `update_frequency`. **Written by the migration (seed), never by the pipeline.** The API returns
  the matching row as `source` in every response, and the web shows it with `DataAttribution`.
  Seeded: `ccee-pld` (CC BY 4.0) and `aneel-reliability` (ODbL 1.0).
- `pld_hourly`: PK `(hour_utc, subsystem, variant, method)`; `hour` (local Brasilia time),
  `pld_brl_per_mwh`. `variant` is `official` (CCEE hourly PLD, 2021 on) or `shadow` (CCEE "shadow"
  simulation, 2022 to 2024; it is **not** the settlement price). `method` is `official` or the
  shadow methodology (`NEWAVE_HIBRIDO`, ...).
- `pld_weekly`: PK `(week_start, subsystem)`; `pld_avg_brl_per_mwh` (CCEE weekly average, 2001 on).
- `pld_daily` and `pld_monthly`: PK `(day|month, subsystem)`; `pld_avg_brl_per_mwh`,
  `pld_min_brl_per_mwh`, `pld_max_brl_per_mwh`, `pld_std_brl_per_mwh`, `hours_at_floor`,
  `hours_at_cap`, `hours`. Derived from the **official** hourly series; floor and cap are the
  yearly ANEEL limits (seed `pld_limits.csv` in `spillway-data`).
- `distributor`: PK `cnpj`; `acronym`. Regulated distribution companies only (no personal data).
- `consumer_unit_set`: PK `(distributor_cnpj, set_id)`; `set_name` (electrical set).
- `reliability_monthly`: PK `(month, distributor_cnpj, set_id)`; `consumers`, `dec_hours` (hours),
  `fec_count` (interruptions), `dec_limit_hours` and `fec_limit_count` (the **annual** regulatory
  limit of that set and year, repeated in each month). Source: ANEEL
  `indicadores-coletivos-de-continuidade-dec-e-fec`, 2020 on.

How `spillway-data` writes them: `ccee_pld_pipeline` (daily) deletes the year of a variant from
`pld_hourly` and reinserts it, upserts `pld_weekly`, then rebuilds `pld_daily` and `pld_monthly`
from the first affected year. `aneel_reliability_pipeline` (monthly) upserts `distributor` and
`consumer_unit_set`, then replaces `reliability_monthly` from the first month it loaded. Both keep
the original files in the lake under `bronze/ccee/` and `bronze/aneel/reliability/`.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/v1/market/pld?granularity=&subsystem=&variant=&from=&to=` | Public | `granularity` is `hourly` (at most 31 days), `daily` (default, last 90 days), `weekly` or `monthly`. `variant=shadow` is hourly only. `{"granularity", "variant", "date_from", "date_to", "source", "points"}` |
| GET | `/v1/reliability?year=` | Public | DEC and FEC per distributor for the year (sum of the monthly values, consumer-weighted over its sets), worst DEC first, with `months_with_data`, the annual limits and `source` |
| GET | `/v1/reliability/{cnpj}?year=` | Public | Monthly DEC and FEC of one distributor |

Cache tags `market` and `reliability` can be passed to `POST /v1/admin/revalidate`.

### Tariff flags and the free market (migration 0015)

Written by `spillway-data`, read by the API. Their sources are seeded in `data_source`
(`aneel-tariff-flags`, ODbL 1.0; `ccee-market`, CC BY 4.0).

- `tariff_flag_monthly`: PK `month`; `flag` (`Verde`, `Amarela`, `Vermelha P1`, `Vermelha P2`,
  `Escassez Hídrica`) and `additional_brl_per_mwh`. The unit is **R$ per MWh** (inferred: the
  ANEEL dictionary does not state it, and `18.85` for the yellow flag matches R$ 1,885 per 100 kWh).
  It is charged on top of the homologated tariff, before taxes: it is not the electricity bill.
- `market_consumption_monthly`: PK `month`; `regulated_mw_avg` (ACR) and `free_mw_avg` (ACL), average
  MW (CCEE, 2023 on).
- `market_agents_monthly`: PK `(month, agent_class)`; `agents` (CCEE, 2023 on). Market-wide counts per
  class, never per agent.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/v1/tariffs/flags?from=&to=` | Public | `{"source", "items": [{"month", "flag", "additional_brl_per_mwh"}]}` |
| GET | `/v1/market/consumption` | Public | `{"source", "consumption": [{"month", "regulated_mw_avg", "free_mw_avg", "free_share_pct"}], "agents": [...]}` |

Both use the `market` cache tag.
