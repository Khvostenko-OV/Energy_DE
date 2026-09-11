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
| Dataset              | Description                                              | Filename                             | Type         |
|----------------------|----------------------------------------------------------|--------------------------------------|--------------|
| Bioenergy            | Locations of power generation units of bioenergy systems | Bioenergy_V20250101.gpkg             | Point        |
| Cogeneration Units   | Locations of cogeneration units (not using for now)      | Cogeneration_Units_V20250101.gpkg    | Point        |
| Energy Storage       | Locations of energy storage units greater than 100 kW    | Energy_Storage_V20250101.gpkg        | Point        |
| Gas Production       | Location of gas production systems                       | Gas_Producer_V20250101.gpkg          | Point        |
| Hydropower           | Locations of hydropower systems                          | Hydropower_V20250101.gpkg            | Point        |
| Solarenergy Polygons | Polygons of solar energy systems (not using for now)     | Solar_Energy_Polygons_V20250101.gpkg | Multipolygon |
| Solar Energy         | Locations of solar energy systems                        | Solar_Energy_V20250101.gpkg          | Point        |
| Wind Energy          | Locations of wind turbines                               | Wind_Energy_V20250101.gpkg           | Point        |

### Germany administrative boundaries (incl. Offshore zones). Source https://www.quickmaptools.com https://www.marineregions.org
| Dataset        | Description                                              | Filename               | Type         |
|----------------|----------------------------------------------------------|------------------------|--------------|
| State boundary | Germany state boundary                                   | germany_boundary.gpkg  | Multipolygon |
| Regions + EEZ  | Regions boundaries + Germany EEZ boundaries (Bundesland) | germany_regions.gpkg   | Multipolygon |
| Districts      | District boundaries (Landkreis + Kreisfreie Stadt)       | germany_districts.gpkg | Multipolygon |
| Municipalities | Municipalities boundaries (Gemeinde)                     | germany_munis.gpkg     | Multipolygon |

## ETL-pipeline description
### 1. Extract
- Input: text file with names of files in the same directory to be extracted
- Check if the file was already loaded. If attribute force (-f) - load else skip
- Read files to geopandas dataframes.
- Type casting
- Drop duplicates
- Convert secondary properties to dictionary, place it to column 'properties'
- Save to PostGIS datalake. Table names should contain source type, date of load, number of load
#### Load administrative and maritime boundaries
- Load .gpkg files with boundaries into table **boundaries** if not exist
### 2. Transform
- Input: list of tables to be transformed
- Add primary keys
- Enrich tables with columns 'region', 'district', 'municipality' (spatial join with Boundaries)
- Decompose properties dictionaries to normalized tables (many-to-many)
- Quality check. Flag bad records, add property 'bad_record' in which append failed tests description:
  1. installed_capacity <=0 or null
  2. decommissioning_date <= commissioning_date
  3. x_coordinates, y_coordinates and geometry do not match
  4. region is null
- Save tables to PostGIS
### 3. Load
#### First load
- Input: list of tables to be loaded
- Create tables **generators**, **storages**
- Insert into **generators** data from Units tables bio, gas, hydro, solar, wind (only good records)
- Insert into **storages** data from Units table storage (only good records)
- Transfer primary keys for dimension tables
- Create indexes
- Quality check. Flag collisions, add property 'collision' with collisions description, 
add property 'close_to' with reference to close unit
  1. Close location. Distance between units < 10m (only if geo_accuracy=1)
  2. Onshore unit in the sea
  3. storage_capacity <=0 or null (for storages)

#### Incremental load 
- Input: list of tables to be loaded
- Append-or-update **generators** table with records from Units tables (using reference_id, reference_date for update)
- Append-or-update **storages** table with records from Units table storage (using reference_id, reference_date for update)
- Transfer primary keys for dimension tables
- Quality check

### Creating Materialized Views
- Number of units pivot table (region / energy_source)
- Generation capacity pivot table (region / energy_source)
- Storage capacity pivot table (region / source_type)

