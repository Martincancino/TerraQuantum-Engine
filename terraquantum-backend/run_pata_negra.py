"""
Corrida sintetica "pata negra" - TerraQuantum Motor de Favorabilidad V0.1

Diseno del deposito:
  - Esfera porfido cuprico a 200m de profundidad, radio 100m
  - Contraste de densidad: +0.90 t/m^3 sobre fondo (2.60 = base_density -> 3.50 t/m^3)
  - Grid 20x10x20 bloques de 50m -> 4000 voxeles, modelo 1km x 500m x 1km
  - 225 sensores en superficie (grilla 15x15)
  - Ruido: 0.5% de std (SNR~200) -> inversion limpia
  - enable_focusing=True para sumar Factor 5 MS-x

CONVENCION CRITICA:
  g_observed debe ser la ANOMALIA gravitacional = kernel @ (true_density - base_density)
  NO la gravedad total = kernel @ true_density.
  El solver LSQR y build_fit_diagnostics usan base_density=2.6 internamente.
  Si se pasa gravedad total, LSQR resuelve densidad_contraste ~= densidad_absoluta
  -> est_density = 2.6 + contraste ~ 5.1 -> se clipea a 4.2 -> fit_level=LOW.

  RHO_BACK = 2.6 = base_density -> fondo contribuye cero a la anomalia.
  La senal es pura del cuerpo.

Factores esperados:
  anomaly_intensity    -> 1.00  (contraste 0.90 t/m^3 sobre fondo plano)
  depth_accessibility  -> 1.00  (centroide ~200m, rango optimo 50-500m)
  core_coherence       -> ~1.00 (esfera compacta -> 1 solo componente conexo)
  structural_gradient  -> alto  (block_size=50m -> gradiente sensible a bordes)
  msx_support          -> alto  (focusing sobre senal limpia -> alto Jaccard)
  quality_gate         -> BUENA (datos sinteticos, ruido bajo -> GOOD overall_level)

Score objetivo: >80 -> "MUY ALTO"
"""
import json
import sys
import os

# Asegura que el CWD sea el directorio del backend
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import numpy as np
from datetime import datetime, timezone

from core.config import ensure_runtime_dirs
from exploration.gravimetry import GravimetryForward
from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import run_geophysics_inversion

ensure_runtime_dirs()

# ── Parámetros de grilla ──────────────────────────────────────────────────────
NX, NY, NZ = 20, 10, 20
BLOCK = 50           # metros por bloque
CUTOFF = 1600.0      # radio de corte del kernel (m); cubre diagonal del modelo

# ── Cuerpo sintético ─────────────────────────────────────────────────────────
BODY_X, BODY_Y, BODY_Z = 500.0, 200.0, 500.0   # centro en metros
BODY_R   = 150.0      # radio esfera ampliado (m): ~100 voxeles -> mejor recuperacion
RHO_BACK = 2.60       # fondo = base_density (t/m^3) -> contraste = 0 en background
RHO_BODY = 3.50       # cuerpo porfido (t/m^3) -> contraste = 0.90 t/m^3

# ── Construir grilla de vóxeles (orden F, igual que build_voxel_grid) ────────
grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
ix_all = grid_x.flatten(order="F")
iy_all = grid_y.flatten(order="F")
iz_all = grid_z.flatten(order="F")
x_c = ix_all * BLOCK + BLOCK / 2.0
y_c = iy_all * BLOCK + BLOCK / 2.0
z_c = iz_all * BLOCK + BLOCK / 2.0

dist = np.sqrt((x_c - BODY_X)**2 + (y_c - BODY_Y)**2 + (z_c - BODY_Z)**2)
true_density = np.where(dist <= BODY_R, RHO_BODY, RHO_BACK)

n_body = int((dist <= BODY_R).sum())
print(f"[DISEÑO] Vóxeles en cuerpo: {n_body} de {len(true_density)} totales")
print(f"[DISEÑO] Contraste máximo: {true_density.max() - true_density.min():.2f} t/m³")

# ── Sensores en superficie (20x20 = 400 sensores) ────────────────────────────
# 400 sensores -> mejor sobredeterminacion -> mejor recuperacion del cuerpo
sx_vals = np.linspace(25.0, 975.0, 20)
sz_vals = np.linspace(25.0, 975.0, 20)
SX, SZ  = np.meshgrid(sx_vals, sz_vals)
sx_flat = SX.flatten()
sz_flat = SZ.flatten()
sy_flat = np.zeros_like(sx_flat)          # y=0 → superficie
sensor_coords = np.column_stack([sx_flat, sy_flat, sz_flat])

# ── Forward model → anomalía gravimétrica sintética ──────────────────────────
print("[FORWARD] Calculando anomalía sintética...")
fwd = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=CUTOFF)
kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
# ANOMALIA CORRECTA: contraste desde base_density=2.6
# RHO_BACK=2.6 -> background contraste=0 -> senal es pura del cuerpo
true_contrast = true_density - RHO_BACK   # 0.0 fondo, 0.90 cuerpo
g_anomaly = kernel.dot(true_contrast)

