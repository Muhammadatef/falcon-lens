-- 001: verdicts + evidence (worker-owned). Idempotent: applied by the worker at startup.
-- `verdicts` shape is fixed by docs/CONTRACTS.md (Internal messages): the API reads
-- `SELECT doc FROM verdicts WHERE verdict_id = $1`. Extra columns must stay nullable.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id text PRIMARY KEY,
    doc        jsonb NOT NULL,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS verdicts_created_at_idx ON verdicts (created_at);

-- One row per evidence item of a final verdict. `observed` is the contract's small structured
-- value (defanged, never raw page or message text).
CREATE TABLE IF NOT EXISTS evidence (
    verdict_id  text NOT NULL REFERENCES verdicts (verdict_id) ON DELETE CASCADE,
    evidence_id text NOT NULL,
    signal      text NOT NULL,
    family      text NOT NULL,
    tier        text NOT NULL,
    weight      double precision NOT NULL,
    polarity    text NOT NULL,
    hard_rule   text,
    source      text NOT NULL,
    confidence  double precision NOT NULL,
    error       text,
    observed    jsonb,
    latency_ms  integer,
    PRIMARY KEY (verdict_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS evidence_signal_idx ON evidence (signal);

INSERT INTO schema_migrations (version) VALUES ('001_verdicts_evidence') ON CONFLICT DO NOTHING;
