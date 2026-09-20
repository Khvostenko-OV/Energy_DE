-- Read-only DB role for the Streamlit viz service (issue #28).
--
-- One idempotent seam, used by both sides of the stack:
--   * compose: mounted into the db container at
--     /docker-entrypoint-initdb.d/99-viz-reader.sql, so a fresh db volume
--     provisions the role on the first `up` (the issue #13 fresh-start cycle
--     picks it up automatically — no extra step);
--   * dev host:  psql -U etl -d energy_de -f docker/viz_reader.sql
--     (run as the role that owns the pipeline schemas, e.g. the DATABASE_URL
--     user on the dev host).
--
-- Run as the pipeline role (the compose POSTGRES_USER — etl by default — or
-- the dev DATABASE_URL user).  That role creates the core / service / marts
-- objects, so ALTER DEFAULT PRIVILEGES without FOR ROLE / IN SCHEMA governs
-- exactly the right future objects:
--   * schema-less defaults apply to every schema in this database — including
--     the marts schema and its materialized views, which do not exist until
--     after the first pipeline pass — so nothing here has to pre-create (and
--     thereby own) a schema the pipeline would otherwise own;
--   * grants survive pipeline drops/recreates of the core tables (defaults
--     re-fire at CREATE time) and REFRESHes of the marts views (a refresh
--     keeps the matview's existing ACL).
--
-- Idempotent: safe to re-run any number of times.
--
-- viz_reader never receives INSERT/UPDATE/DELETE.  Default SELECT on all
-- tables/sequences plus default USAGE on all schemas is intentionally a
-- superset that also covers raw/staging reads — harmless for a read-only
-- role, and it avoids coupling this file to which schemas exist when it runs.

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'viz_reader') THEN
        CREATE ROLE viz_reader LOGIN PASSWORD 'viz';
    ELSE
        -- Pre-existing role: keep it usable for the app but never clobber a
        -- password an operator may have set elsewhere.
        ALTER ROLE viz_reader LOGIN;
    END IF;
END
$$;

-- Default privileges (for the current / pipeline role):
--   * future objects (tables, materialized views, sequences) are SELECTable
--     by viz_reader,
--   * future schemas (e.g. marts, created by the marts stage) are USAGE-able,
--   * both apply to core / service / marts wherever they appear.
ALTER DEFAULT PRIVILEGES GRANT USAGE ON SCHEMAS TO viz_reader;
ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO viz_reader;
ALTER DEFAULT PRIVILEGES GRANT SELECT ON SEQUENCES TO viz_reader;

-- Objects that already exist when this runs (a host that provisions after a
-- pipeline pass): identical grants, scoped to the three schemas the app reads.
-- Schemas that do not exist yet are skipped — the defaults above cover their
-- future objects.
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['core', 'service', 'marts']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO viz_reader', s);
            EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO viz_reader', s);
            EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO viz_reader', s);
        END IF;
    END LOOP;
END
$$;