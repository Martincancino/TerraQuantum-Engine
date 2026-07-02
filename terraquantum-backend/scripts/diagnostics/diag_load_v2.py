"""Diagnóstico: corre prueba_gravimetria_v2.tqpkg por /load-package (flujo real UI)
y reporta densidad recuperada, best_target, misfit y depthResolution."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
pkg = os.path.join(os.path.dirname(__file__), "..", "prueba_gravimetria_v2.tqpkg")
with open(pkg, "rb") as f:
    r = client.post("/v2/gravity-import/load-package",
                    files={"file": ("prueba_gravimetria_v2.tqpkg", f, "text/csv")})

print("HTTP", r.status_code)
data = r.json()
inv = data.get("inversionResult") or data
rep = inv.get("report") or inv

def g(d, *ks):
    for k in ks:
        d = (d or {}).get(k) if isinstance(d, dict) else None
    return d

# densidad recuperada
dr = g(rep, "depthResolution") or {}
bt = rep.get("best_target") or {}
ver = rep.get("overall_verdict") or {}
print("status:", data.get("status"), "| stage:", data.get("stage"))
print("misfit_%:", rep.get("misfit_error_percent"))
print("chi2:", rep.get("chi2_final"))
print("density_min/max recuperada:",
      g(rep, "metadata", "densityMin") or rep.get("densityMin"),
      g(rep, "metadata", "densityMax") or rep.get("densityMax"))
print("best_target:", json.dumps({k: bt.get(k) for k in
      ("x_m","y_m","z_m","density","depth_m","is_resolvable_depth","confidence_level")}, ensure_ascii=False))
print("overall_verdict.level:", ver.get("level"), "| limiting:", ver.get("limiting_factors"))
print("depthResolution:", json.dumps({k: dr.get(k) for k in
      ("computed","deep_mass_fraction","resolvable_depth_max_m","resolvable_body_depth_m")}, ensure_ascii=False))
# voxeles sobre cutoff (lo que el 3D dibuja)
vox = rep.get("voxels") or inv.get("voxels")
if isinstance(vox, list):
    print("n_voxels en payload:", len(vox))
print("--- claves del reporte (top) ---", sorted(list(rep.keys()))[:25])
