# TerraQuantum Public Gravity Benchmark B1

## Dataset

- Name: South America: Andes Gravity Station Data (1997) / Central Andes Gravity 1997
- Official source: NOAA National Centers for Environmental Information (NCEI), legacy NGDC gravity archive
- Metadata page: https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.geophysics%3AG01455
- Download directory: https://www.ngdc.noaa.gov/mgg/gravity/1999/data/regional/andes97/
- Accessed: 2026-05-22
- Source terms shown by NCEI: "If you use this data, please cite the National Geophysical Data Center and the originator of the data." The NCEI metadata also reports `Access Constraints: None` and a NOAA/NCEI distribution liability notice.

The NCEI summary describes 6,151 Central Andes gravity station records compiled by Professor Gotze and the MIGRA Group. It states that the principal gravity parameters include Free-air Anomalies and Bouguer Anomalies, that the Bouguer values are terrain and mass corrected, that station gravity is adjusted to IGSN 71, and that anomaly computation uses the GRS 67 theoretical gravity formula.

## Raw Files

Files copied unchanged from the official NOAA download directory:

- `raw/andes97.ast`: fixed-width ASCII station data
- `raw/andes97.fmt`: fixed-width field layout
- `raw/andes97.hdr`: per-field min/max/unit header
- `raw/andes97.txt`: source summary and contributor note

## Original Columns

`raw/andes97.fmt` defines these ASCII fields:

| Source field | Position | Used here |
| --- | --- | --- |
| `station_id` | 1-7 | Yes |
| `longitude` | 8-19 | Yes |
| `latitude` | 20-30 | Yes |
| `utm_east` | 31-39 | Kept in normalized intermediate |
| `utm_north` | 40-48 | Kept in normalized intermediate |
| `sea_level_elev_m` | 49-57 | Yes |
| `obs_grav` | 58-68 | Kept in normalized intermediate |
| `terr_corr_onshore_267` | 69-77 | Yes, as `terrain_correction` |
| `mass_corr_offshore_164` | 78-86 | Kept in normalized intermediate |
| `Free_air_anom` | 87-95 | Kept in normalized intermediate |
| `Bouguer_anom` | 96-104 | Yes, as `g_mgal` |

## Benchmark Outputs

- `normalized/andes97_station_rows.csv` is the parsed fixed-width NOAA station table with source field names retained.
- `terraquantum_ready.csv` is the full TerraQuantum ingest benchmark with all 6,151 stations.
- `normalized/andes97_invert_subset.csv` is a real 152-station subset from `terraquantum_ready.csv` used only for the current end-to-end inversion QA. The subset window is `-25.8 <= lat <= -25.0` and `-70.2 <= lon <= -69.2`.

## TerraQuantum Mapping

| TerraQuantum field | Source / value |
| --- | --- |
| `station_id` | NOAA `station_id` |
| `lat` | NOAA `latitude` |
| `lon` | NOAA `longitude` |
| `g_mgal` | NOAA `Bouguer_anom` in mGal |
| `elevation_m` | NOAA `sea_level_elev_m` |
| `uncertainty_mgal` | Empty: not present in the downloaded NOAA station file |
| `instrument_id` | Empty: not present in the downloaded NOAA station file |
| `terrain_correction` | NOAA `terr_corr_onshore_267` in mGal |
| `unit` | Constant `mGal`, matching the NOAA Bouguer anomaly unit |
| `gravity_type` | Constant `bouguer_anomaly`, matching the selected gravity field |

`terrain_correction` is used instead of relabeling the NOAA terrain correction as a full `bouguer_correction`. The NOAA file also carries `mass_corr_offshore_164`; it remains in the parsed intermediate and is not mapped into the ingest CSV.

## Transformations

1. Parsed `raw/andes97.ast` by the 1-based fixed-width ranges in `raw/andes97.fmt`.
2. Preserved the parsed source fields in `normalized/andes97_station_rows.csv`.
3. Selected NOAA `Bouguer_anom` as the TerraQuantum gravity value because the source summary identifies it as a principal anomaly field and the backend accepts `bouguer_anomaly`.
4. Renamed geographic coordinates and elevation to TerraQuantum aliases.
5. Added explicit `unit=mGal` and `gravity_type=bouguer_anomaly` required by strict TerraQuantum CSV import.
6. Left missing uncertainty and instrument values empty.
7. Emitted derived CSV files as UTF-8 without BOM so the first header is recognized by strict import.

## Why This Fits TerraQuantum

- It is a real public gravity-station dataset with station coordinates, elevation, anomaly values, and official field documentation.
- It exercises public-data provenance, fixed-width parsing, TerraQuantum alias mapping, geographic coordinate detection, gravity import preview, and inversion/report integration on a real gravity signal.
- It is an ingestion and geospatial gravity benchmark. It is not evidence of mineralization, a mining dataset classification, or an economic validation.

## Limitations

- The full dataset is regional in scale across the Central Andes. In the current backend QA, full-file preview succeeds but full-file inversion is rejected because auto-grid dimensions exceed the inversion input cap.
- The NOAA file does not provide per-station uncertainty or instrument identifiers in the downloaded ASCII layout.
- NOAA metadata says Bouguer anomalies are terrain and mass corrected, but this benchmark does not recompute anomaly reductions.
- **Estado de clasificación (actualizado post R3.5-I-FIX1):** Antes de R3.5-I-FIX1, el sistema podía sobreclasificar datasets con headers profesionales vacíos como `PROFESSIONAL_SURVEY`. Ese comportamiento fue corregido. El estado actual correcto es: `terraquantum_ready.csv` (columnas `uncertainty_mgal` e `instrument_id` vacías) clasifica como **`GEOGRAPHIC_COORDS`**, no como `PROFESSIONAL_SURVEY`. Un CSV equivalente con `uncertainty_mgal` e `instrument_id` poblados puede clasificar como `PROFESSIONAL_SURVEY`. El archivo completo sigue siendo de escala regional y no apto para inversión única bajo R3.7 (scale_class = `TOO_LARGE_SINGLE_INVERSION`).
