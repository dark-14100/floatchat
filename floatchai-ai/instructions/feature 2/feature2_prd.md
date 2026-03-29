# FloatChat — Feature 2: Ocean Data Database
## Product Requirements Document (PRD)

**Feature Name:** Ocean Data Database  
**Version:** 1.0  
**Status:** Ready for Development  
**Owner:** Backend / Data Engineering  
**Depends On:** Feature 1 (Data Ingestion Pipeline) — tables defined here are written to by the ingestion pipeline

---

## 1. Purpose & Background

### 1.1 What Problem Does This Solve?
Raw ARGO oceanographic data is deeply multi-dimensional — profiles indexed by float, cycle, depth, time, and geography. Without a properly designed storage layer, even simple queries like "show temperature near Sri Lanka last year" would require full table scans across hundreds of millions of rows.

Feature 2 defines and implements the central storage layer that every other FloatChat feature depends on. It is not just a set of tables — it is a carefully indexed, spatially enabled, query-optimized data platform that makes all downstream features fast, reliable, and scalable.

This feature covers:
- The complete relational schema for all oceanographic data
- All indexes, constraints, and spatial extensions
- Connection pooling for production-grade reliability
- A reusable data access layer (DAL) for safe, consistent querying
- A Redis caching layer for repeated query optimization
- Ocean basin reference data for named region queries
- Dataset versioning for safe re-ingestion

### 1.2 Relationship to Feature 1
Feature 1 (Ingestion Pipeline) writes data into the tables defined here. Feature 2 defines those tables and ensures they are optimized for reading. The two features are tightly coupled — the schema defined here must exactly match what Feature 1 writes.

### 1.3 Relationship to Downstream Features
Every feature that reads data — the NL Query Engine (Feature 4), Geospatial Exploration (Feature 7), Visualization (Feature 6), and Export (Feature 8) — queries the tables defined here. The indexes and query patterns defined in this PRD directly determine the performance of the entire platform.

---

## 2. Goals & Success Criteria

### 2.1 Goals
- Provide a storage layer that handles all FloatChat query patterns efficiently
- Enable spatial queries (nearest floats, region filtering) with sub-second response times
- Support time-range, depth, and variable-availability filtering without full table scans
- Be robust to re-ingestion — dataset versioning ensures no data loss on updates
- Abstract raw SQL behind a clean data access layer so application code never writes raw queries

### 2.2 Success Criteria

| Criterion | Target |
|---|---|
| Spatial query (floats within 300km of a point) | < 500ms at 10M profiles |
| Time range query (profiles in a 1-year window) | < 300ms at 10M profiles |
| Depth slice query (measurements between 100–500 dbar) | < 400ms at 100M measurements |
| Combined filter query (region + time + depth) | < 1s at 10M profiles |
| Cache hit response time | < 50ms |
| Connection pool exhaustion under load | Never — pool must queue, not reject |
| Re-ingestion of existing dataset | Zero data loss, zero duplicates |

---

## 3. User Stories

### 3.1 Query Engine (Internal Consumer)
- **US-01:** As the NL Query Engine, I need to query profiles by lat/lon radius so that I can answer "show floats near Sri Lanka."
- **US-02:** As the NL Query Engine, I need to query measurements by depth range so that I can answer "show deep profiles below 1000m."
- **US-03:** As the NL Query Engine, I need to filter by variable availability so that I can answer "show BGC floats with oxygen data."
- **US-04:** As the NL Query Engine, I need to filter by named ocean basin so that I can answer "show profiles in the Arabian Sea."

### 3.2 Data Manager (Admin)
- **US-05:** As a data manager, I need dataset versioning so that re-ingesting updated ARGO data doesn't destroy the previous version.
- **US-06:** As a data manager, I need to know which datasets are active vs archived so that I can manage what researchers see.

### 3.3 Platform (Reliability)
- **US-07:** As the platform, I need connection pooling so that concurrent API requests don't exhaust database connections.
- **US-08:** As the platform, I need query result caching so that repeated identical queries don't hit the database every time.

---

## 4. Functional Requirements

### 4.1 Core Schema