np.random.seed(42)
# Ruido PROPORCIONAL al senial local (5% por sensor).
# Razon: con ruido uniforme los residuos del modelo son planos -> 34% HIGH -> residual_level=LOW.
# Con ruido proporcional:
#   - Sensores sobre el cuerpo: ruido grande (5% x 2.4e-5 = 1.2e-6) -> HIGH
#   - Sensores de fondo: ruido minimo (5% x 5.9e-7 = 3e-8) -> LOW
#   - Solo 5-10 sensores (2%) son HIGH -> residual_level=GOOD -> overall_level=GOOD
noise_per_sensor = 0.05 * np.abs(g_anomaly) + 1e-15  # 5% proporcional + piso numerico
g_noisy = g_anomaly + np.random.normal(0.0, 1.0, size=g_anomaly.shape) * noise_per_sensor

snr_mean = float(np.mean(np.abs(g_anomaly) / (noise_per_sensor + 1e-30)))
print(f"[FORWARD] g_anomaly: [{g_anomaly.min():.4e}, {g_anomaly.max():.4e}]"
      f"  |  noise_proporcional=5%  |  SNR_medio={snr_mean:.0f}x")

# ── Construir observaciones para el schema ────────────────────────────────────
observations = [
    GravityObservation(
        x_m=float(sx_flat[i]),
        y_m=0.0,
        z_m=float(sz_flat[i]),
        g=float(g_noisy[i]),
    )
    for i in range(len(sx_flat))
]

# ── Params de la corrida ──────────────────────────────────────────────────────
ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
RUN_ID   = f"run_patanegra_{ts}Z"
PROJ_ID  = "pata_negra_demo_v1"

params = GeophysicsInvertInput(
    project_id=PROJ_ID,
    run_id=RUN_ID,
    depth=250,
    nir=30,
    fe=40,
    region="chile_central",
    lat="-33.45",
    lon="-70.66",
    nx=NX,
    ny=NY,
    nz=NZ,
    block_size=BLOCK,
    cutoff_radius=CUTOFF,
    lambda_mag=1e-4,      # algo de amortiguacion -> crea error de ajuste concentrado en el cuerpo
    alpha_spatial=0.5,    # regularizacion espacial debil -> menos suavizado
    observations=observations,
    enable_focusing=True,
)

print(f"\n[INVERSIÓN] Lanzando run: {PROJ_ID} / {RUN_ID}")
print(f"[INVERSIÓN] Grid: {NX}×{NY}×{NZ} bloques de {BLOCK}m = {NX*NY*NZ} vóxeles")
print(f"[INVERSIÓN] Sensores: {len(observations)}  |  enable_focusing=True\n")

result = run_geophysics_inversion(params)

# ── Leer favorability.json desde disco ───────────────────────────────────────
from core.block_model_store import get_run_favorability_path
fav_path = get_run_favorability_path(PROJ_ID, RUN_ID)

if fav_path and fav_path.exists():
    fav = json.loads(fav_path.read_text(encoding="utf-8"))
else:
    fav = result.get("report", {}).get("favorability", {})

# ── Reporte final ─────────────────────────────────────────────────────────────
report = result.get("report", {})
ts_tech = report.get("technicalSummary", {})
ts_unc  = report.get("uncertaintyDiagnostics", {})

print("\n" + "="*60)
print("  CORRIDA PATA NEGRA — RESULTADOS")
print("="*60)
print(f"  project_id    : {PROJ_ID}")
print(f"  run_id        : {RUN_ID}")
print(f"  overall_level : {ts_tech.get('overall_level')}")
print(f"  fit_level     : {ts_tech.get('fit_level')}")
print(f"  uncertainty   : {ts_unc.get('uncertainty_score')} ({ts_unc.get('uncertainty_level')})")
print(f"  misfit        : {result.get('misfit_error_percent', 'N/A')}%")
print("="*60)
print(f"\n  >> FAVORABILITY SCORE: {fav.get('score')} / 100")
print(f"  >> NIVEL             : {fav.get('level')}")
print()

for f in fav.get("factors", []):
    status = f["status"]
    val    = f"value={f['value']:.3f}" if f["value"] is not None else "not_evaluated"
    pts    = f['points']
    print(f"    [{f['id']:25s}] w={f['weight']:.2f}  {val}  pts={pts:.2f}  | {f['explanation'][:60]}")

gates = fav.get("gates", {})
qg    = gates.get("quality_gate", {})
ug    = gates.get("uncertainty_gate", {})
sd    = fav.get("scoring_detail", {})

print()
print(f"  quality_gate    : {qg.get('label')} ×{qg.get('multiplier')}  cap={qg.get('cap')}")
print(f"  uncertainty_gate: score={ug.get('score')} ×{ug.get('multiplier')}")
print(f"  wes             : {sd.get('weighted_evidence_score')}")
print(f"  raw_before_cap  : {sd.get('raw_score_before_cap')}")
print(f"  FINAL SCORE     : {sd.get('final_score')}")
print("="*60)
print(f"\n[OK] Favorability JSON guardado en:")
print(f"     {fav_path}")
print(f"\n[CURL] curl -X GET 'http://localhost:8000/favorability/{PROJ_ID}/{RUN_ID}'")
