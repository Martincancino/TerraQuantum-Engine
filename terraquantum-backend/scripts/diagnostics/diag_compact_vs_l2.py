"""Prueba HONESTA: el mismo cuerpo (v2) invertido con L2 suave (default actual del
paquete) vs norma COMPACTA (minimum-support, ya en el motor pero off/no-cableada).
Mide cuán concentrado queda el cuerpo recuperado en cada caso."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from exploration.gravimetry import GravimetryForward, GravimetryInversion

G = 6.67430e-11
SPACING = 80.0; NX = NY = 20; R, DRHO, DEPTH = 90.0, 1500.0, 100.0
CX = CZ = (NX - 1) * SPACING / 2.0
mass = (4/3)*np.pi*R**3*DRHO
rng = np.random.default_rng(7)

# estaciones + dato (esfera)
sx, sz, g_obs = [], [], []
for j in range(NY):
    for i in range(NX):
        x, z = i*SPACING, j*SPACING
        r = np.sqrt((x-CX)**2 + (z-CZ)**2 + DEPTH**2)
        g = G*mass*DEPTH/r**3 + rng.normal(0, 0.01)*1e-5
        sx.append(x); sz.append(z); g_obs.append(g)
g_obs = np.array(g_obs)
# sensores: x=este, z=norte, y=0 (superficie). Motor: x,y,z con y=prof.
sensors = np.column_stack([sx, np.zeros(len(sx)), sz])

# malla 30x16x30 @ 50m (cubre 1500m lateral, 800m prof)
nx=nz=30; ny=16; bs=50.0
inv = GravimetryInversion(nx, ny, nz, bs, base_density=2.6)
fwd = GravimetryForward(bs, bs, bs, cutoff_radius=2000.0)
xs = (np.arange(nx)+0.5)*bs; ys=(np.arange(ny)+0.5)*bs; zs=(np.arange(nz)+0.5)*bs
gx,gy,gz = np.meshgrid(xs,ys,zs, indexing='ij')
x_c=gx.ravel(order='F'); y_c=gy.ravel(order='F'); z_c=gz.ravel(order='F')

def run(norm):
    d,_,mis,_ = inv.solve_inversion_lsqr(
        g_observed=g_obs, kernel_sparse=None, y_c=y_c,
        lambda_mag=0.5, alpha_spatial=1.0, sensor_coords=sensors,
        x_c=x_c, z_c=z_c, forward_model=fwd,
        density_min=2.6, density_max=5.5, regularization_norm=norm,
    )
    dens = d.copy(); contrast = np.nan_to_num(dens-2.6, nan=0.0)
    contrast = np.clip(contrast, 0, None)
    total = contrast.sum()
    # concentración: fracción de masa-contraste en las celdas top (más densas)
    order = np.argsort(-contrast)
    top20 = contrast[order[:int(0.02*len(contrast))]].sum()/max(total,1e-12)
    n_strong = int((contrast > 0.3).sum())
    # spread espacial de las celdas fuertes alrededor del centro verdadero (760,_,760)
    strong = contrast > 0.3
    if strong.any():
        xx,zz = x_c[strong], z_c[strong]
        w = contrast[strong]
        cxr = (w*xx).sum()/w.sum(); czr=(w*zz).sum()/w.sum()
        spread = np.sqrt((w*((xx-cxr)**2+(zz-czr)**2)).sum()/w.sum())
    else:
        cxr=czr=spread=float('nan')
    return dict(misfit=mis, dmax=float(np.nanmax(dens)), n_strong=n_strong,
               frac_top2pct=float(top20), spread_m=float(spread),
               centroid=(float(cxr), float(czr)))

for norm in ("L2", "compact"):
    r = run(norm)
    print(f"[{norm:8s}] misfit={r['misfit']:.1f}% dmax={r['dmax']:.2f} "
          f"n(contrast>0.3)={r['n_strong']:4d} masa_en_top2%={r['frac_top2pct']*100:.0f}% "
          f"spread={r['spread_m']:.0f}m centroide=({r['centroid'][0]:.0f},{r['centroid'][1]:.0f}) [verdad ~760,760]")
