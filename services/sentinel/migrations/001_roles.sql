-- Sentinel Postgres roles (run once as a superuser / the DB owner), then start the sentinel with
--   DATABASE_URL=postgresql://falcon_sentinel:...@postgres/falcon          (service role, unprivileged)
--   FL_DATABASE_OWNER_URL=postgresql://falcon:...@postgres/falcon          (owner role: schema + grants only)
--   FL_SENTINEL_DB_ROLE=falcon_sentinel
-- At start-up the sentinel connects as the OWNER only to run the DDL (falcon_sentinel/db.py DDL) and db.GRANTS.
-- The service role then has INSERT/SELECT on audit_log and nothing else on it: it cannot UPDATE, DELETE, TRUNCATE,
-- ALTER or DROP the table, and it cannot disable the append-only triggers because it does not own the table.
-- Triggers (owner-created): audit_log_immutable (row UPDATE/DELETE) and audit_log_no_truncate (statement TRUNCATE).
-- LangGraph checkpoint tables are created by the service role (hence GRANT CREATE ON SCHEMA public in db.GRANTS).
CREATE ROLE falcon_sentinel LOGIN PASSWORD :'sentinel_password';  -- psql -v sentinel_password=...
GRANT CONNECT ON DATABASE falcon TO falcon_sentinel;
