-- Sentinel hunt mode tables (docs/design/HUNTER.md section 3). Idempotent; run by the table OWNER at start-up
-- (falcon_sentinel/hunt/store.py), like the DDL in falcon_sentinel/db.py. The service role gets the grants below.
-- `domain` is the live A-label registrable name: it is stored only here, never in the repo, logs or metrics.
-- Every projection that leaves the Sentinel uses domain_defanged + domain_sha256.
CREATE TABLE IF NOT EXISTS hunt_candidates (
  candidate_id text PRIMARY KEY,
  domain text NOT NULL UNIQUE,
  domain_sha256 text NOT NULL,
  brand_id text NOT NULL,
  discovery text NOT NULL,
  permutation_kind text,
  reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  provenance jsonb NOT NULL,
  first_seen timestamptz NOT NULL,
  upstream_seen timestamptz,
  prescore integer NOT NULL CHECK (prescore BETWEEN 0 AND 100),
  status text NOT NULL CHECK (status IN ('new','unregistered','queued','submitted','confirmed','cleared',
                                         'already_known','skipped_quota','error')),
  verdict_id text UNIQUE,
  verdict text,
  verdict_at timestamptz,
  incident_id text,
  time_to_detection_s double precision,
  time_to_detection_basis text,
  checked_at timestamptz,
  first_user_seen timestamptz,
  scheme text NOT NULL DEFAULT 'https' CHECK (scheme IN ('https','http')),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hunt_candidates_status_idx ON hunt_candidates (status, prescore DESC);
CREATE INDEX IF NOT EXISTS hunt_candidates_brand_idx ON hunt_candidates (brand_id);

-- Per-source cursor, backoff and health (restart-safe: the scheduler resumes from here).
CREATE TABLE IF NOT EXISTS hunt_source_state (
  source_id text PRIMARY KEY,
  cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
  backoff_until timestamptz,
  failures integer NOT NULL DEFAULT 0,
  last_success timestamptz,
  last_error text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Submission quota buckets: one row per (quota, window start), e.g. ('submit_hour', 2026-11-24T20:00Z).
CREATE TABLE IF NOT EXISTS hunt_quota (
  quota text NOT NULL,
  window_start timestamptz NOT NULL,
  used integer NOT NULL DEFAULT 0,
  PRIMARY KEY (quota, window_start)
);

-- Cycle log (one row per cycle; outcome ok | paused | disabled | quota | error | locked).
CREATE TABLE IF NOT EXISTS hunt_cycles (
  cycle_id text PRIMARY KEY,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  outcome text,
  stats jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS hunt_cycles_started_idx ON hunt_cycles (started_at DESC);
