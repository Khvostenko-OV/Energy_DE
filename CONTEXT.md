# Renewable Energy Installations in Germany

Geospatial registry of renewable energy generation and storage units in Germany, enriched with administrative and maritime boundaries for analyzing installed capacity by energy source and region. Rows move through four PostGIS layers — raw (versioned datalake), staging (enriched + quality-gated), core (consolidated, serial-keyed), marts (active-unit pivots).

## Language

### Units

**Unit**:
A single renewable energy installation in the registry, either a generator or a storage unit. Every unit has a stable identity in the staging layer derived from its source dataset.
_Avoid_: Plant, system, installation, record

**Generator**:
A unit that produces electricity: Bio, Gas, Hydro, Solar, or Wind.
_Avoid_: Power plant

**Storage**:
A unit that stores energy (Battery, Pumped storage, Hydrogen storage) rather than producing it.
_Avoid_: Storage unit, Energy storage

**Energy source**:
The canonical type of a unit: Bio, Gas, Hydro, Solar, Wind, or Storage. Canonicalized from the varied labels in the source files (e.g. "Bioenergy", "Solar Energy", "Energy Storage").
_Avoid_: Bioenergy, Solar Energy, Wind Energy, Hydropower (as values — keep only as original source attributes)

**Storage type**:
The technology class of a storage unit: Battery, Pumped storage, Hydrogen storage.

**Installed capacity**:
Nameplate output of a generator, in kilowatts (kW).
_Avoid_: Nominal power, nameplate rating

**Storage capacity**:
Usable energy storage capacity of a storage unit, in kilowatt-hours (kWh).

**Commissioning date**:
The date a unit was put into operation.

**Decommissioning date**:
The date a unit was taken out of operation; null means the unit is still active.

**Active unit**:
A unit whose decommissioning date is null or in the future. Only active units contribute to mart pivots.

**Geo accuracy**:
The precision of a unit's coordinates: 1 = exact location of the facility, 2 = centre of the municipality (imprecise). Geo accuracy 2 is a plain column, never a quality flag.
_Avoid_: Accuracy, coordinate precision

**Reference ID**:
The identifier of the record in its original source dataset. Unique within and across all source files. Used to build the staging unit_id, not the core identity.

**Reference date**:
Full-source timestamp of a record. In incremental load it is the freshness gate: a row updates core only when its reference_date is fresher than the stored row's.

**Synthetic identity**:
A generated staging unit_id for units lacking a reference ID (39 solar rows), derived from the unit's own attributes and recognized by its hash prefix. Staging-only: core replaces it with a serial key and never flags it.

### Geography

**Boundaries**:
The single level-coded `raw.boundaries` table of administrative and maritime polygons (0 country outline, 1 regions + EEZ, 2 districts, 3 municipalities) used to assign each unit its region, district, and municipality by spatial join.

**Region**:
A Bundesland (federal state) or, for offshore units, the sea/EEZ area they fall in.
_Avoid_: State, Land

**District**:
A Landkreis (administrative district).

**Municipality**:
A Gemeinde (municipality).

**Offshore**:
A wind unit located at sea, enriched against the EEZ region layer rather than onshore boundaries.

### Data stages

**Raw version**:
A dated snapshot table `raw.<source>_<YYYYMMDD>_<n>` produced by one extract load. Every load appends a new version; versions are never dropped or overwritten.

**Load signature**:
The `(filename, filesize, modified_at)` triplet recorded in `loaded_files`. A file whose signature is already logged is skipped on extract unless forced with `-f`; `-f` appends another raw version and log row.

**Raw**:
The extract layer: versioned per-source tables with secondary attributes folded into a `secondary_attributes` jsonb column, plus the `loaded_files` log and the level-coded `boundaries` table.

**Staging**:
The transform layer: raw rows enriched with region, district, and municipality via spatial joins, keyed by a natural `unit_id`, quality-gated by `bad_quality`, and with secondary attributes decomposed into normalized properties.

**Core**:
The consolidated layer: `generators` and `storages`, each unit appearing exactly once, holding a serial surrogate key and collision flags. Core rows are updated in place and never deleted.

**Marts**:
The aggregation layer: three Postgres materialized views (installation counts, generation capacity, storage capacity) at region grain, computed from active units only.

**Properties**:
Normalized (name, value) attribute pairs of a unit, linked many-to-many through `units_properties`. Also the home of quality annotations (`bad_quality`, `collision`, `close_to`).
_Avoid_: Parameters

**Secondary attributes**:
The raw/staging jsonb column holding a unit's source attributes that have no fixed column. Decomposed into `properties` in staging.
_Avoid_: Properties (column name — now a table, not a column)

### Quality

**Bad quality**:
A staging flag on a record failing a transform-level check (installed_capacity ≤ 0 or null; decommissioning_date before commissioning_date; coordinates conflicting with geometry; region null). The failing record is excluded from core, and a `bad_quality` property link carries the newline-joined descriptions.
_Avoid_: Error, anomaly

**Collision**:
A core flag on a unit flagged by a load-level check: two `geo_accuracy = 1` units less than 10 m apart, an onshore-labelled unit inside the sea, or a storage with `storage_capacity ≤ 0` or null. Collision rows remain in core, annotated by property links (`collision`, and `close_to` naming the neighbouring unit).
_Avoid_: Issue, error, anomaly

**Close-to**:
The property link value naming the other unit's id when a unit is part of a close-location collision.