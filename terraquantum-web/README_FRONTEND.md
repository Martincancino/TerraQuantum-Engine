# TerraQuantum Frontend

Frontend industrial de TerraQuantum construido con Next.js, React, Zustand, Three.js y React Three Fiber.

Este frontend conecta con el backend Python/FastAPI para visualizar:

- Modelo geofísico 3D
- Inversión gravimétrica
- Block model exploratorio
- Telemetría MWD
- Diseño matemático de rajo abierto
- Modelo GLB del pit
- Métricas LOM y NPV
- Diagnóstico de conexión backend/frontend

---

## Estructura principal

```txt
terraquantum-web/
│
├─ app/
│  ├─ api/
│  │  ├─ _lib/
│  │  │  └─ backend.ts
│  │  ├─ backend-health/
│  │  ├─ block-model/
│  │  ├─ generate-pit/
│  │  ├─ geophysics-invert/
│  │  └─ system-check/
│  │
│  ├─ page.tsx
│  ├─ layout.tsx
│  └─ globals.css
│
├─ componentes/
│  ├─ views/
│  │  ├─ Exploration3DView.tsx
│  │  └─ MineDesignView.tsx
│  │
│  ├─ huds/
│  │  ├─ BackendStatusBadge.tsx
│  │  ├─ BottomControls.tsx
│  │  ├─ MwdLiveLink.tsx
│  │  └─ TelemetryConsole.tsx
│  │
│  ├─ Scene3D.tsx
│  ├─ MineDesign3D.tsx
│  └─ PitMetricsPanel.tsx
│
├─ lib/
│  ├─ terraquantum/
│  │  ├─ frontendApi.ts
│  │  ├─ geophysicsModel.ts
│  │  ├─ geophysicsSurvey.ts
│  │  └─ pitDesignModel.ts
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