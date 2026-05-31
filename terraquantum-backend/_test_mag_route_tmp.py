import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import run_geophysics_inversion
from exploration.magnetometry import MagnetometryForward

NX, NY, NZ, B = 8, 6, 8, 10
gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
xc = gx.flatten(order='F') * B + B / 2
yc = gy.flatten(order='F') * B + B / 2
zc = gz.flatten(order='F') * B + B / 2

sensors = [(float(x), 0.0, float(z)) for x in range(10, 90, 12) for z in range(10, 90, 20)]
sc = np.array(sensors, dtype=float)

# TMI sintetica desde el propio motor (round-trip a traves del SERVICIO)
fwd = MagnetometryForward(B, B, B, 150.0, -30, 2, 23500)
G = fwd.build_sparse_kernel(xc, yc, zc, sc)
st = np.zeros(len(xc)); st[((xc-40)**2 + (yc-30)**2 + (zc-40)**2) < 300] = 0.08
tmi = (G @ st).tolist()

obs = [GravityObservation(x_m=s[0], y_m=s[1], z_m=s[2], g=0.0) for s in sensors]
inp = GeophysicsInvertInput(
    project_id=None, run_id=None,
    depth=50, nir=50, fe=50, region="norte_chile", lat="-24", lon="-69",
    nx=NX, ny=NY, nz=NZ, block_size=B, cutoff_radius=150.0,
    lambda_mag=1e-4, alpha_spatial=1.0, observations=obs,
    magnetic_nt=tmi, inclination_deg=-30, declination_deg=2,
    field_intensity_nt=23500, susc_min=0.0, susc_max=1.0,
)

print(f"[ROUTE TEST] {len(sensors)} sensores | TMI min={min(tmi):.2f} max={max(tmi):.2f} nT")
res = run_geophysics_inversion(inp)
rep = res["report"]
print("-" * 64)
print(f"[ROUTE TEST] method = {rep['method']}")
print(f"[ROUTE TEST] is_joint_inversion = {rep['is_joint_inversion']}")
print(f"[ROUTE TEST] f_hat = {rep['field']['field_unit_vector_xyz']}")
print(f"[ROUTE TEST] cond_A = {rep['solver']['cond_A']:.2e}")
print(f"[ROUTE TEST] misfit = {res['misfit_error_percent']:.3f}% | voxels = {len(res['voxels'])}")
if res["best_target"]:
    bt = res["best_target"]
    print(f"[ROUTE TEST] best_target susc={bt['susceptibility']:.4f} @ ({bt['x_m']:.0f},{bt['y_m']:.0f},{bt['z_m']:.0f})")
print("-" * 64)
assert rep["method"] == "magnetic_dipole_tmi_phase9a", "no ruteo a magnetico"
assert rep["solver"]["cond_A"] < 1e14, "cond(A) excede 1e14"
assert res["misfit_error_percent"] < 1.0, "misfit alto en round-trip"
assert len(res["voxels"]) > 0, "sin voxels de susceptibilidad"
assert "density" not in (res["voxels"][0] if res["voxels"] else {}), "fuga de densidad en payload magnetico"
print("[ROUTE TEST] PASS: ruteo magnetico OK, cond(A)<1e14, sin fuga de densidad")
