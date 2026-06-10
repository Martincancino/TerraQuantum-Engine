"""
AUDIT SYNTHETIC TEST — TerraQuantum Motor de Inversión Geofísica 3D
======================================================================
FASE 3 de la auditoría matemática exhaustiva.

Genera un modelo sintético canónico:
  - Medio homogéneo: rho_host = 2.67 t/m³
  - Bloque anómalo: rho_body = 3.00 t/m³ (contraste = +0.33 t/m³)
  - Dimensiones: 200 m × 200 m × 200 m
  - Profundidad al techo: ~300 m (centro a 400 m)

Ejecuta Forward Modeling con ruido gaussiano 2% y luego invierte.
Compara la anomalía recuperada con el bloque real usando:
  - Profundidad del pico de densidad vs. profundidad real
  - Densidad máxima recuperada vs. densidad real
  - chi² reducido final
  - Misfit relativo ‖d - Gm‖/‖d‖
  - Resolución en profundidad: error de profundidad del pico

Resultados criteriados:
  PASS: pico en profundidad ± 1 celda (OK para problema sub-determinado)
  WARN: pico en profundidad ± 3 celdas
  FAIL: pico fuera de ± 3 celdas (skin effect grave)
"""

import sys
import os
import time

# Añadir el backend al path
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE LA GRILLA
# ─────────────────────────────────────────────────────────────────────────────
BLOCK_SIZE   = 50.0      # metros por celda (más grande = más rápido)
NX           = 20        # 1000 m total en X
NY           = 16        # 800 m en Y (profundidad)
NZ           = 20        # 1000 m en Z
CUTOFF       = 800.0     # radio de corte del kernel

RHO_HOST     = 2.67      # densidad del medio (t/m³)
RHO_BODY     = 3.00      # densidad del bloque anómalo (t/m³)
CONTRAST     = RHO_BODY - RHO_HOST   # 0.33 t/m³

# Posición del bloque sintético (centros de vóxeles afectados)
# Bloque: X ∈ [350, 650], Z ∈ [350, 650], Y (prof) ∈ [300, 500]
BODY_X_CENTER = 500.0
BODY_Z_CENTER = 500.0
BODY_Y_CENTER = 400.0    # profundidad al centro
BODY_RADIUS   = 150.0    # radio de la esfera equivalente

NOISE_PCT    = 0.02      # 2% de ruido gaussiano sobre el rango dinámico
LAMBDA_MAG   = 3.0       # lambda de producción (el operating point fijo)
ALPHA_SPATIAL = 1.0
SEED         = 42

# ─────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("AUDIT SYNTHETIC TEST — TerraQuantum Geophysics Engine")
print("=" * 70)

# Grilla de vóxeles en orden Fortran
grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
ix = grid_x.flatten(order="F").astype(np.int32)
iy = grid_y.flatten(order="F").astype(np.int32)
iz = grid_z.flatten(order="F").astype(np.int32)

x_c = (ix * BLOCK_SIZE) + (BLOCK_SIZE / 2)
y_c = (iy * BLOCK_SIZE) + (BLOCK_SIZE / 2)
z_c = (iz * BLOCK_SIZE) + (BLOCK_SIZE / 2)

total_voxels = len(x_c)
print(f"\n[MALLA] {NX}x{NY}x{NZ} = {total_voxels:,} vóxeles | block_size={BLOCK_SIZE:.0f}m")
print(f"[MALLA] Dominio: X=[0,{NX*BLOCK_SIZE:.0f}] Y=[0,{NY*BLOCK_SIZE:.0f}] Z=[0,{NZ*BLOCK_SIZE:.0f}] m")

# ── Modelo verdadero: contraste respecto al medio ────────────────────────────
true_contrast = np.zeros(total_voxels, dtype=np.float64)
blob_mask = (
    (x_c - BODY_X_CENTER) ** 2 +
    (y_c - BODY_Y_CENTER) ** 2 +
    (z_c - BODY_Z_CENTER) ** 2
) < BODY_RADIUS ** 2

true_contrast[blob_mask] = CONTRAST
n_blob = int(np.sum(blob_mask))
print(f"\n[MODELO TRUE] Bloque esférico: r={BODY_RADIUS:.0f}m | centro=(x={BODY_X_CENTER:.0f}, y={BODY_Y_CENTER:.0f}, z={BODY_Z_CENTER:.0f})")
print(f"[MODELO TRUE] Vóxeles en el bloque: {n_blob} | contraste={CONTRAST:.3f} t/m³")
if n_blob == 0:
    print("ERROR: Ningún vóxel cayó en el bloque. Revisar parámetros de malla.")
    sys.exit(1)

