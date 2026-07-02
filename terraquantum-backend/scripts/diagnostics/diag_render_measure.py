"""Mide el cuerpo recuperado por /load-package: misfit, dmax, n(contrast>0.3),
spread espacial y centroide. Lee el block_model_anomaly.parquet del run recién
creado. Uso: python diag_render_measure.py <pkg_relpath>"""
import os, sys, glob, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from main import app

pkg_rel = sys.argv[1] if len(sys.argv) > 1 else "../prueba_gravimetria_v2.tqpkg"
pkg = os.path.join(os.path.dirname(__file__), pkg_rel)
client = TestClient(app)
with open(pkg, "rb") as f:
    r = client.post("/v2/gravity-import/load-package",
                    files={"file": (os.path.basename(pkg), f, "text/csv")})
print("HTTP", r.status_code)
data = r.json()
rep = (data.get("inversionResult") or data).get("report") or data
bmp = rep.get("blockModelPath") or rep.get("anomalyPath")
# Localiza el run_dir más reciente.
runs = glob.glob("data/projects/pkg_*/runs/*/block_model_anomaly.parquet")
runs.sort(key=os.path.getmtime)
parq = runs[-1]
df = pd.read_parquet(parq)
c = df["density_contrast_t_m3"].to_numpy()
x = df["x_m"].to_numpy(); z = df["z_m"].to_numpy()
m = c > 0.3
print(f"run_parquet: {os.path.basename(os.path.dirname(parq))}")
print(f"misfit_%={rep.get('misfit_error_percent')}  chi2={rep.get('chi2_final'):.3f}")
print(f"anomaly_voxels(payload)={len(df)}  dmax_contrast={np.nanmax(c):.2f}")
print(f"n(contrast>0.3)={int(m.sum())}")
if m.sum():
    xx, zz, w = x[m], z[m], c[m]
    cx = (w*xx).sum()/w.sum(); cz = (w*zz).sum()/w.sum()
    spread = np.sqrt((w*((xx-cx)**2+(zz-cz)**2)).sum()/w.sum())
    print(f"centroid=({cx:.0f},{cz:.0f}) spread={spread:.0f}m  [verdad ~760,760]")
bt = rep.get("best_target") or {}
print("best_target:", json.dumps({k: bt.get(k) for k in
      ("x_m","y_m","z_m","density","depth_m","is_resolvable_depth","confidence_level")}))
ver = rep.get("overall_verdict") or {}
print("verdict.level:", ver.get("level"))
dr = rep.get("depthResolution") or {}
print("depthResolution.computed:", dr.get("computed"))
