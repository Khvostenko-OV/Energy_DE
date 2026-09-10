# Renewable Energy Installations in Germany

Geospatial registry of renewable energy generation and storage units in Germany, enriched with administrative and maritime boundaries for analyzing installed capacity by energy source, region, and commissioning date.

## Language

### Units

**Unit**:
A single renewable energy installation in the registry, either a generator or a storage unit. Every unit has a stable identity derived from its source dataset.
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

**Commissioning date**:
The date a unit was put into operation.

**Decommissioning date**:
The date a unit was taken out of operation; null means the unit is still active.

**Active unit**:
A unit whose decommissioning date is null or in the future. Only active units contribute to mart capacity and counts.

**Geo accuracy**:
The precision of a unit's coordinates: 1 = exact location of the facility, 2 = centre of the municipality (imprecise).
_Avoid_: Accuracy, coordinate precision

**Reference ID**:
The identifier of the record in its original source dataset. Unique within and across all source files.

### Geography

**Boundaries**:
Administrative and maritime polygons (country, regions + EEZ, districts, municipalities) used to assign each unit its region, district, and municipality by spatial join.

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

**Raw**:
The extract layer: per-source tables holding each source file's records as loaded, secondary attributes folded into a properties dictionary.

**Staging**:
The transform layer: raw rows enriched with region, district, and municipality via spatial joins, keyed by the unit's natural identity and with secondary attributes decomposed into parameters.

**Core**:
The consolidated layer: `generators` and `storages`, each unit appearing exactly once, holding the surrogate identity and quality flags.

**Marts**:
The aggregation layer: stored pivot tables of installation counts and capacity by region.

**Parameters**:
Secondary attributes of a unit decomposed into normalized (name, value) pairs, linked many-to-many through units-parameters.

### Quality

**Collision**:
A unit flagged by a quality check — e.g. an onshore-labelled unit inside the sea, an imprecise (`geo_accuracy = 2`) location, a synthetic identity, or a same-location co-occurrence.
_Avoid_: Issue, error, anomaly

**Synthetic identity**:
A generated fallback identity for units lacking a reference ID, derived from the unit's own attributes and flagged by a quality check.