# Profundidad del centro verdadero
true_y_center = BODY_Y_CENTER
print(f"[MODELO TRUE] Profundidad del centro verdadero: {true_y_center:.1f} m")
print(f"[MODELO TRUE] Techo del bloque: ~{BODY_Y_CENTER - BODY_RADIUS:.0f} m | Piso: ~{BODY_Y_CENTER + BODY_RADIUS:.0f} m")

# ── Sensores en superficie (y=0) ─────────────────────────────────────────────
n_sensors_1d = 8
sx = np.linspace(BLOCK_SIZE, NX * BLOCK_SIZE - BLOCK_SIZE, n_sensors_1d)
sz = np.linspace(BLOCK_SIZE, NZ * BLOCK_SIZE - BLOCK_SIZE, n_sensors_1d)
SX, SZ = np.meshgrid(sx, sz)
sensor_coords = np.column_stack([
    SX.ravel(),
    np.zeros(SX.size),      # y=0: superficie
    SZ.ravel()
])
n_sensors = len(sensor_coords)
print(f"\n[SENSORES] {n_sensors_1d}×{n_sensors_1d} = {n_sensors} sensores en y=0")

# ─────────────────────────────────────────────────────────────────────────────
# FORWARD MODELING
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 70)
print("FASE 1: FORWARD MODELING")
print("-" * 70)

from exploration.gravimetry import GravimetryForward, GravimetryInversion

t0 = time.perf_counter()
forward = GravimetryForward(BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF)
G = forward.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
t_forward = time.perf_counter() - t0

# Datos sintéticos limpios
g_clean = G @ true_contrast
g_range = float(np.max(g_clean) - np.min(g_clean))
g_amplitude = float(np.max(np.abs(g_clean)))

print(f"\n[FORWARD] Tiempo: {t_forward:.2f}s")
print(f"[FORWARD] Anomalía gravimétrica teórica:")
print(f"  min={g_clean.min():.6e} | max={g_clean.max():.6e} | rango={g_range:.6e}")

# Añadir ruido gaussiano 2%
rng = np.random.default_rng(SEED)
noise_sigma = NOISE_PCT * g_range
noise = rng.normal(0.0, noise_sigma, size=n_sensors)
g_observed = g_clean + noise
snr_db = 20.0 * np.log10(g_amplitude / noise_sigma) if noise_sigma > 0 else float('inf')

print(f"[FORWARD] Ruido añadido: σ={noise_sigma:.4e} ({NOISE_PCT*100:.0f}% del rango) | SNR≈{snr_db:.1f} dB")

# ─────────────────────────────────────────────────────────────────────────────
# INVERSIÓN
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 70)
print("FASE 2: INVERSIÓN (motor de producción)")
print("-" * 70)
print(f"Parámetros: lambda_mag={LAMBDA_MAG} | alpha_spatial={ALPHA_SPATIAL}")
print(f"Bounds: density ∈ [{RHO_HOST:.2f}, 4.20] t/m³")

inversor = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE)
inversor.base_density = RHO_HOST   # ajustar base al medio sintético

solver_meta = {}
t_inv_start = time.perf_counter()
est_density, rel_score, misfit_pct, norm_sens = inversor.solve_inversion_lsqr(
    g_observed=g_observed,
    kernel_sparse=None,
    y_c=y_c,
    lambda_mag=LAMBDA_MAG,
    alpha_spatial=ALPHA_SPATIAL,
    topography_elevations=None,
    sensor_coords=sensor_coords,
    x_c=x_c,
    z_c=z_c,
    forward_model=forward,
    density_min=RHO_HOST,
    density_max=4.20,
    solver_meta=solver_meta,
)
t_inv = time.perf_counter() - t_inv_start

print(f"\n[INVERSIÓN] Tiempo total: {t_inv:.1f}s")

# ─────────────────────────────────────────────────────────────────────────────
# EVALUACIÓN DE RESULTADOS
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("EVALUACIÓN DE RESULTADOS — PRUEBA DE FUEGO")
print("=" * 70)

