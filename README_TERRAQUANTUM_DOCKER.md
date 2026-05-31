# TerraQuantum — Docker

Levanta el sistema completo (backend FastAPI + frontend Next.js) con un solo comando.

## Prerequisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y corriendo
- Puertos 8010 y 3000 libres

## Levantar el sistema

```bash
# Desde la raíz del proyecto (donde está este archivo)
docker compose up --build
```

El flag `--build` garantiza que las imágenes se recompilen si hay cambios en el código.

## URLs

| Servicio | URL |
|----------|-----|
| Frontend (Next.js) | http://localhost:3000 |
| Backend API (FastAPI) | http://localhost:8010 |
| Swagger / Docs | http://localhost:8010/docs |
| Healthcheck | http://localhost:8010/health |

## Comandos útiles

```bash
# Primera vez o después de cambiar dependencias
docker compose up --build

# Levantar sin rebuild (más rápido)
docker compose up

# Levantar en background
docker compose up -d

# Ver logs de un servicio específico
docker compose logs -f backend
docker compose logs -f frontend

# Parar todo
docker compose down

# Parar y eliminar volúmenes (CUIDADO: borra corridas en data/ y tmp/)
docker compose down -v
```

## Persistencia de datos

Los directorios de corridas mineras se mapean a carpetas locales:

| Carpeta local | Montada en el contenedor | Contenido |
|--------------|--------------------------|-----------|
| `terraquantum-backend/data/` | `/app/data` | Parquets, proyectos, block models |
| `terraquantum-backend/tmp/` | `/app/tmp` | Archivos temporales de corridas |
| `terraquantum-backend/public/` | `/app/public` | Modelos GLB generados (pit design) |

Los datos persisten entre reinicios del contenedor mientras no se ejecute `docker compose down -v`.

## Variables de entorno

El sistema usa estas variables (ya configuradas en `docker-compose.yml`):

| Variable | Valor en Docker | Descripción |
|----------|----------------|-------------|
| `TERRAQUANTUM_HOST` | `0.0.0.0` | Host de escucha del backend |
| `TERRAQUANTUM_PORT` | `8010` | Puerto del backend |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Origenes permitidos para el frontend local |
| `CSV_MAX_BYTES` | `10485760` | Tamano maximo de CSV en bytes |
| `TERRAQUANTUM_BACKEND_URL` | `http://backend:8010` | URL interna (server-side Next.js) |
| `NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL` | `http://localhost:8010` | URL pública (browser del usuario) |

## Healthcheck

El backend expone `http://localhost:8010/health` y Docker Compose lo usa como healthcheck. El frontend espera a que el backend este `healthy` antes de arrancar.

## CORS

Por defecto Docker permite el frontend local en `http://localhost:3000` y `http://127.0.0.1:3000`.
En produccion se debe configurar el dominio exacto en `CORS_ALLOWED_ORIGINS`; no usar `*`.

## Google Earth Engine (GEE) opcional

Si no configuras GEE, el backend levanta igual con degradacion/fallback.

Para usar GEE real:

1. Coloca `credenciales_gee.json` fuera de git.
2. Descomenta en `docker-compose.yml` el volumen opcional:
   ```yaml
   - ./credenciales_gee.json:/app/credenciales_gee.json:ro
   ```
3. Descomenta la variable:
   ```yaml
   - GEE_CREDENTIALS_PATH=/app/credenciales_gee.json
   ```

No commitear credenciales ni archivos `*credentials*.json`.

## Rebuild selectivo

```bash
# Solo reconstruir el backend
docker compose build backend

# Solo reconstruir el frontend
docker compose build frontend
```

## Desarrollo local (sin Docker)

Para desarrollo se siguen usando los scripts `.bat` habituales:
```
start-terraquantum.bat
```
El backend levanta en `http://127.0.0.1:8010` y el frontend en `http://localhost:3000`.