**FR-01 — `floats` Table**
One row per unique ARGO float, identified by `platform_number`. Must support:
- Lookup by `platform_number` (unique index)
- Filter by `float_type` (core / BGC / deep)
- Filter by deployment region (lat/lon)

Columns: `float_id` (PK), `platform_number` (unique, not null), `wmo_id`, `float_type`, `deployment_date`, `deployment_lat`, `deployment_lon`, `country`, `program`, `created_at`, `updated_at`

**FR-02 — `profiles` Table**
One row per float cycle. This is the most-queried table in the system. Must support:
- Spatial queries via PostGIS geography column `geom`
- Time-range queries via `timestamp`
- Join to `floats` via `float_id`
- Join to `measurements` via `profile_id`
- Unique constraint on `(platform_number, cycle_number)` to prevent duplicates

Columns: `profile_id` (PK), `float_id` (FK → floats), `platform_number`, `cycle_number`, `juld_raw`, `timestamp` (TIMESTAMPTZ), `timestamp_missing` (bool), `latitude`, `longitude`, `position_invalid` (bool), `geom` (GEOGRAPHY POINT), `data_mode`, `dataset_id` (FK → datasets), `created_at`, `updated_at`

**FR-03 — `measurements` Table**
One row per depth level within a profile. This is the largest table — expect 100M+ rows at scale. Must support:
- Depth filtering via `pressure`
- Variable availability filtering (e.g. `WHERE doxy_qc IS NOT NULL`)
- Join to `profiles` via `profile_id`
- Cascade delete when parent profile is deleted

Columns: `measurement_id` (PK), `profile_id` (FK → profiles, CASCADE DELETE), `pressure`, `temperature`, `salinity`, `dissolved_oxygen`, `chlorophyll`, `nitrate`, `ph`, `bbp700`, `downwelling_irradiance`, QC flag columns for each variable as SMALLINT (`pres_qc`, `temp_qc`, `psal_qc`, `doxy_qc`, `chla_qc`, `nitrate_qc`, `ph_qc`), `is_outlier` (bool)

**FR-04 — `datasets` Table**
One row per ingested file. Stores metadata about each dataset for discovery. Must support:
- Lookup by `dataset_id`
- Filter by `is_active` flag
- Spatial bounding box stored as `bbox` (GEOGRAPHY POLYGON)
- Variable list stored as `variable_list` (JSONB)
- Dataset versioning via `dataset_version` integer

Columns: `dataset_id` (PK), `name`, `source_filename`, `raw_file_path`, `ingestion_date`, `date_range_start`, `date_range_end`, `bbox` (GEOGRAPHY POLYGON), `float_count`, `profile_count`, `variable_list` (JSONB), `summary_text`, `is_active` (bool, default true), `dataset_version` (int, default 1), `created_at`

**FR-05 — `float_positions` Table**
Lightweight spatial index — one row per float cycle. Used by the map view and nearest-float queries. Intentionally denormalized for speed. Must support:
- Fast spatial queries via `geom`
- Unique constraint on `(platform_number, cycle_number)`

Columns: `position_id` (PK), `platform_number`, `cycle_number`, `timestamp`, `latitude`, `longitude`, `geom` (GEOGRAPHY POINT)

**FR-06 — `ingestion_jobs` Table**
Tracks every ingestion job. Defined fully in Feature 1 PRD. Included here for completeness — must be created in this schema migration.

**FR-07 — `ocean_regions` Reference Table**
Named ocean region polygons used for basin-based filtering. Must support:
- Lookup by `region_name` (e.g. "Arabian Sea", "Bay of Bengal")
- Spatial intersection with profile geometries via `geom`
- Hierarchical regions: ocean basins contain sub-regions

Columns: `region_id` (PK), `region_name` (unique), `region_type` (ocean / sea / bay / gulf), `parent_region_id` (self-referencing FK, nullable), `geom` (GEOGRAPHY POLYGON), `description`

**FR-08 — `dataset_versions` Table**
Audit log of dataset version history for rollback support.

Columns: `version_id` (PK), `dataset_id` (FK → datasets), `version_number`, `ingestion_date`, `profile_count`, `float_count`, `notes`, `created_at`

