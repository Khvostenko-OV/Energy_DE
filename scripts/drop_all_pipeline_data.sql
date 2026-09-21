-- Drop every table, view, materialized view, and sequence from the pipeline
-- schemas: raw, stage, core, marts, service.
--
-- A clean-slate reset for the ETL stack: after this runs, `python -m etl
-- run-all` rebuilds all five schemas from the raw data.  The schemas
-- themselves are left in place — they keep their ACLs (including the
-- viz_reader grants from docker/viz_reader.sql) — only their contents go.
--
-- Order is dependency-safe: materialized views and views are dropped before
-- the tables they read, tables before the sequences their serials own (those
-- go with the table), and every DROP uses CASCADE for foreign keys and other
-- dependents.  Idempotent: re-running on an already-empty schema is a no-op.
--
-- Usage (dev host or compose db):
--   psql "$DATABASE_URL" -f scripts/drop_all_pipeline_data.sql
--   docker compose exec -T db psql -U etl -d energy_de -f \
--     /app/scripts/drop_all_pipeline_data.sql   (scripts/ mounted per your setup)

\set ON_ERROR_STOP on

DO $$
DECLARE
    r  record;
    sq text;
BEGIN
    FOR r IN
        SELECT
            c.relkind,
            CASE c.relkind
                WHEN 'm' THEN 'MATERIALIZED VIEW'
                WHEN 'v' THEN 'VIEW'
                WHEN 'r' THEN 'TABLE'
                WHEN 'p' THEN 'TABLE'
                WHEN 'S' THEN 'SEQUENCE'
            END AS kind,
            quote_ident(n.nspname) || '.' || quote_ident(c.relname) AS qualified
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY (ARRAY['raw', 'stage', 'core', 'marts', 'service'])
          AND c.relkind IN ('m', 'v', 'r', 'p', 'S')
          -- a sequence OWNED BY a serial/identity column is an auto-dependency
          -- of its table and vanishes with it; drop only standalone ones.
          AND NOT (c.relkind = 'S' AND EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass
                AND d.objid = c.oid
                AND d.deptype = 'a'
          ))
        ORDER BY
            -- dependents first, so a DROP ... CASCADE never pre-eats a later
            -- target: partition children before the parent that owns them,
            -- then matviews/views before the tables they read, and tables
            -- before the sequences their serial columns own.
            c.relispartition DESC,
            CASE c.relkind WHEN 'm' THEN 1 WHEN 'v' THEN 2 WHEN 'r' THEN 3
                           WHEN 'p' THEN 3 ELSE 4 END,
            c.relname
    LOOP
        sq := format('DROP %s %s CASCADE', r.kind, r.qualified);
        RAISE NOTICE '%', sq;
        EXECUTE sq;
    END LOOP;
END
$$;

-- A dropped table's owned sequences vanish with it; only sequences without an
-- owning column could remain, and the loop above already dropped them.