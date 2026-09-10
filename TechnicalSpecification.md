# Project. Renewable Energy Installations in Germany

## Project objectives
1. Visualization of geodata showing the locations of renewable energy generation facilities in Germany. 
2. ETL pipeline that integrates geospatial data on renewable energy installations in Germany 
with administrative and maritime boundaries. The data is enriched using spatial joins and stored in PostGIS.
3. Interactive dashboard in Metabase to analyze capacity, energy types, and regional distribution.
Aggregation total installed capacity by region (Bundesland / Landkreis / Gemeinde), 
by source type (Bio, Water, Solar, Wind, Gas), by date of commissioning

## Data description
### Energy installations. Source https://zenodo.org/records/20716459  
| Dataset              | Description                                                    | Filename                             | Type         |
|----------------------|----------------------------------------------------------------|--------------------------------------|--------------|
| Bioenergy            | Locations of power generation units of bioenergy systems       | Bioenergy_V20250101.gpkg             | Point        |
| Cogeneration Units   | Locations of cogeneration units connected to bioenergy systems | Cogeneration_Units_V20250101.gpkg    | Point        |
| Energy Storage       | Locations of energy storage units greater than 100 kW          | Energy_Storage_V20250101.gpkg        | Point        |
| Gas Production       | Location of gas production systems                             | Gas_Producer_V20250101.gpkg          | Point        |
| Hydropower           | Locations of hydropower systems                                | Hydropower_V20250101.gpkg            | Point        |
| Solarenergy Polygons | Polygons of solar energy systems                               | Solar_Energy_Polygons_V20250101.gpkg | Multipolygon |
| Solar Energy         | Locations of solar energy systems                              | Solar_Energy_V20250101.gpkg          | Point        |
| Wind Energy          | Locations of wind turbines                                     | Wind_Energy_V20250101.gpkg           | Point        |

### Germany administrative boundaries (incl. Offshore zones). Source https://www.quickmaptools.com https://www.marineregions.org
| Dataset        | Description                                              | Filename               | Type         |
|----------------|----------------------------------------------------------|------------------------|--------------|
| State boundary | Germany state boundary                                   | germany_boundary.gpkg  | Multipolygon |
| Regions + EEZ  | Regions boundaries + Germany EEZ boundaries (Bundesland) | germany_regions.gpkg   | Multipolygon |
| Districts      | District boundaries (Landkreis + Kreisfreie Stadt)       | germany_districts.gpkg | Multipolygon |
| Municipalities | Municipalities boundaries (Gemeinde)                     | germany_munis.gpkg     | Multipolygon |

## ETL-pipeline description
### 1. Extract
- Read .gpkg files to Geopandas' dataframes (2 type of dfs Units, Boundaries).
- Type casting (dates)
- Drop duplicates
- Convert secondary properties to dictionary, place it to column 'properties'
- Save to PostGIS datalake (Units tables, storage table)
### 2. Transform
- Add primary keys
- Enrich tables with columns 'region', 'district', 'municipality' (spatial join with Boundaries)
- Decompose properties dictionaries to normalized tables (many-to-many)
- Save tables to PostGIS
### 3. Load
#### First load
- Create tables **generators**, **storages**
- Insert into **generators** data from Units tables bio, gas, hydro, solar, wind
- Insert into **storages** data from Units table storage
- Transfer primary keys for dimension tables
- Create indexes
- Quality check. Look up for collisions (same location, onshore unit in the sea, etc), add flags and notes

#### Incremental load 
- Append-or-update **generators** table with records from Units tables
- Append-or-update **storages** table with records from Units table storage
- Transfer primary keys for dimension tables
- Quality check. Look up for collisions (same location, onshore unit in the sea, etc), add flags and notes

### Creating Materialized Views
- Capacity by region
- Capacity by energy source
- Generation capacity pivot table (region / energy source)
- Storage capacity pivot table (region / energy source)

## Serving
### 1. Visualization
- Metabase dashboard with map
- Checkboxes to show units of different type (Bio, Hydro, Wind, Solar, Gas, Storage)
- Checkbox to show/hide decommissioned units
- Multiselectors to include different regions, districts, municipalities
- Calendars to choose commissioning/decommissioning date (from/to)
- Charts showing the total installed capacity according to the selected unit types

### 2. Admin panel (auth)
- Correcting records (CRUD)
- Resolving collisions

### 3. API (auth)
- Quering records from BD (Exel file)
- Quering aggregated data from BD (JSON)

## Data layers
### 1. Raw
#### Units tables: bio, gas, hydro, solar, wind
| Column                 | Data type | Description                                       |
|------------------------|-----------|---------------------------------------------------|
| energy_source          | str       | Type of unit (Bio, Gas, Hydro, Solar, Wind)       |
| installed_capacity     | float     | Kilowatt (kW)                                     |
| commissioning_date     | date      | Commissioning date of the system                  |
| decommissioning_date   | date      | Decommissioning date of the system                |
| x_coordinates          | float     | Longitude WGS-84                                  |
| y_coordinates          | float     | Latitude WGS-84                                   |
| geo_accuracy           | int       | 1/2                                               |
| reference_id           | str       | Reference id of the record in the original source |
| reference_date         | date      | Timestamp of the record in the original source    |
| geometry               | point     | WGS-84                                            |
| properties             | json      | Dictionary of secondary attributes                |