# Densidad recuperada (limpiar NaN → base_density)
est_clean = np.where(np.isfinite(est_density), est_density, RHO_HOST)

# 1. Densidad máxima recuperada
max_rho_recovered = float(np.max(est_clean))
max_rho_idx       = int(np.argmax(est_clean))
peak_x = float(x_c[max_rho_idx])
peak_y = float(y_c[max_rho_idx])
peak_z = float(z_c[max_rho_idx])

print(f"\n─── Densidad ───────────────────────────────────────────────")
print(f"  Densidad real del bloque:         {RHO_BODY:.3f} t/m³")
print(f"  Densidad máxima recuperada:       {max_rho_recovered:.3f} t/m³")
density_error_pct = abs(max_rho_recovered - RHO_BODY) / RHO_BODY * 100
print(f"  Error en densidad máxima:         {density_error_pct:.1f}%")

# 2. Profundidad del pico
print(f"\n─── Profundidad ────────────────────────────────────────────")
print(f"  Centro verdadero del bloque:      y = {true_y_center:.1f} m")
print(f"  Pico de densidad recuperado:      y = {peak_y:.1f} m  (x={peak_x:.1f}, z={peak_z:.1f})")
depth_error_m  = abs(peak_y - true_y_center)
depth_error_cells = depth_error_m / BLOCK_SIZE
print(f"  Error en profundidad del pico:    {depth_error_m:.1f} m ({depth_error_cells:.1f} celdas)")

# 3. Chi² y misfit
chi2 = solver_meta.get("chi2_final", float("nan"))
acond = solver_meta.get("acond", float("nan"))
print(f"\n─── Calidad del ajuste ─────────────────────────────────────")
print(f"  Misfit ‖d - Gm‖/‖d‖ × 100:       {misfit_pct:.2f}%")
print(f"  chi² reducido final:               {chi2:.4f}  (objetivo ≈ 1.0)")
print(f"  cond(A) estimado:                  {acond:.2e}  (objetivo < 1e12)")

# 4. Saturación de bounds
n_sat = solver_meta.get("n_sat_total", 0)
n_active = solver_meta.get("n_active", total_voxels)
sat_pct = solver_meta.get("sat_fraction", 0.0) * 100
print(f"\n─── Saturación petrofísica ─────────────────────────────────")
print(f"  Celdas saturadas en bounds:        {n_sat}/{n_active} ({sat_pct:.1f}%)")
print(f"  (>10% indica lambda demasiado alto o bounds incorrectos)")

# 5. Centroide de masa ponderado
contrast_recovered = est_clean - RHO_HOST
contrast_pos = np.clip(contrast_recovered, 0.0, None)
total_mass = float(np.sum(contrast_pos))
if total_mass > 1e-9:
    centroid_y = float(np.sum(y_c * contrast_pos) / total_mass)
    centroid_x = float(np.sum(x_c * contrast_pos) / total_mass)
    centroid_z = float(np.sum(z_c * contrast_pos) / total_mass)
    print(f"\n─── Centroide de masa (diagnóstico profundidad) ────────────")
    print(f"  Centro verdadero:                 ({BODY_X_CENTER:.0f}, {BODY_Y_CENTER:.0f}, {BODY_Z_CENTER:.0f}) m")
    print(f"  Centroide recuperado:             ({centroid_x:.0f}, {centroid_y:.0f}, {centroid_z:.0f}) m")
    centroid_depth_error = abs(centroid_y - true_y_center)
    print(f"  Error en profundidad (centroide): {centroid_depth_error:.1f} m ({centroid_depth_error/BLOCK_SIZE:.1f} celdas)")
else:
    centroid_y = peak_y
    centroid_depth_error = depth_error_m
    print(f"\n─── Centroide: masa recuperada ~0 (problema grave) ─────────")

# 6. Fracción de masa recuperada en la zona correcta
y_techo = BODY_Y_CENTER - BODY_RADIUS
y_piso  = BODY_Y_CENTER + BODY_RADIUS
# Extender ±1 celda para tolerancia de discretización
margin = BLOCK_SIZE
in_zone_mask = (y_c >= y_techo - margin) & (y_c <= y_piso + margin)
mass_in_zone  = float(np.sum(contrast_pos[in_zone_mask]))
mass_total_rec = float(np.sum(contrast_pos))
frac_in_zone = mass_in_zone / max(mass_total_rec, 1e-12)
print(f"\n─── Distribución de masa recuperada ────────────────────────")
print(f"  Zona correcta: y ∈ [{y_techo-margin:.0f}, {y_piso+margin:.0f}] m")
print(f"  Fracción de masa en zona correcta: {frac_in_zone:.1%}")

