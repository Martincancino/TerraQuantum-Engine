# TerraQuantum

Plataforma experimental/conceptual de exploracion geofisica 3D.

No es herramienta de decision minera, recursos, reservas ni factibilidad.

## Estructura

- `terraquantum-backend`: backend FastAPI.
- `terraquantum-web`: frontend Next.js.
- `docker-compose.yml`: stack Docker local.
- `README_TERRAQUANTUM_LOCAL.md`: guia local extendida.
- `README_TERRAQUANTUM_DOCKER.md`: guia Docker.

## Quick Start local

```powershell
.\start-terraquantum.bat
```

## Arranque manual

- Backend en `8010`.
- Frontend en `3000`.

## Docker

```powershell
docker compose up --build
```

## URLs

- Frontend: http://localhost:3000
- Health backend: http://127.0.0.1:8010/health
- Docs backend: http://127.0.0.1:8010/docs

## Seguridad

- No commitear `.env`, `.env.local`, `credenciales_gee.json`, `data/` o `tmp/`.
- GEE es opcional y requiere credenciales fuera del repo.

## Estado tecnico

- Auto-grid.
- Coordinate transform.
- MS-x always-on.
- Favorability.
- Guardrails semanticos/economicos.

Estado experimental/conceptual.
