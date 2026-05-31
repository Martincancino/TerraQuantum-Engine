# TerraQuantum Frontend

Frontend Next.js para TerraQuantum.

## Requisitos

- Node 20.
- npm.

## Setup local

```powershell
cd terraquantum-web
copy .env.example .env.local
npm install
```

## Variables

- `NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL`
- `TERRAQUANTUM_BACKEND_URL`

## Arranque

```powershell
npm run dev
```

## Build/lint

```powershell
npm.cmd run lint
npm.cmd run build
```

## URLs

- Frontend: http://localhost:3000
- Backend esperado: http://127.0.0.1:8010

## Nota

El backend debe estar corriendo antes de usar importacion CSV, terreno GEE o reportes.

Las rutas `app/api/*` actuan como proxy cuando corresponde.
