# Marts are stored wide pivot tables at region grain

Marts are three stored wide pivot tables as the spec lists them: installation counts, generation capacity, and storage capacity — at region grain, with energy-source (generation) and storage-type (storage) as columns. Materialized views for capacity-by-region and capacity-by-source layer on top of them.

Consequence: the stored shape cannot answer date-range or decommissioned-inclusion queries, so the future dashboard ticket must aggregate from core tables with filters rather than read the pivots. Rejected a single narrow unit-grain fact mart serving all rollups as over-flexible versus the spec's literal pivot tables.