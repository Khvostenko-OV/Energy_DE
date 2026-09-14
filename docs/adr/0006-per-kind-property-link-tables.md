# Property link tables are per core unit-kind, not shared

Per-unit-kind link tables `core.generator_properties` and (for storages)
`core.storage_properties` carry each core unit table's normalized property
links, each with a real FK to its own unit table. `core.properties` stays a
single shared dimension of (name, value) pairs.

## Context

Core split into `core.generators` and `core.storages`, each with its own
SERIAL `unit_id` starting at 1. Issue #8 (generators) and its storage
counterpart transfer normalized properties from staging into core. The
earlier ADR 0005 named a single shared `properties` / `units_properties`
link table, with `units_properties.unit_id` carrying *no* FK because it was
shared across both unit tables. Once storages also link properties, a shared
`unit_id` column becomes ambiguous: generator #5 and storage #5 are
indistinguishable, so link integrity could only ever be enforced by the
application, never by the schema.

## Decision

Each core unit-kind table gets its own property link table, FK'd to it:
`core.generator_properties` (unit_id → core.generators, prop_id →
core.properties) now, `core.storage_properties` when `core.storages` lands
(issue #7). The staging per-source link tables stay named
`{source}_units_properties` and keep the `<source>_<reference_id>` or
`syn_<hash>` staging unit ids, since each staging source is a single unit
kind.

## Consequences

- Link integrity is enforced by foreign keys instead of application care
  ("#8 owns link integrity" disappears).
- Property queries are unambiguous per unit kind; a storage and a generator
  may carry the same serial id without colliding.
- The `properties` dimension remains shared, so (name, value) pairs are
  deduplicated across generators and storages.
- Supersedes the shared-table naming part of ADR 0005; the rest of ADR 0005
  (whitelist decomposition, annotations as property links, secondary
  attributes surviving through staging/core) is unchanged.