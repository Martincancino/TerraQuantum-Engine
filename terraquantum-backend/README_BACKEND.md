# TerraQuantum Backend

Backend industrial para TerraQuantum.

Este backend usa FastAPI y contiene los motores principales de:

- Inversión geofísica gravimétrica
- Generación de block model
- Visualización exploratoria
- Diseño matemático de rajo abierto
- Optimización tipo Lerchs-Grossmann
- Planificación LOM
- Análisis de sensibilidad
- Smoke test industrial

---

## Estructura actual

```txt
terraquantum-backend/
│
├─ api/
│  ├─ block_model_api.py
│  ├─ geophysics_api.py
│  ├─ pit_design_api.py
│  ├─ scenario_sweep_api.py
│  └─ system_api.py
│
├─ core/
│  └─ config.py
│
├─ schemas/
│  ├─ geophysics_schema.py
│  ├─ pit_design_schema.py
│  └─ scenario_sweep_schema.py
│
├─ services/
│  ├─ block_model_service.py
│  ├─ geophysics_service.py
│  ├─ pit_design_service.py
│  └─ scenario_sweep_service.py
│
├─ exploration/
│  ├─ gravimetry.py
│  └─ geophysics_api.py
│
├─ Camiones/
│  └─ fms.py
│
├─ scripts/
│  └─ smoke_test_backend.py
│
├─ data/
├─ tmp/
├─ public/models/
│
├─ engine.py
├─ pit_mesh.py
├─ scheduler.py
├─ main.py
├─ start-backend.bat
├─ run-smoke-test.bat
├─ requirements.txt
└─ README_BACKEND.md