### 4.2 Indexes

**FR-09 — Spatial Indexes (GiST)**
- GiST index on `profiles.geom` — required for all spatial queries
- GiST index on `float_positions.geom` — required for map view queries
- GiST index on `ocean_regions.geom` — required for basin lookup queries
- GiST index on `datasets.bbox` — required for dataset spatial search

**FR-10 — Time Indexes (BRIN)**
- BRIN index on `profiles.timestamp` — BRIN is optimal for time-ordered append-only data
- BRIN index on `measurements.profile_id` is NOT appropriate — use B-tree instead

**FR-11 — B-tree Indexes**
- Index on `profiles.float_id` — for join performance
- Index on `profiles.dataset_id` — for dataset-scoped queries
- Index on `measurements.profile_id` — for join performance (most critical index in the system)
- Index on `measurements.pressure` — for depth filtering
- Index on `floats.platform_number` — already covered by unique constraint
- Index on `floats.float_type` — for BGC-only queries
- Composite index on `profiles(platform_number, cycle_number)` — already covered by unique constraint
- Composite index on `profiles(float_id, timestamp)` — for float time series queries

**FR-12 — Partial Indexes**
- Partial index on `profiles` where `position_invalid = FALSE` — spatial queries only care about valid positions
- Partial index on `profiles` where `timestamp_missing = FALSE` — time queries only care about profiles with timestamps
- Partial index on `datasets` where `is_active = TRUE` — most queries only touch active datasets

**FR-13 — Materialized Views**
Create the following materialized views for frequently needed aggregations:

- `mv_float_latest_position` — latest position per float (MAX cycle per platform_number). Used by the map view to show current float positions.
- `mv_dataset_stats` — per-dataset profile count, float count, and date range. Used by the metadata search.

Materialized views must be refreshed after each ingestion job completes. Refresh is triggered by the ingestion pipeline (Feature 1), not by this feature.

### 4.3 PostGIS Configuration

**FR-14 — Required PostgreSQL Extensions**
The following extensions must be enabled before any tables are created:
- `postgis` — core geospatial extension
- `postgis_topology` — topology support
- `pgcrypto` — for UUID generation
- `pg_trgm` — for fuzzy text search on region names

**FR-15 — Geography vs Geometry**
All spatial columns must use `GEOGRAPHY` type (not `GEOMETRY`). Geography uses spherical calculations which are accurate for ocean data spanning large distances. Geometry uses planar calculations which are inaccurate at global scale.

**FR-16 — SRID**
All geography columns must use SRID 4326 (WGS 84). This is the standard for GPS coordinates and ARGO float data.

**FR-17 — Ocean Basin Reference Data**
Load named ocean region polygons from the IHO Sea Areas dataset (available at `https://www.marineregions.org/downloads.php`) or Natural Earth. The `ocean_regions` table must be populated with at minimum these regions:

- Indian Ocean
- Arabian Sea
- Bay of Bengal
- Laccadive Sea
- Pacific Ocean (North)
- Pacific Ocean (South)
- Atlantic Ocean (North)
- Atlantic Ocean (South)
- Southern Ocean
- Arctic Ocean
- Mediterranean Sea
- Caribbean Sea
- Gulf of Mexico
- Red Sea
- Persian Gulf

Loading this reference data is done via a separate SQL seed file, not via Alembic migrations.

### 4.4 Connection Pooling

**FR-18 — PgBouncer Configuration**
Deploy PgBouncer as a connection pool between the application and PostgreSQL. Add it as a Docker service.

Configuration requirements:
- Pool mode: `transaction` — most efficient for short-lived API requests
- Max client connections: 100
- Default pool size: 20 per database
- Reserve pool size: 5
- PgBouncer listens on port `5433` (application connects to 5433, PgBouncer forwards to PostgreSQL on 5432)
- Application `DATABASE_URL` must point to PgBouncer port (5433), not PostgreSQL directly (5432)

**FR-19 — SQLAlchemy Connection Pool**
Even with PgBouncer, SQLAlchemy must be configured with its own pool:
- `pool_size`: 10
- `max_overflow`: 20
- `pool_pre_ping`: True — detect and discard stale connections
- `pool_recycle`: 3600 — recycle connections after 1 hour

