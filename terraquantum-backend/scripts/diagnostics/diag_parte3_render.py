"""PARTE 3 — Render real: corre v2 por /load-package (default FINAL = L2) y mide
(a) backend: anomalía/concentración; (b) FRONTEND: celdas VISIBLES tras el piso
relativo al pico (réplica de terraQuantumGeology.ts) + concentración del set visible."""
import os, sys, glob, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np, pandas as pd
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
pkg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "prueba_gravimetria_v2.tqpkg")
with open(pkg, "rb") as f:
    r = client.post("/v2/gravity-import/load-package",
                    files={"file": (os.path.basename(pkg), f, "text/csv")})
rep = (r.json().get("inversionResult") or r.json()).get("report") or r.json()
runs = glob.glob("data/projects/pkg_*/runs/*/block_model.parquet"); runs.sort(key=os.path.getmtime)
df = pd.read_parquet(runs[-1])
d = df["density_t_m3"].to_numpy() if "density_t_m3" in df else df["density"].to_numpy()
x = df["x_m"].to_numpy(); z = df["z_m"].to_numpy()
fin = np.isfinite(d)
d, x, z = d[fin], x[fin], z[fin]               # frontend ignora celdas no finitas
TRUE = (760., 760.)

# Réplica EXACTA del frontend (terraQuantumGeology.ts):
bg = float(np.median(d))
p95 = float(np.percentile(d, 95)); p05 = float(np.percentile(d, 5))
scale = max(p95 - bg, bg - p05, 0.05)
cmag = np.abs(d - bg) / scale
maxc = float(cmag.max())
ANOM_VIS, PEAK_FRAC, WEAK = 0.18, 0.20, 0.60
weak = maxc < WEAK
floor = ANOM_VIS if weak else max(ANOM_VIS, PEAK_FRAC * maxc)
old_vis = cmag >= ANOM_VIS                       # piso ANTES (fijo 0.18)
new_vis = cmag >= floor                          # piso DESPUÉS (relativo al pico)

def conc(mask):
    n = int(mask.sum())
    if n == 0: return 0, 0.0, 0.0
    dist = np.sqrt((x-TRUE[0])**2 + (z-TRUE[1])**2)
    near = mask & (dist <= 160)
    w = np.clip(d[mask]-bg, 0, None)
    massfrac = (np.clip(d[near]-bg,0,None).sum())/max(w.sum(),1e-9)
    # spread del set visible (x,z)
    xx, zz = x[mask], z[mask]; ww = np.clip(d[mask]-bg,1e-6,None)
    cx=(ww*xx).sum()/ww.sum(); cz=(ww*zz).sum()/ww.sum()
    spread=np.sqrt((ww*((xx-cx)**2+(zz-cz)**2)).sum()/ww.sum())
    return n, near.sum()/n, spread

no, oc, osp = conc(old_vis)
nn, nc, nsp = conc(new_vis)
print(f"== PARTE 3 render (default={rep.get('auto_params',{}) and 'L2'}) ==")
print(f"misfit%={rep.get('misfit_error_percent'):.2f}  chi2={rep.get('chi2_final'):.3f}  maxContrast={maxc:.1f}  floor={floor:.2f}  weakAnomaly={weak}")
print(f"VISIBLE ANTES (piso fijo 0.18):   n={no:5d}  conc<160m={oc*100:3.0f}%  spread={osp:.0f}m")
print(f"VISIBLE DESPUES (piso pico 0.20): n={nn:5d}  conc<160m={nc*100:3.0f}%  spread={nsp:.0f}m")
bt = rep.get("best_target") or {}
print("best_target:", json.dumps({k: bt.get(k) for k in ("x_m","z_m","y_m","density","depth_m","confidence_level")}))
print("overall_verdict.level:", (rep.get("overall_verdict") or {}).get("level"),
      "| depthResolution.computed:", (rep.get("depthResolution") or {}).get("computed"))