#### Units table: storage
| Column               | Data type | Description                                        |
|----------------------|-----------|----------------------------------------------------|
| energy_source        | str       | Type of unit (Storage)                             |
| installed_capacity   | float     | Kilowatt (kW)                                      |
| commissioning_date   | date      | Commissioning date of the system                   |
| decommissioning_date | date      | Decommissioning date of the system                 |
| storage_type         | str       | Type of energy storage system                      |
| storage_capacity     | float     | Usable energy storage capacity Kilowatt-hour (kWh) |
| x_coordinates        | float     | Longitude WGS-84                                   |
| y_coordinates        | float     | Latitude WGS-84                                    |
| geo_accuracy         | int       | 1/2                                                |
| reference_id         | str       | Reference id of the record in the original source  |
| reference_date       | date      | Timestamp of the record in the original source     |
| geometry             | point     | WGS-84                                             |
| properties           | json      | Dictionary of secondary attributes                 |

### 2. Staging
#### Units tables: bio, gas, hydro, solar, wind
| Column               | Data type | Description                                       |
|----------------------|-----------|---------------------------------------------------|
| unit_id              | str       | pk                                                |
| energy_source        | str       | Type of unit (Bio, Gas, Hydro, Solar, Wind)       |
| installed_capacity   | float     | Kilowatt (kW)                                     |
| commissioning_date   | date      | Commissioning date of the system                  |
| decommissioning_date | date      | Decommissioning date of the system                |
| geometry             | point     | WGS-84                                            |
| geo_accuracy         | int       | 1/2                                               |
| reference_date       | date      | Timestamp of the record in the original source    |
| reference_id         | str       | Reference id of the record in the original source |
| country_iso          | str       | DEU                                               |
| region               | str       | Bundesland / Sea                                  |
| district             | str       | Landkreis                                         |
| municipality         | str       | Gemeinde                                          |

#### Units table: storage
| Column               | Data type | Description                                        |
|----------------------|-----------|----------------------------------------------------|
| unit_id              | str       | pk                                                 |
| storage_type         | str       | Type of energy storage system                      |
| storage_capacity     | str       | Usable energy storage capacity Kilowatt-hour (kWh) |
| installed_capacity   | float     | Kilowatt (kW)                                      |
| commissioning_date   | date      | Commissioning date of the system                   |
| decommissioning_date | date      | Decommissioning date of the system                 |
| geometry             | point     | WGS-84                                             |
| geo_accuracy         | int       | 1/2                                                |
| reference_id         | str       | Reference id of the record in the original source  |
| reference_date       | date      | Timestamp of the record in the original source     |
| country_iso          | str       | DEU                                                |
| region               | str       | Bundesland / Sea                                   |
| district             | str       | Landkreis                                          |
| municipality         | str       | Gemeinde                                           |

### Dimension tables (normalized, one set for each Unit table)
#### parameters
| Column        | Data type |
|---------------|-----------|
| param_id      | int pk    |
| name          | str       |
| value         | str       |
| (name, value) | unique    |
#### units_parameters
| Column              | Data type |
|---------------------|-----------|
| unit_id             | int fk    |
| param_id            | int fk    |
| (unit_id, param_id) | pk        |

## 3. Core
### generators
| Column               | Data type | Description                                       |
|----------------------|-----------|---------------------------------------------------|
| unit_id              | int       | pk                                                |
| energy_source        | str       | Type of unit (Bio, Gas, Hydro, Solar, Wind)       |
| installed_capacity   | float     | Kilowatt (kW)                                     |
| commissioning_date   | date      | Commissioning date of the system                  |
| decommissioning_date | date      | Decommissioning date of the system                |
| geometry             | point     | WGS-84                                            |
| geo_accuracy         | int       | 1/2                                               |
| reference_date       | date      | Timestamp of the record in the original source    |
| reference_id         | str       | Reference id of the record in the original source |
| country_iso          | str       | DEU                                               |
| region               | str       | Bundesland / Sea                                  |
| district             | str       | Landkreis                                         |
| municipality         | str       | Gemeinde                                          |

#### storages
| Column               | Data type | Description                                        |
|----------------------|-----------|----------------------------------------------------|
| unit_id              | int       | pk                                                 |
| storage_type         | str       | Type of energy storage system                      |
| storage_capacity     | str       | Usable energy storage capacity Kilowatt-hour (kWh) |
| installed_capacity   | float     | Kilowatt (kW)                                      |
| commissioning_date   | date      | Commissioning date of the system                   |
| decommissioning_date | date      | Decommissioning date of the system                 |
| geometry             | point     | WGS-84                                             |
| geo_accuracy         | int       | 1/2                                                |
| reference_id         | str       | Reference id of the record in the original source  |
| reference_date       | date      | Timestamp of the record in the original source     |
| country_iso          | str       | DEU                                                |
| region               | str       | Bundesland / Sea                                   |
| district             | str       | Landkreis                                          |
| municipality         | str       | Gemeinde                                           |

### Dimension tables (double set)
#### parameters
| Column        | Data type |
|---------------|-----------|
| param_id      | int pk    |
| name          | str       |
| value         | str       |
| (name, value) | unique    |
#### units_parameters
| Column              | Data type |
|---------------------|-----------|
| unit_id             | int fk    |
| param_id            | int fk    |
| (unit_id, param_id) | pk        |

## 4. Marts
- **Number of installations** pivot table (region / energy source)
- **Generation capacity pivot** table (region / energy source)
- **Storage capacity** pivot table (region / energy source)

## Tools
1. Data Processing: Python (Pandas, GeoPandas)
2. Database: PostgreSQL + PostGIS 
3. Orchestration: Python scripts / Airflow (optional)
4. Visualization: Metabase 
5. Infrastructure: Docker, GitHub Actions