# ─────────────────────────────────────────────────────────────────────────────
# CRITERIOS DE PASE / FALLO
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("VEREDICTO FINAL")
print("=" * 70)

results = {}

# A. Profundidad del pico
if depth_error_cells <= 1.0:
    results["profundidad_pico"] = ("PASS", f"Error={depth_error_m:.0f}m ≤ 1 celda ({BLOCK_SIZE:.0f}m)")
elif depth_error_cells <= 3.0:
    results["profundidad_pico"] = ("WARN", f"Error={depth_error_m:.0f}m ({depth_error_cells:.1f} celdas) — sesgo de profundidad moderado")
else:
    results["profundidad_pico"] = ("FAIL", f"Error={depth_error_m:.0f}m ({depth_error_cells:.1f} celdas) — SKIN EFFECT GRAVE: masa concentrada en superficie")

# B. Densidad máxima (el LSQR suaviza, nunca recupera el valor exacto; ≥30% es aceptable)
density_recovery_pct = (max_rho_recovered - RHO_HOST) / CONTRAST * 100
if density_recovery_pct >= 60:
    results["densidad_recuperada"] = ("PASS", f"Recuperación={density_recovery_pct:.0f}% del contraste real")
elif density_recovery_pct >= 30:
    results["densidad_recuperada"] = ("WARN", f"Recuperación={density_recovery_pct:.0f}% — suavizado excesivo (lambda demasiado alto)")
else:
    results["densidad_recuperada"] = ("FAIL", f"Recuperación={density_recovery_pct:.0f}% — contraste casi invisible (lambda demasiado alto o cutoff bajo)")

# C. Misfit (10-30% aceptable con 2% de ruido en problema sub-determinado)
if misfit_pct <= 15:
    results["misfit"] = ("PASS", f"Misfit={misfit_pct:.2f}% ≤ 15%")
elif misfit_pct <= 40:
    results["misfit"] = ("WARN", f"Misfit={misfit_pct:.2f}% — sub-ajuste moderado")
else:
    results["misfit"] = ("FAIL", f"Misfit={misfit_pct:.2f}% — sub-ajuste grave (lambda demasiado alto)")

# D. chi² (debe estar cerca de 1; >>1 = sub-ajuste; <<1 = sobre-ajuste)
if 0.5 <= chi2 <= 3.0:
    results["chi2"] = ("PASS", f"chi²={chi2:.3f} ∈ [0.5, 3.0]")
elif 0.1 <= chi2 <= 10.0:
    results["chi2"] = ("WARN", f"chi²={chi2:.3f} — desajuste con el target chi²=1")
else:
    results["chi2"] = ("FAIL", f"chi²={chi2:.3f} — estimación de ruido errónea O lambda mal calibrado")

# E. Fracción de masa en zona correcta (≥40% = razonable para problema sub-determinado)
if frac_in_zone >= 0.40:
    results["masa_en_zona"] = ("PASS", f"Fracción={frac_in_zone:.1%} ≥ 40%")
elif frac_in_zone >= 0.20:
    results["masa_en_zona"] = ("WARN", f"Fracción={frac_in_zone:.1%} — masa dispersa por regularización L2")
else:
    results["masa_en_zona"] = ("FAIL", f"Fracción={frac_in_zone:.1%} — masa fuera de la zona (skin effect)")

# F. Condicionamiento
if np.isfinite(acond) and acond < 1e12:
    results["condicionamiento"] = ("PASS", f"cond(A)={acond:.2e} < 1e12")
elif not np.isfinite(acond):
    results["condicionamiento"] = ("INFO", "cond(A) no disponible (TRF o SuperLU path)")
else:
    results["condicionamiento"] = ("FAIL", f"cond(A)={acond:.2e} ≥ 1e12 — sistema mal condicionado")

# Imprimir veredictos
n_pass = n_warn = n_fail = 0
for criterion, (status, msg) in results.items():
    marker = {"PASS": "✓", "WARN": "△", "FAIL": "✗", "INFO": "ℹ"}.get(status, "?")
    print(f"  [{status:4s}] {marker} {criterion:25s}: {msg}")
    if status == "PASS": n_pass += 1
    elif status == "WARN": n_warn += 1
    elif status == "FAIL": n_fail += 1

