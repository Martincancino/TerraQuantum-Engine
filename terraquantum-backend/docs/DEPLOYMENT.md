# Deployment Guide — TerraQuantum v0.2.0

## Overview

TerraQuantum is a geophysical inversion engine (gravity + magnetometry → 3D density/susceptibility models).

**Architecture:**
- Backend: Python 3.11+ / FastAPI (port 8000)
- Frontend: Next.js 18+ (port 3000)
- Storage: Parquet (runs), DEM cache, model files
- Optional: PostgreSQL (project metadata), Redis (background tasks)

---

## Prerequisites

### System Requirements
- **CPU**: 4+ cores (inversions scale poorly on 2-core)
- **RAM**: 16 GB minimum (32 GB for regional grids >200k voxels)
- **Disk**: 50 GB (models, cache, DEM)
- **OS**: Linux (production), macOS/Windows (development)

### Software
- Python 3.11+
- Node.js 18+ LTS
- PostgreSQL 13+ (optional, recommended for production)
- Redis 6+ (optional, for background job queue)

---

## Backend Deployment

### Local Development

```bash
cd terraquantum-backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Reload enabled
```

Visit: http://localhost:8000/docs (Swagger UI)

### Production Deployment (Docker)

**1. Build Image**

```bash
docker build -t terraquantum-backend:0.2.0 -f Dockerfile .
```

Example `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_VERSION=0.2.0
ENV APP_ENV=production
ENV DEBUG=false

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

**2. Run Container**

```bash
docker run -d \
  --name terraquantum-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -e APP_ENV=production \
  -e TQ_AUTH_ENABLED=true \
  -e TERRAQUANTUM_SECRET_KEY=<your-secret-key> \
  -e TERRAQUANTUM_RUN_DIR=/data/runs \
  -v /mnt/data/runs:/data/runs \
  terraquantum-backend:0.2.0
```

**3. Health Check**

```bash
curl http://localhost:8000/health
# Expected:
# {"status": "ok", "version": "0.2.0", "app_env": "production"}
```

### Environment Variables

Create `.env` file (never commit):

```env
# Version & Environment
APP_VERSION=0.2.0
APP_ENV=production
DEBUG=false

# Security
TQ_AUTH_ENABLED=true
TERRAQUANTUM_SECRET_KEY=<generate-random-256-bit-key>
ALLOWED_ORIGINS=https://app.terraquantum.example.com

# Storage Paths
TERRAQUANTUM_RUN_DIR=/data/runs
TERRAQUANTUM_CACHE_DIR=/data/cache
TERRAQUANTUM_MODEL_DIR=/data/models

# Database (optional)
DATABASE_URL=postgresql://user:pass@localhost:5432/terraquantum

# Cache (optional)
REDIS_URL=redis://localhost:6379/0

# Solver Configuration
USE_BOUNDED_SOLVER=true
USE_PROJECTED_SOLVER=true
USE_LSMR_LARGE=true
SOLVER_TIMEOUT_SECONDS=300

# OpenTopography API (terrain corrections)
OPENTOPO_API_KEY=<your-api-key>

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

---

## Frontend Deployment

### Build for Production

```bash
cd terraquantum-web
npm install
npm run build
```

### Option A: Self-Hosted (Next.js)

```bash
npm run start
# Runs: http://localhost:3000
```

### Option B: Docker

```dockerfile
FROM node:18-alpine

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 3000
ENV NEXT_PUBLIC_API_BASE_URL=https://api.terraquantum.example.com
ENV NEXT_PUBLIC_VERSION=0.2.0

CMD ["npm", "start"]
```

```bash
docker build -t terraquantum-web:0.2.0 .
docker run -d --name terraquantum-web -p 3000:3000 terraquantum-web:0.2.0
```

---

## Reverse Proxy (Nginx)

