# QA Notes

## Files Checked

- Full ingest file: `terraquantum_ready.csv`
- End-to-end subset file: `normalized/andes97_invert_subset.csv`
- Backend path exercised: FastAPI `TestClient` from `terraquantum-backend`
- Project persistence during QA: temporary directory patched into `core.block_model_store.PROJECTS_DIR`; no historical `data/projects` run was used for this benchmark QA

## Full File Preview

`POST /gravity-import/preview` with `terraquantum_ready.csv`:

- HTTP status: `200`
- Import status: `ok`
- Total observations: `6151`
- Gravity column used: `g_mgal`
- Gravity type: `bouguer_anomaly`
- Spatial readiness returned: `PROFESSIONAL_SURVEY`
- Import errors: none

The source has real latitude, longitude, elevation, Bouguer anomaly, and terrain correction values. The ready CSV also keeps `uncertainty_mgal` and `instrument_id` headers with blank values because those fields are absent in the NOAA file. Current backend readiness detection uses the header aliases, so it reports `PROFESSIONAL_SURVEY` rather than `GEOGRAPHIC_COORDS`.

## Full File Inversion Attempt

`POST /gravity-import/invert` with the full `terraquantum_ready.csv` was attempted without `acknowledge_spatial_risk`.

- HTTP status: `422`
- Spatial gate acknowledgement was not the blocker
- Backend validation detail: auto-generated inversion input had `nx=97` and `nz=145`, while the current inversion schema cap is `<=80` for each

This is a backend scale-contract limit for the regional full file, not a synthetic-data workaround and not a source-data failure.

## End-to-End Subset QA

To exercise the remaining TerraQuantum path, `normalized/andes97_invert_subset.csv` was derived from real stations in the full benchmark file:

- Subset station count: `152`
- Subset window: `-25.8 <= lat <= -25.0`, `-70.2 <= lon <= -69.2`
- Subset preview auto-grid: `nx=27`, `ny=16`, `nz=24`, `voxel_count=10368`

`POST /gravity-import/invert` with the subset and no `acknowledge_spatial_risk`:

- HTTP status: `200`
- Status: `done`
- Stage: `inversion`
- Spatial readiness: `PROFESSIONAL_SURVEY`
- `r3_enrichment.attempted`: `true`
- `r3_enrichment.enrichment_attempted`: `true`
- `r3_enrichment.enrichment_status`: `ok`
- `r3_enrichment.has_elevation_data`: `true`

Follow-up endpoint checks for the same temporary run:

- `GET /block-model`: HTTP `200`
- `/block-model has_elevation_data`: `true`
- `GET /export-report`: HTTP `200`
- Report HTML contains `Contrato Espacial de Entrada`: `true`

## QA Boundaries

- The QA checks ingestion, spatial-readiness gating, inversion integration, R3 enrichment, block-model exposure, and report generation on public gravity data.
- The benchmark does not claim that the gravity anomalies validate mineralization, grade, reserves, or economics.
