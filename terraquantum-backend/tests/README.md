# Tests automatizados — TerraQuantum Backend

## Cómo correr los tests

```bash
# Desde terraquantum-backend/
pytest tests/ -v

# Solo tests rápidos (sin escritura a disco)
pytest tests/ -v -m "not integration"

# Con cobertura
pytest tests/ -v --cov=services --cov=exploration --cov-report=term-missing
```

## Marcadores disponibles

- `integration` — tests que crean archivos en `data/projects/pytest_*/`. Se limpian manualmente.
- `slow` — tests que tardan más de 10s.

## Nota sobre datos de test

Los tests de integración crean corridas con `project_id=pytest_XXXXXXXX` (uuid aleatorio) en
`data/projects/`. Estos archivos NO se limpian automáticamente. Para limpiar:

```bash
# Desde terraquantum-backend/
python -c "import shutil, glob; [shutil.rmtree(p) for p in glob.glob('data/projects/pytest_*')]"
```

## Scripts de validación manuales

Los scripts bajo `scripts/validation/` son ADICIONALES a estos tests — no fueron reemplazados.
Para correrlos manualmente: `python scripts/validation/test_project_run_flow.py`
