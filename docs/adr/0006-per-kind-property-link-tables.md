# Property dimension and link tables are per core unit-kind, not shared

Each core unit-kind owns its property tables. For generators that is
`core.generator_properties` (the normalized (name, value) dimension) and
`core.generator_units_properties` (the unit → property link table, FK'd to
both core.generators and core.generator_properties). Storages have their own
`storage_properties` / `storage_units_properties` (issue #7). Neither
dimension nor links are shared across unit-kinds.

## Context

Core split into `core.generators` and `core.storages`, each with its own
SERIAL `unit_id` starting at 1. Issue #8 (generators) and its storage
counterpart transfer normalized properties from staging into core. The
earlier ADR 0005 named a single shared `properties` / `units_properties`,
with the link table's `unit_id` carrying *no* FK because it was shared
across both unit tables. Once storages also link properties, a shared
`unit_id` column becomes ambiguous: generator #5 and storage #5 are
indistinguishable, so link integrity could only ever be enforced by the
application, never by the schema.

## Decision

Three core tables exist per generator kind today — `core.generators` (units),
`core.generator_properties` (normalized property dictionary, prop_id / name /
value), and `core.generator_units_properties` (links, FK unit_id →
core.generators and prop_id → core.generator_properties). The storage kind has `core.storages`, `core.storage_properties` and
`core.storage_units_properties`, under the same pattern. The
staging per-source link tables stay named `{source}_units_properties` and
keep the `<source>_<reference_id>` or `syn_<hash>` staging unit ids, since
each staging source is a single unit kind.

## Consequences

- Link integrity is enforced by foreign keys instead of application care
  ("#8 owns link integrity" disappears).
- Property queries are unambiguous per unit kind; a storage and a generator
  may carry the same serial prop_id / unit_id without colliding.
- Because the dimension is per-kind too, `properties` (prop_id) sequences
  start fresh per unit kind; (name, value) pairs are deduplicated within a
  kind, not across kinds.
- Supersedes the shared-table naming part of ADR 0005; the rest of ADR 0005
  (whitelist decomposition, annotations as property links, secondary
  attributes surviving through staging/core) is unchanged.