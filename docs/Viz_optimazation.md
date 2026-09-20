# Performance optimization of rendering Map and Header

## Using pandas

## 1. Fetching data
1. Fetch active units once from core tables. 2 queries - from core.generators and core.storages.
Something like:

df_gen = pd.read_sql(f"""
    SELECT energy_source, installed_capacity, commissioning_date, decommissioning_date, 
    latitude, longitude, {area_column} as name
    FROM core.generators
    WHERE energy_source = ANY(:sources)
    {f'AND {area_column} = ANY(:area_names)' if area_names else ''}
    AND {ACTIVE_UNIT_PREDICATE}
""", engine) if storages != ('storage',) 
else df_gen = pd.DataFrame(columns=['unit_id', 'energy_source', 'installed_capacity', 'commissioning_date', 'decommissioning_date', {area_column}])

df_stor = pd.read_sql("""
    SELECT energy_source, installed_capacity, commissioning_date, decommissioning_date, 
    latitude, longitude, {area_column} as name
    FROM core.storages
    WHERE energy_source = ANY(:sources)
    {f'AND {area_column} = ANY(:area_names)' if area_names else ''}
    AND {ACTIVE_UNIT_PREDICATE}
""", engine) if 'storage' in sources
else df_stor = pd.DataFrame(columns=['unit_id', 'energy_source', 'installed_capacity', 'commissioning_date', 'decommissioning_date', {area_column}])

units = pd.concat([df_gen, df_stor], ignore_index=True)

2. Add column "tooltip"
3. Fetching all current level areas (name, area) with  geojson to boundaries df
4. Use units and boundaries for all steps.
5. Area layer includes boundaries of all areas and filling of selected areas
6. Area's tooltip includes name for all areas + total capacity, units count for selected areas

## 2. Choropleth
For building choropleth we don't need spatial join. We just make boundaries left join with units aggregated by name
