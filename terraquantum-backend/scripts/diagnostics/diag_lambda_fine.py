"""Sweep fino de λ (compact) + métricas ROBUSTAS de compacidad:
- chi2/misfit (salud del ajuste)
- core_frac: % de masa-contraste dentro de 2 celdas del pico (compacidad robusta)
- vis_fe: nº de celdas que el FRONTEND mostraría (malla COMPLETA, |ρ-fondo|/escala >= 0.18)
- spread_core: spread solo de las celdas dentro de 3 celdas del pico."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np, pandas as pd
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
src = os.path.join(os.path.dirname(__file__), "..", "prueba_gravimetria_v2.tqpkg")
text = open(src, "r", encoding="utf-8").read()

def patch_cfg(text, **kw):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("#CONFIG "):
            cfg = json.loads(ln[len("#CONFIG "):]); cfg.update(kw)
            lines[i] = "#CONFIG " + json.dumps(cfg); break
    return "\n".join(lines) + "\n"

def latest(name):
    fs = glob.glob(f"data/projects/pkg_*/runs/*/{name}")
    fs.sort(key=os.path.getmtime); return fs[-1]

def metrics():
    # malla COMPLETA para conteo visible estilo frontend
    full = pd.read_parquet(latest("block_model.parquet"))
    d = full["density_t_m3"].to_numpy() if "density_t_m3" in full else full["density"].to_numpy()
    bg = np.nanmedian(d)
    # escala robusta simétrica como el frontend (P5/P95 vs mediana)
    p95 = np.nanpercentile(d, 95); p05 = np.nanpercentile(d, 5)
    scale = max(p95 - bg, bg - p05, 0.05)
    cmag = np.abs(d - bg) / scale
    vis_fe = int((cmag >= 0.18).sum())
    # compacidad sobre la malla completa (contraste positivo)
    c = np.clip(d - bg, 0, None)
    x = full["x_m"].to_numpy(); y = full["y_m"].to_numpy(); z = full["z_m"].to_numpy()
    bs = float(np.median(np.diff(np.unique(x))))
    pk = int(np.argmax(c))
    px, py, pz = x[pk], y[pk], z[pk]
    dist = np.sqrt((x-px)**2 + (z-pz)**2)
    strong = c > 0.3
    tot = c[strong].sum() if strong.any() else 1e-9
    core_frac = c[strong & (dist <= 2*bs)].sum() / tot if strong.any() else 0.0
    sc = strong & (dist <= 3*bs)
    if sc.any():
        w = c[sc]; xx = x[sc]; zz = z[sc]
        cx = (w*xx).sum()/w.sum(); cz = (w*zz).sum()/w.sum()
        spread_core = np.sqrt((w*((xx-cx)**2+(zz-cz)**2)).sum()/w.sum())
    else:
        spread_core = float('nan')
    return dict(bs=bs, vis_fe=vis_fe, n_strong=int(strong.sum()),
                core_frac=core_frac, spread_core=spread_core,
                peak=(round(px), round(pz)))

print(f"{'lambda':>7} {'misfit%':>8} {'chi2':>7} {'n>0.3':>6} {'vis_FE':>7} {'core%<2cel':>10} {'spread_core':>11} peak  bs")
for lam in (0.0, 0.5, 0.6, 0.7, 0.8, 1.0):
    txt = patch_cfg(text, regularization_norm="compact", lambda_mag=lam)
    r = client.post("/v2/gravity-import/load-package",
                    files={"file": ("p.tqpkg", txt.encode(), "text/csv")})
    rep = (r.json().get("inversionResult") or r.json()).get("report") or r.json()
    m = metrics()
    tag = "(moroz)" if lam == 0 else ""
    print(f"{lam:>7.2f} {rep.get('misfit_error_percent'):>8.2f} {rep.get('chi2_final'):>7.3f} "
          f"{m['n_strong']:>6} {m['vis_fe']:>7} {m['core_frac']*100:>9.0f}% "
          f"{m['spread_core']:>11.0f} {m['peak']} {m['bs']:.0f} {tag}")
