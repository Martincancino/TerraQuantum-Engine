# TerraQuantum Backend

Backend FastAPI para TerraQuantum.

## Requisitos

- Python 3.11 recomendado.
- pip.
- Windows PowerShell o terminal equivalente.

## Setup local

```powershell
cd terraquantum-backend
copy .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Arranque local

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

## URLs

- Health: http://127.0.0.1:8010/health
- Docs: http://127.0.0.1:8010/docs

## Tests

```powershell
python -m compileall api services schemas core reporting -q
pytest tests/ -v
```

## Variables principales

- `TERRAQUANTUM_HOST`
- `TERRAQUANTUM_PORT`
- `CORS_ALLOWED_ORIGINS`
- `CSV_MAX_BYTES`
- `GEE_CREDENTIALS_PATH`

## GEE

Google Earth Engine es opcional para desarrollo. Si no esta configurado, el backend levanta igual con degradacion/fallback.

Nunca commitear credenciales.

## Seguridad

- No usar wildcard `*` en CORS en produccion.
- No subir `.env` ni `credenciales_gee.json`.