### 4.5 Redis Caching Layer

**FR-20 — Query Result Cache**
Cache the results of NL query executions in Redis with a TTL of 5 minutes. Cache key must be a hash of the exact SQL query string. This prevents the same query from hitting PostgreSQL repeatedly within a short window.

Cache behavior:
- On cache hit: return cached result, skip database entirely
- On cache miss: execute query, store result in Redis with 5-minute TTL, return result
- Cache must be invalidated for a dataset when new data is ingested for that dataset

**FR-21 — Cache Key Design**
Cache keys must follow the pattern: `query_cache:{md5_hash_of_sql_string}`

Do not cache queries that return more than 10,000 rows — large result sets are not worth caching.

**FR-22 — Cache Invalidation**
When an ingestion job completes successfully, invalidate all cache keys associated with the affected dataset's spatial region. Use Redis key pattern deletion: `query_cache:*` flush on ingestion complete is acceptable for v1.

### 4.6 Data Access Layer

**FR-23 — `db.py` Module**
Build a reusable data access layer in `app/db/dal.py`. This module provides clean Python functions for every common query pattern. No other part of the application should write raw SQL — all queries go through this module.

Required functions:

- `get_profiles_by_radius(lat, lon, radius_meters, start_date, end_date, db)` — spatial + time filter
- `get_profiles_by_basin(region_name, start_date, end_date, db)` — named region filter
- `get_measurements_by_profile(profile_id, min_pressure, max_pressure, db)` — depth slice
- `get_float_latest_positions(db)` — reads from materialized view
- `get_active_datasets(db)` — returns all active datasets
- `get_dataset_by_id(dataset_id, db)` — single dataset lookup
- `search_floats_by_type(float_type, db)` — BGC vs core filter
- `get_profiles_with_variable(variable_name, db)` — variable availability filter
- `invalidate_query_cache(redis_client)` — clears Redis query cache

Each function must:
- Accept a SQLAlchemy `Session` as its last argument
- Return typed Python objects (SQLAlchemy model instances or plain dicts)
- Never expose raw SQL to the caller
- Log the query execution time using `structlog`

### 4.7 Dataset Versioning

**FR-24 — Version Tracking**
Every time a dataset is re-ingested, increment `datasets.dataset_version` and create a new record in `dataset_versions` with the previous version's stats. The previous version's data is not deleted — only `is_active` is toggled.

**FR-25 — Rollback Support**
An admin must be able to restore a previous dataset version by setting the old version's `is_active` back to `TRUE` and the current version's to `FALSE`. This is done via the admin API (Feature 10) — not in scope for Feature 2, but the schema must support it.

---

## 5. Non-Functional Requirements

### 5.1 Performance
- All queries used by the NL Query Engine must return in under 1 second at 10M profiles / 100M measurements
- Spatial queries must use the GiST index — never perform full table scans on `profiles`
- The BRIN index on `timestamp` must be used for all time-range queries
- Materialized views must be used for aggregation queries — never compute counts or stats on the fly in production

### 5.2 Scalability
- The `profiles` table must be designed with partitioning in mind. In v1, partitioning is not implemented but the schema must not prevent it from being added later. Do not use `SERIAL` primary keys on `profiles` — use `BIGSERIAL` to accommodate billions of rows.
- The `measurements` table must use `BIGSERIAL` for `measurement_id` — this table will exceed 1 billion rows at full ARGO scale.

### 5.3 Reliability
- PgBouncer must be configured to queue connections, never reject them
- SQLAlchemy `pool_pre_ping` must be enabled — stale connections must never cause silent query failures
- All schema changes must be done via Alembic migrations — never modify the schema manually in production

### 5.4 Security
- The application database user (`floatchat`) must have only `SELECT`, `INSERT`, `UPDATE`, `DELETE` privileges — never `CREATE`, `DROP`, or `ALTER`
- A separate read-only database user (`floatchat_readonly`) must be created for the NL Query Engine — it must have only `SELECT` privileges
- PgBouncer must use `scram-sha-256` authentication

