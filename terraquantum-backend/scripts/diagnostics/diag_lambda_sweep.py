"""Barre lambda_mag (FIJO, desactiva Morozov) con regularization_norm=compact por
el flujo REAL /load-package y mide spread/misfit/chi² del cuerpo recuperado.
Objetivo: encontrar el operating point (piso de λ) que entregue un cuerpo nítido."""
import os, sys, json, glob, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np, pandas as pd
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
src = os.path.join(os.path.dirname(__file__), "..", "prueba_gravimetria_v2.tqpkg")
with open(src, "r", encoding="utf-8") as f:
    text = f.read()

def patch_cfg(text, **kw):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("#CONFIG "):
            cfg = json.loads(ln[len("#CONFIG "):])
            cfg.update(kw)
            lines[i] = "#CONFIG " + json.dumps(cfg)
            break
    return "\n".join(lines) + "\n"

def measure():
    runs = glob.glob("data/projects/pkg_*/runs/*/block_model_anomaly.parquet")
    runs.sort(key=os.path.getmtime)
    df = pd.read_parquet(runs[-1])
    c = df["density_contrast_t_m3"].to_numpy()
    x = df["x_m"].to_numpy(); z = df["z_m"].to_numpy()
    m = c > 0.3
    out = dict(n_payload=len(df), dmax=float(np.nanmax(c)), n_strong=int(m.sum()))
    if m.sum():
        w = c[m]; xx = x[m]; zz = z[m]
        cx = (w*xx).sum()/w.sum(); cz = (w*zz).sum()/w.sum()
        out["spread"] = float(np.sqrt((w*((xx-cx)**2+(zz-cz)**2)).sum()/w.sum()))
        out["centroid"] = (round(cx), round(cz))
    return out

print(f"{'lambda':>10} {'norm':>8} {'misfit%':>8} {'chi2':>7} {'n>0.3':>6} {'dmax':>5} {'spread_m':>9} centroid")
for norm in ("compact",):
    for lam in (0.0, 0.1, 0.3, 0.5, 1.0, 2.0, 5.0):
        txt = patch_cfg(text, regularization_norm=norm, lambda_mag=lam)
        r = client.post("/v2/gravity-import/load-package",
                        files={"file": ("p.tqpkg", txt.encode(), "text/csv")})
        rep = (r.json().get("inversionResult") or r.json()).get("report") or r.json()
        mm = measure()
        tag = "(morozov)" if lam == 0.0 else ""
        print(f"{lam:>10.2f} {norm:>8} {rep.get('misfit_error_percent'):>8.2f} "
              f"{rep.get('chi2_final'):>7.3f} {mm['n_strong']:>6} {mm['dmax']:>5.2f} "
              f"{mm.get('spread', float('nan')):>9.0f} {mm.get('centroid')} {tag}")
