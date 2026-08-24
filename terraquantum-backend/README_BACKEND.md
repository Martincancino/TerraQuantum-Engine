# TerraQuantum Backend

Backend industrial para TerraQuantum — plataforma de exploración geofísica.

Este backend usa FastAPI y contiene los motores principales de:

- Inversión geofísica gravimétrica y magnética 3D (LSQR/LSMR/TRF, W_z formal)
- Correcciones de gravedad de campo (GRS80, Free-Air, Bouguer, terreno)
- Generación de block model (Parquet/Arrow, schema v4.0)
- Observed vs Calculated, DOI e incertidumbre posterior
- Exportación industrial (UBC-GIF, VTK, GSLIB, ASEG-GDF2)
- Open Mining Format v1 (`.omf`): exportación e importación de sondajes — ver
  `docs/09_OMF_INTEROPERABILIDAD.md`
- Reportes técnicos con disclaimers JORC/NI 43-101
- Smoke test industrial

---

## Estructura actual

```txt
terraquantum-backend/
│
├─ api/
│  ├─ geophysics_api.py
│  ├─ gravity_import_api.py
│  ├─ gravity_corrections_api.py
│  ├─ block_model_api.py
│  ├─ report_api.py
│  ├─ export_api.py
│  ├─ terrain_api.py
│  └─ system_api.py
│
├─ core/
│  ├─ config.py
│  ├─ auth.py
│  └─ block_model_store.py
│
├─ schemas/
│  ├─ geophysics_schema.py
│  ├─ gravity_import_schema.py
│  ├─ gravity_corrections_schema.py
│  └─ response_schema.py
│
├─ services/
│  ├─ geophysics_service.py
│  ├─ gravity_import_service.py
│  ├─ gravity_corrections_service.py
│  ├─ block_model_service.py
│  └─ export_service.py
│
├─ exploration/
│  ├─ gravimetry.py
│  ├─ magnetometry.py
│  └─ solver_preconditioned.py
│
├─ docs/
│  └─ GUIA_DATOS_DE_CAMPO.md
│
├─ scripts/
├─ tests/
├─ data/
├─ tmp/
├─ public/models/
│
├─ main.py
├─ start-backend.bat
├─ run-smoke-test.bat
├─ requirements.txt
└─ README_BACKEND.md
```

Los módulos de diseño de mina, escenarios económicos y flota FMS fueron
eliminados del producto (2026-06-10): TerraQuantum se enfoca exclusivamente
en el modelo geofísico 3D. No se calculan NPV, LOM ni recursos minerales.
