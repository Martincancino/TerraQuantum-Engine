# CHANGELOG

## [0.2.0] — 2026-06-16

### Motor & Pipeline

- **Fase 1 (Joint normalization)**: Cross-gradient coupling normalizado. `λ_cross_eff = β · ‖G_scaled‖_F / ‖B·χ‖_F` reemplaza 1e4 hardcodeado. Elimina degradación de misfit gravimétrico (0.52% → 100%) en modo conjunto.
- **Fase 2 (Kernel cache)**: Kernels gravimétrico/magnético construidos una vez pre-loop; reutilizados en 15 iteraciones alternas. Speedup: ~21 min → ~3 s en demo.
- **Fase 3 (3D Model Engine)**: Schema v4.0 (x_m/density_t_m3/doi_index/density_contrast), doi_reliable mode, `/v2/block-model-profile` A-A', Arrow LZ4.
- **Fase 4 (LOD & 3D Visualization)**: Tiers de material LOD (≤5k Physical / 5k-50k Standard / >50k Worker), terrain LOD por survey size, doi_index color badge, cross-section heat map Viridis.
- **Fase 5 (Formulas Audit)**: Rename `_kg → _tonnes`, fix `GEMINI_MODEL_NAME`, tests FAC <0.01 mGal + λ calibración r=0.73≥0.70; 32/32 PASS.
- **Fase 6 (Reports)**: ASEG-GDF2 export (.dfn+.dat), Obs vs Calc HTML section, UBC-GIF .den rename; todos los criterios cumplidos. Eliminación de `ProjectRunList` huérfano.

### UI Avanzada (Fase 7)

- **Fase 7A (ColorPipeline)**: Pipeline de color unificado. Clase `ColorPipeline` consolida colormap spectral/turbo/inferno, atenuación DOI y gating de visibilidad en un único lugar reutilizable. Elimina duplicación entre Scene3D, workers y terraQuantumGeology.
- **Fase 7B-1 (DOI Threshold Slider)**: Campo `doiThreshold` (0.0–1.0, default 0.9) en Zustand store. Permite ajuste interactivo desde UI.
- **Fase 7B-2 (PGI UI)**: Modal de parámetros PGI (K-clases, α_pgi, max_iter). Enviado como JSON en FormData; backend parsea y pasa a `run_geophysics_inversion`.
- **Fase 7B-3 (Remanencia UI)**: Modal de remanencia magnética (Q-ratio, Inc/Dec, modo de inversión, do_q_sweep). Disponible solo en modo `magnetic`.

### Infraestructura

- **Fase 8 (Versión 0.2.0)**: Version bump backend (config.py) y frontend (package.json). CHANGELOG creado. Deployment docs en `docs/DEPLOYMENT.md` pendiente.

### Backend Routing

- `gravity_import_api.py /invert`: Acepta `pgi_params_json` y `remanence_json` como Form fields opcionales. Parsea con Pydantic y los inyecta en `GeophysicsInvertInput`.

### Breaking Changes

Ninguno. Todos los cambios son backward compatible. Los nuevos Form fields son opcionales con default `None`.

### Limitaciones Conocidas

- DOI threshold slider (Fase 7B-1): actualmente se almacena en Zustand pero no está conectado a `updateInstancedBuffers`. Pendiente wiring en Scene3D (Fase 7C).
- PGI UI (Fase 7B-2): usa siempre `fit_from_model=True` con componentes dummy. La UI de componentes explícitos requiere una segunda iteración (petrología por litología).
- Remanencia (Fase 7B-3): solo disponible en inversiones magnéticas (dataType="magnetic"). No aplica en gravity ni joint por el momento.

---

## [0.1.0] — 2026-06-01

Release inicial. Inversión gravimétrica (Li & Oldenburg Tier 1), inversión conjunta, PGI, focusing, correcciones (FAC/BC/TC), visualización (colormap espectral, DOI, modelo 3D).
