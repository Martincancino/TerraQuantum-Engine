"""Comparación DECISIVA y limpia: L2-morozov vs compact-morozov vs compact-λ1.0.
Métrica no-confundida: sobre malla core COMPLETA, anomalía ABSOLUTA (ρ-2.6 > THR),
concentración HORIZONTAL alrededor del centro verdadero (760,760) ignorando z=prof
(null-space honesto). Reporta n_anom, % concentrado <160m (~4 celdas), mass_frac."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np, pandas as pd
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
src = os.path.join(os.path.dirname(__file__), "..", "prueba_gravimetria_v2.tqpkg")
text = open(src, "r", encoding="utf-8").read()
TRUE = (760.0, 760.0); THR = 0.5; RAD = 160.0

def patch_cfg(text, **kw):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("#CONFIG "):
            cfg = json.loads(ln[len("#CONFIG "):]); cfg.update(kw)
            lines[i] = "#CONFIG " + json.dumps(cfg); break
    return "\n".join(lines) + "\n"

def metrics():
    fs = glob.glob("data/projects/pkg_*/runs/*/block_model.parquet")
    fs.sort(key=os.path.getmtime)
    df = pd.read_parquet(fs[-1])
    d = df["density_t_m3"].to_numpy() if "density_t_m3" in df else df["density"].to_numpy()
    x = df["x_m"].to_numpy(); z = df["z_m"].to_numpy()
    c = d - 2.6
    anom = c > THR
    n = int(anom.sum())
    if n == 0:
        return dict(n=0, conc=0.0, massfrac=0.0)
    dist = np.sqrt((x-TRUE[0])**2 + (z-TRUE[1])**2)
    near = anom & (dist <= RAD)
    conc = int(near.sum())/n
    massfrac = c[near].sum()/c[anom].sum()
    return dict(n=n, n_near=int(near.sum()), conc=conc, massfrac=massfrac)

configs = [
    ("L2  +morozov", dict(regularization_norm="L2",      lambda_mag=0.0)),
    ("comp+morozov", dict(regularization_norm="compact", lambda_mag=0.0)),
    ("comp+lam=1.0", dict(regularization_norm="compact", lambda_mag=1.0)),
]
print(f"{'config':>14} {'misfit%':>8} {'chi2':>7} {'n_anom':>7} {'n<160m':>7} {'conc%':>6} {'massfrac%':>9}")
for name, kw in configs:
    txt = patch_cfg(text, **kw)
    r = client.post("/v2/gravity-import/load-package", files={"file": ("p.tqpkg", txt.encode(), "text/csv")})
    rep = (r.json().get("inversionResult") or r.json()).get("report") or r.json()
    m = metrics()
    print(f"{name:>14} {rep.get('misfit_error_percent'):>8.2f} {rep.get('chi2_final'):>7.3f} "
          f"{m['n']:>7} {m.get('n_near',0):>7} {m['conc']*100:>5.0f}% {m['massfrac']*100:>8.0f}%")