```nginx
upstream api_backend  { server localhost:8000; }
upstream app_frontend { server localhost:3000; }

server {
  listen 443 ssl http2;
  server_name api.terraquantum.example.com;

  ssl_certificate     /etc/letsencrypt/live/api.terraquantum.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/api.terraquantum.example.com/privkey.pem;

  location / {
    proxy_pass http://api_backend;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Long timeout for inversions
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
  }
}

server {
  listen 443 ssl http2;
  server_name app.terraquantum.example.com;

  ssl_certificate     /etc/letsencrypt/live/app.terraquantum.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/app.terraquantum.example.com/privkey.pem;

  location / {
    proxy_pass http://app_frontend;
    proxy_set_header Host $host;
  }

  location /_next/static {
    expires 365d;
    add_header Cache-Control "public, immutable";
  }
}

server {
  listen 80;
  server_name api.terraquantum.example.com app.terraquantum.example.com;
  return 301 https://$server_name$request_uri;
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/terraquantum /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

---

## Database Setup (Optional)

```bash
sudo -u postgres createdb terraquantum
sudo -u postgres psql -d terraquantum -c "CREATE USER terraquantum WITH PASSWORD 'your-password';"
sudo -u postgres psql -d terraquantum -c "GRANT ALL ON SCHEMA public TO terraquantum;"
export DATABASE_URL=postgresql://terraquantum:your-password@localhost:5432/terraquantum
```

---

## Monitoring & Logging

Backend outputs JSON structured logs (`LOG_FORMAT=json`):

```json
{
  "timestamp": "2026-06-16T10:00:00Z",
  "level": "INFO",
  "message": "Inversion completed",
  "run_id": "abc123def456",
  "duration_s": 45.2,
  "misfit_percent": 0.52,
  "n_voxels": 125000
}
```

Simple uptime check:

```bash
curl -f http://localhost:8000/health || echo "API DOWN — alert!"
```

---

## Troubleshooting

### Inversion Timeout (>300s)

- Increase `SOLVER_TIMEOUT_SECONDS`
- Reduce grid size (larger `block_size`)
- Set `USE_LSMR_LARGE=true` for grids >50k voxels
- Use background task queue (Redis)

### Out of Memory (>32 GB)

- Enable Zarr/Parquet out-of-core (Fase 10)
- Split grid into overlapping regions
- Use lower-resolution forward model
- Increase server RAM to 64+ GB

### CORS / Frontend Can't Reach Backend

In `terraquantum-backend/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.terraquantum.example.com",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Backup & Recovery

### Data to Backup

```
/data/runs/     # All inversion results (Parquet, JSON, reports)
/data/cache/    # DEM cache (regenerable)
```

### Backup to S3

```bash
aws s3 sync /data/runs s3://terraquantum-backups/runs/daily/$(date +%Y%m%d) --delete
```

### Restore

```bash
aws s3 sync s3://terraquantum-backups/runs/daily/20260616 /data/runs
docker restart terraquantum-api
```

---

## Performance Tuning

**Backend (Uvicorn workers):**

```dockerfile
# Rule of thumb: workers = (2 × CPU cores) + 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "8"]
```

**Solver flags:**

```env
USE_LSMR_LARGE=true       # LSMR for n > 50k (faster than LSQR)
USE_BOUNDED_SOLVER=true   # FISTA projected bounds (better physics)
```

---

## Version Upgrades

### Pre-Upgrade Checklist

- [ ] Backup `/data/runs/` to S3 or external drive
- [ ] Test in staging environment
- [ ] Review `CHANGELOG.md` for breaking changes

### Upgrade Steps

```bash
# Backend
git fetch origin v0.3.0
git checkout v0.3.0
pip install -r requirements.txt --upgrade
docker build -t terraquantum-backend:0.3.0 .
docker stop terraquantum-api
docker run -d ... terraquantum-backend:0.3.0

# Frontend
git checkout v0.3.0
npm install && npm run build
docker build -t terraquantum-web:0.3.0 .
docker restart terraquantum-web
```

---

## Support

- API Docs: `http://api.example.com/docs` (Swagger)
- Contact: `support@terraquantum.example.com`

*Last Updated: 2026-06-16 — Version: 0.2.0*
