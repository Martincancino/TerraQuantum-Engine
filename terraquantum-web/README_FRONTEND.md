# TerraQuantum Frontend

Frontend industrial de TerraQuantum construido con Next.js, React, Zustand, Three.js y React Three Fiber.

Este frontend conecta con el backend Python/FastAPI para visualizar:

- Modelo geofísico 3D (densidad, DOI, incertidumbre)
- Inversión gravimétrica con correcciones de campo (GRS80/FAC/BC/TC)
- Block model exploratorio (Parquet/Arrow)
- Observed vs Calculated (misfit, chi², r²)
- Historial y comparación de corridas
- Diagnóstico de conexión backend/frontend

El frontend NO calcula física: solo visualiza y consume APIs del backend.

---

## Estructura principal

```txt
terraquantum-web/
│
├─ app/
│  ├─ api/                      # BFF: proxy tipado hacia el backend
│  │  ├─ _lib/
│  │  │  └─ backend.ts
│  │  ├─ backend-health/
│  │  ├─ block-model/
│  │  ├─ geophysics-invert/
│  │  ├─ geophysics-misfit/
│  │  ├─ geophysics-status/
│  │  ├─ gravity-import/
│  │  ├─ gravity-corrections/
│  │  └─ system-check/
│  │
│  ├─ page.tsx
│  ├─ layout.tsx
│  └─ globals.css
│
├─ componentes/
│  ├─ views/
│  │  ├─ HomeView.tsx
│  │  ├─ Exploration3DView.tsx
│  │  ├─ HistorialView.tsx
│  │  └─ IAChatView.tsx
│  │
│  ├─ datos/
│  │  ├─ ObsVsCalcPanel.tsx
│  │  └─ RunComparePanel.tsx
│  │
│  ├─ Scene3D.tsx
│  ├─ GravityCsvPreviewPanel.tsx
│  └─ GravityCorrectionWizard.tsx
│
├─ lib/
│  ├─ terraquantum/
│  │  ├─ frontendApi.ts
│  │  ├─ geophysicsModel.ts
│  │  └─ geophysicsSurvey.ts
│  │
│  └─ terraQuantumGeology.ts
│
├─ scripts/
│  └─ smoke_test_frontend.mjs
│
├─ store/
│  └─ useAppStore.ts
│
├─ start-frontend.bat
├─ run-frontend-smoke-test.bat
├─ .env.example
├─ .gitignore
└─ README_FRONTEND.md
```