## Serving
### 1. Visualization
- Metabase dashboard with map
- Checkboxes to show units of different type (Bio, Hydro, Wind, Solar, Gas, Storage)
- Checkbox to show/hide decommissioned units
- Multiselectors to include different regions, districts, municipalities
- Calendar to choose time scope 
- Charts showing the total installed capacity according to the selected unit types

### 2. Admin panel (auth)
- Correcting records (CRUD)
- Resolving collisions

### 3. API (auth)
- Quering records from BD (Exel file)
- Quering aggregated data from BD (JSON)

## Data layers
### 1. Raw
#### loaded_files - list of datafiles loaded into Raw layer
| Column      | Data type |
|-------------|-----------|
| filename    | str       |
| filesize    | int       |
| modified_at | timestamp |
| loaded_at   | timestamp |
| loaded_to   | str       |

#### Units tables: bio, gas, hydro, solar, wind
| Column               | Data type | Description                                       |
|----------------------|-----------|---------------------------------------------------|
| energy_source        | str       | Type of unit (bio, gas, hydro, solar, wind)       |
| installed_capacity   | float     | Kilowatt (kW)                                     |
| commissioning_date   | date      | Commissioning date of the system                  |
| decommissioning_date | date      | Decommissioning date of the system                |
| x_coordinates        | float     | Longitude WGS-84                                  |
| y_coordinates        | float     | Latitude WGS-84                                   |
| geo_accuracy         | int       | 1/2                                               |
| reference_id         | str       | Reference id of the record in the original source |
| reference_date       | timestamp | Timestamp of the record in the original source    |
| geometry             | point     | WGS-84                                            |
| secondary_attributes | jsonb     | Dictionary of secondary attributes                |

#### Units table: storage
| Column                | Data type | Description                                        |
|-----------------------|-----------|----------------------------------------------------|
| energy_source         | str       | Type of unit (storage)                             |
| installed_capacity    | float     | Kilowatt (kW)                                      |
| commissioning_date    | date      | Commissioning date of the system                   |
| decommissioning_date  | date      | Decommissioning date of the system                 |
| storage_type          | str       | Type of energy storage system                      |
| storage_capacity      | float     | Usable energy storage capacity Kilowatt-hour (kWh) |
| x_coordinates         | float     | Longitude WGS-84                                   |
| y_coordinates         | float     | Latitude WGS-84                                    |
| geo_accuracy          | int       | 1/2                                                |
| reference_id          | str       | Reference id of the record in the original source  |
| reference_date        | date      | Timestamp of the record in the original source     |
| geometry              | point     | WGS-84                                             |
| secondary_attributes  | jsonb     | Dictionary of secondary attributes                 |

#### boundaries
| Column           | Data type    | Description                                         |
|------------------|--------------|-----------------------------------------------------|
| country_iso      | str          | DEU                                                 |
| name             | str          | name of area                                        |
| level            | int          | Administrative level 0 - county,..,3 - municipality |
| area             | float        | km2                                                 |
| geometry         | multipolygon | WGS-84                                              |


### 2. Staging
#### Units tables: bio, gas, hydro, solar, wind
| Column               | Data type | Description                                       |
|----------------------|-----------|---------------------------------------------------|
| unit_id              | str       | pk                                                |
| energy_source        | str       | Type of unit (bio, gas, hydro, solar, wind)       |
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
| bad_quality          | bool      | Flag bad quality record                           |

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
| bad_quality          | bool      | Flag bad quality record                            |

### Dimension tables (normalized, one set for each Unit table)
#### properties
| Column        | Data type |
|---------------|-----------|
| param_id      | int pk    |
| name          | str       |
| value         | str       |
| (name, value) | unique    |
#### units_properties
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
| collision            | bool      | Flag collisions                                    |

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
| collision            | bool      | Flag collisions                                    |

### Dimension tables (double set)
#### properties
| Column        | Data type |
|---------------|-----------|
| param_id      | int pk    |
| name          | str       |
| value         | str       |
| (name, value) | unique    |
#### units_properties
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

## Implementation
1. ETL pipeline using CLI interface
2. DB design using schemas
3. Logging with time control
4. For Staging layer using reference_id to create unit_id. If not present create hash-key
5. For Core layer using serial primary key