---

## 6. Database Schema — Complete Table List

Tables must be created in this exact order due to foreign key dependencies:

1. `floats`
2. `datasets`
3. `profiles`
4. `measurements`
5. `float_positions`
6. `ingestion_jobs`
7. `ocean_regions`
8. `dataset_versions`

Materialized views are created after all tables:
9. `mv_float_latest_position`
10. `mv_dataset_stats`

---

## 7. Docker Services

### 7.1 PgBouncer Service
Add a `pgbouncer` service to `docker-compose.yml`. It must:
- Depend on the `postgres` service being healthy before starting
- Listen on port `5433`
- Be configured via `pgbouncer.ini` and `userlist.txt` files mounted as volumes
- Use transaction pooling mode

### 7.2 Updated Application Connection
After adding PgBouncer, update `.env.example` to point `DATABASE_URL` at port `5433` (PgBouncer) instead of `5432` (PostgreSQL directly).

---

## 8. Seed Data

### 8.1 Ocean Basin Polygons
Create a seed script at `backend/scripts/seed_ocean_regions.py`. This script:
- Reads ocean region polygon data from a GeoJSON or shapefile source
- Inserts records into the `ocean_regions` table
- Is idempotent — running it twice must not create duplicate regions
- Must be run manually after migrations, not automatically on startup

### 8.2 Read-Only Database User
Create a seed SQL script at `backend/scripts/create_readonly_user.sql` that creates the `floatchat_readonly` user with SELECT-only privileges on all tables.

---

## 9. Testing Requirements

### 9.1 Schema Tests
- Verify all 8 tables exist after running migrations
- Verify all GiST indexes exist on geometry columns
- Verify BRIN index exists on `profiles.timestamp`
- Verify unique constraints exist on `profiles(platform_number, cycle_number)` and `float_positions(platform_number, cycle_number)`
- Verify CASCADE DELETE works: deleting a profile must delete its measurements

### 9.2 DAL Tests
- Test `get_profiles_by_radius` returns only profiles within the specified radius
- Test `get_profiles_by_basin` returns profiles within the named region polygon
- Test `get_measurements_by_profile` returns only measurements within the depth range
- Test `get_float_latest_positions` reads from the materialized view correctly

### 9.3 Cache Tests
- Test that a repeated query returns from cache on second call
- Test that cache is invalidated after ingestion
- Test that queries returning over 10,000 rows are not cached

### 9.4 Connection Pool Tests
- Test that 50 concurrent connections are handled without errors
- Test that a stale connection is detected and replaced via `pool_pre_ping`

---

## 10. Dependencies & Prerequisites

| Dependency | Reason | Must Be Ready Before |
|---|---|---|
| Feature 1 schema (tables) | Feature 2 extends Feature 1's migration | Day 1 |
| Docker Compose (Phase 1) | PostgreSQL and Redis must be running | Day 1 |
| PostGIS enabled in PostgreSQL | All geometry columns depend on it | Before migrations |
| PgBouncer Docker image | Connection pooling service | Before API testing |
| Ocean basin GeoJSON/shapefile | Seed data for `ocean_regions` | Before integration testing |

---

## 11. Out of Scope for v1.0

- Table partitioning on `profiles` by year (schema supports it, not implemented)
- Automated materialized view refresh scheduling (triggered manually or by ingestion)
- Full-text search on `summary_text` (deferred to Feature 3)
- Multi-tenant data isolation
- Read replicas for horizontal read scaling

---

## 12. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| Q1 | Which ocean basin polygon source should be used — IHO Sea Areas or Natural Earth? IHO is more authoritative but requires registration to download. | Data Team | Before seed script |
| Q2 | Should PgBouncer be added to docker-compose for local dev, or only for production? Running it locally adds complexity but ensures dev/prod parity. | Infra | Before Phase 2 dev start |
| Q3 | Should materialized view refresh be triggered by the ingestion pipeline (Feature 1) or by a scheduled cron? | Backend | Before Feature 1 integration |
| Q4 | What is the expected maximum number of concurrent API users? This determines PgBouncer pool size settings. | Product | Before deploy |