print(f"\n  RESUMEN: {n_pass} PASS | {n_warn} WARN | {n_fail} FAIL")

# ─────────────────────────────────────────────────────────────────────────────
# DIAGNÓSTICO FORENSE DETALLADO
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("DIAGNÓSTICO FORENSE — Causas raíz identificadas")
print("=" * 70)

print("""
[D1] REGULARIZACIÓN L2 (Tikhonov): DIFUMINA BORDES GEOLÓGICOS
     El Laplaciano 3D con norma L2 produce soluciones suaves (smooth).
     Para un bloque rectangular, la L2 recupera una "nube" gaussiana en vez
     de bordes afilados. La densidad máxima recuperada será SIEMPRE menor que
     la real con L2. Fix: IRLS con norma L_p (p<1) — ya implementado como
     MS-x en focusing.py pero es EXPERIMENTAL y no está en producción.

[D2] LAMBDA FIJO (λ=3.0) SIN VALIDACIÓN DATA-DRIVEN
     El operating point λ=3.0 fue elegido por inspección visual en pruebas
     de depósitos pequeños. Para datos con distinta geometría (profundidad,
     extensión, contraste) un λ fijo puede sub-ajustar (chi²>>1) o sobreajustar.
     El selector automático (L-curve / chi²-target) existe pero NO se usa en
     producción. Riesgo: lambda muy alto → masa aplastada en superficie (skin
     effect); lambda muy bajo → sobreajuste del ruido.

[D3] COLUMN SCALING (Ws = 1/‖col‖) vs. DEPTH WEIGHTING FORMAL
     El column scaling normaliza CADA columna de G por su norma L2. Para
     gravimetría (G∝1/r²), las columnas profundas tienen norma menor →
     Ws las amplifica → efecto similar a depth weighting. PERO:
     - No tiene motivación física directa (depende de la geometría del sensor)
     - En magnetometría (G∝1/r³) el motor usa W_z formal (Li&Oldenburg) —
       inconsistencia entre los dos motores.
     - El column scaling puede enmascarar la selección de λ óptimo.

[D4] BOUNDS COMO CLIP POST-LSQR PARA n>8000
     Para mallas grandes (>8000 celdas activas), los bounds petrofísicos
     [density_min, density_max] se implementan como clip DESPUÉS del LSQR:
         m = clip(LSQR_solution, lb, ub)
     Esto viola la solución del problema regularizado. El TRF bounded (n≤8000)
     sí implementa constraints duros (scipy.optimize.lsq_linear). En datos
     reales con mallas grandes, el motor puede producir soluciones que
     "querían" salir del rango y el clip introduce un sesgo sistemático.

[D5] SIGMA ADAPTIVO CON ESCALA 2% PUEDE SOBRE-SUAVIZAR
     sigma_i = max(0.02|d_i|, 0.01·rango)
     Con datos limpios de laboratorio (SNR>>50dB), sigma = 0.02|d| sobreestima
     el ruido → Wd = 1/sigma subestima la contribución del dato → λ efectivo
     se reduce → suavizado excesivo. Necesita calibración contra el ruido real
     del instrumento.

[D6] FOCUSING MS-x CON β INCONSISTENTE (β=1.0 vs β=2.0 en solver)
     El solver principal usa depth_beta=2.0; el módulo de focusing usa
     _DEPTH_BETA=1.00 (hardcoded). Esto hace que la suavización por profundidad
     sea distinta en el post-procesamiento MS-x vs. la inversión base.
     Consecuencia: el focusing "empuja" la masa a profundidades distintas que
     el solver base.

[D7] LAPLACIANO MS-x SIN DEPTH WEIGHTING
     _build_spatial_regularizer(y_c=None) → pesos uniformes en el focusing.
     El Laplaciano del MS-x no tiene depth weighting, a diferencia del solver
     principal (que usa w_reg = 1/(depth+z0)^β). Inconsistencia estructural.
""")

print("=" * 70)
print(f"Test completado en {time.perf_counter()-t0:.1f}s total")
print("=" * 70)

# Exit code: 0 si no hay FAILs
sys.exit(n_fail)
