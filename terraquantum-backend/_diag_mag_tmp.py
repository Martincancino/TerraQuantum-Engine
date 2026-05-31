import os, sys, io, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion

NX, NY, NZ, B = 12, 8, 12, 10.0
gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
ix, iy, iz = gx.flatten(order='F'), gy.flatten(order='F'), gz.flatten(order='F')
xc, yc, zc = ix*B+B/2, iy*B+B/2, iz*B+B/2
sx, sz = np.meshgrid(np.linspace(10, 110, 8), np.linspace(10, 110, 8))
sc = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
fwd = MagnetometryForward(B, B, B, 200.0, -30, 2, 23500)
st = np.zeros(len(xc)); st[((xc-60)**2 + (yc-40)**2 + (zc-60)**2) < 400] = 0.1
G = fwd.build_sparse_kernel(xc, yc, zc, sc); d = G @ st

print("verdad: blob centro (x=60, y=40, z=60), k=0.1")
for beta in [0.0, 1.0, 2.0, 3.0]:
    inv = MagnetometryInversion(NX, NY, NZ, B); m = {}
    with contextlib.redirect_stdout(io.StringIO()):
        se, _, mf, _ = inv.solve_magnetic_inversion_lsqr(
            d, yc, 1e-4, 1.0, forward_model=fwd, sensor_coords=sc,
            x_c=xc, z_c=zc, depth_beta=beta, solver_meta=m)
    sec = np.nan_to_num(se); pk = int(np.argmax(sec))
    # profundidad del centro de masa de susceptibilidad
    com_y = float(np.sum(sec*yc)/max(np.sum(sec), 1e-30))
    print(f"beta={beta}: peak@(x={xc[pk]:.0f},y={yc[pk]:.0f},z={zc[pk]:.0f}) "
          f"kmax={sec.max():.3f} com_y={com_y:.0f} misfit={mf:.3f}% "
          f"cond={m['acond']:.1e} sat={m['sat_fraction']:.0%}")
