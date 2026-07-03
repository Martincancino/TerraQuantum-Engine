"""
visualizar_datasets.py
======================
Mapas 2D de anomalias gravimetricas y magneticas de los 3 datasets
descargados en la Fase 1 para validacion de TerraQuantum.

Genera un PDF con 7 paneles:
  1. SimPEG Synthetic — Mapa gravimetrico
  2. SimPEG Synthetic — Mapa magnetico
  3. DO-27 Kimberlite — Mapa gravimetrico
  4. DO-27 Kimberlite — Mapa magnetico
  5. Raglan Ni-Sulfide — Mapa magnetico TMI
  6. Raglan Ni-Sulfide — Mapa magnetico (zoom anomalia)
  7. DO-27 — Modelo verdadero de susceptibilidad (slice horizontal)
"""

import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import matplotlib
matplotlib.use("Agg")   # no requiere display
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import Normalize
from matplotlib.ticker import MaxNLocator
import warnings
warnings.filterwarnings("ignore")

# ── Rutas ─────────────────────────────────────────────────────────────────────
BASE  = r"C:\Users\marti\OneDrive\Documentos\TerraQuantum"

SIM_GRAV = os.path.join(BASE, "simpeg_data_joint_inversion", "gravity", "gravity_data.obs")
SIM_GRAV_TRUE = os.path.join(BASE, "simpeg_data_joint_inversion", "gravity", "true_model.txt")
SIM_MAG  = os.path.join(BASE, "simpeg_data_mag", "magnetics", "magnetics_data.obs")
SIM_MAG_TRUE  = os.path.join(BASE, "simpeg_data_mag", "magnetics", "true_model.txt")
SIM_TOPO = os.path.join(BASE, "simpeg_data_joint_inversion", "gravity", "gravity_topo.txt")

DO27_GRAV = os.path.join(BASE, "DO-27_Kimberlite", "Forward", "GRAV_noisydata.obs")
DO27_MAG  = os.path.join(BASE, "DO-27_Kimberlite", "Forward", "MAG_noisydata.obs")
DO27_MESH = os.path.join(BASE, "DO-27_Kimberlite", "Forward", "mesh_inverse_ubc.msh")
DO27_SUS  = os.path.join(BASE, "DO-27_Kimberlite", "Forward", "model_mag.sus")
DO27_DEN  = os.path.join(BASE, "DO-27_Kimberlite", "Forward", "model_grav.den")

RAG_MAG   = os.path.join(BASE, "Raglan_Magnetic", "data", "Raglan_1997", "obs.mag")
RAG_SUS   = os.path.join(BASE, "Raglan_Magnetic", "data", "Raglan_1997", "maginv3d.sus")

OUT_PDF   = os.path.join(BASE, "visualizacion_datasets_geofisicos.pdf")
OUT_PNG   = os.path.join(BASE, "visualizacion_datasets_geofisicos.png")

print("Cargando datos...")

# ── Helpers ────────────────────────────────────────────────────────────────────
def load_xyz_val(fpath, skip_lines=0, comments=("!", "#")):
    """Carga archivo ASCII X Y Z val [std] ignorando headers UBC-GIF."""
    rows = []
    with open(fpath, "r", errors="replace") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            if any(line.startswith(c) for c in comments):
                continue
            parts = line.split()
            # Intentar convertir todas las partes a float
            try:
                vals = [float(p) for p in parts]
                if len(vals) >= 4:
                    rows.append(vals[:5])
                elif len(vals) == 3:
                    rows.append(vals)
            except ValueError:
                continue  # linea de header textual
    return np.array(rows) if rows else None


def load_ubcgif_mag(fpath):
    """Parsea archivo .mag / .obs formato UBC-GIF MAG3D."""
    with open(fpath, "r", errors="replace") as fh:
        lines = fh.readlines()

    # Cabecera: linea 1 = INCL DECL STRENGTH, linea 2 = INCL_anom DECL_anom
    # Linea 3 = N datos; luego X Y Z TMI std
    header = {}
    parts1 = lines[0].split()
    try:
        header["incl"] = float(parts1[0])
        header["decl"] = float(parts1[1])
        header["strength"] = float(parts1[2]) if len(parts1) > 2 else 60000.0
    except:
        pass

    # Buscar linea con N
    data_start = 0
    n_obs = None
    for i, line in enumerate(lines[:8]):
        parts = line.strip().split()
        clean = parts[0] if parts else ""
        if len(parts) == 1 and clean.isdigit():
            n_obs = int(clean)
            data_start = i + 1
            break

    rows = []
    for line in lines[data_start:]:
        line = line.strip()
        if not line or line.startswith("!"):
            continue
        parts = line.split()
        try:
            vals = [float(p) for p in parts[:5]]
            if len(vals) >= 4:
                rows.append(vals)
        except:
            continue
    return np.array(rows) if rows else None, header


def scatter_map(ax, x, y, z, title, cmap, units, vmin=None, vmax=None,
                marker_size=18, xlabel="X (m)", ylabel="Y (m)"):
    """Mapa de puntos con scatter + colorbar."""
    if vmin is None: vmin = np.nanpercentile(z, 2)
    if vmax is None: vmax = np.nanpercentile(z, 98)
    sc = ax.scatter(x, y, c=z, cmap=cmap, s=marker_size,
                    vmin=vmin, vmax=vmax, edgecolors="none", rasterized=True)
    cb = plt.colorbar(sc, ax=ax, pad=0.02, shrink=0.85)
    cb.set_label(units, fontsize=8)
    cb.ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=9, fontweight="bold", pad=4)
    ax.set_xlabel(xlabel, fontsize=7)
    ax.set_ylabel(ylabel, fontsize=7)
    ax.tick_params(labelsize=7)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.25, linewidth=0.5)
    # Marcar maximo y minimo
    imax = np.nanargmax(z)
    imin = np.nanargmin(z)
    ax.plot(x[imax], y[imax], "r^", ms=6, label=f"max={z[imax]:.3f}")
    ax.plot(x[imin], y[imin], "bv", ms=6, label=f"min={z[imin]:.3f}")
    ax.legend(fontsize=6, loc="upper right")
    return sc


def grid_map(ax, xi, yi, zi, title, cmap, units, vmin=None, vmax=None):
    """Mapa interpolado en grilla regular."""
    from scipy.interpolate import griddata
    x_u = np.unique(xi)
    y_u = np.unique(yi)
    X, Y = np.meshgrid(x_u, y_u)
    Z = griddata((xi, yi), zi, (X, Y), method="linear")
    if vmin is None: vmin = np.nanpercentile(zi, 2)
    if vmax is None: vmax = np.nanpercentile(zi, 98)
    im = ax.pcolormesh(X, Y, Z, cmap=cmap, vmin=vmin, vmax=vmax,
                       shading="auto", rasterized=True)
    cb = plt.colorbar(im, ax=ax, pad=0.02, shrink=0.85)
    cb.set_label(units, fontsize=8)
    cb.ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=9, fontweight="bold", pad=4)
    ax.set_xlabel("X (m)", fontsize=7)
    ax.set_ylabel("Y (m)", fontsize=7)
    ax.tick_params(labelsize=7)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.25, linewidth=0.5)
    imax = np.nanargmax(zi)
    imin = np.nanargmin(zi)
    ax.plot(xi[imax], yi[imax], "r^", ms=7, label=f"max={zi[imax]:.4f}")
    ax.plot(xi[imin], yi[imin], "bv", ms=7, label=f"min={zi[imin]:.4f}")
    ax.legend(fontsize=6, loc="upper right")
    ax.contour(X, Y, Z, levels=8, colors="k", linewidths=0.3, alpha=0.5)

# ── Cargar datos ───────────────────────────────────────────────────────────────
print("  [1] SimPEG Synthetic...")
sim_grav = load_xyz_val(SIM_GRAV)      # X Y Z mGal
sim_mag  = load_xyz_val(SIM_MAG)       # X Y Z nT
sim_topo = load_xyz_val(SIM_TOPO)

print("  [2] DO-27 Kimberlite...")
do27_grav = load_xyz_val(DO27_GRAV)    # UBC-GIF grav
do27_mag, do27_hdr  = load_ubcgif_mag(DO27_MAG)
do27_sus  = np.loadtxt(DO27_SUS)       if os.path.exists(DO27_SUS) else None

print("  [3] Raglan Ni-Sulfide...")
rag_mag, rag_hdr = load_ubcgif_mag(RAG_MAG)
rag_sus  = np.loadtxt(RAG_SUS)         if os.path.exists(RAG_SUS) else None

print("Generando figura...")

# ── Figura: 3 filas x 3 columnas ──────────────────────────────────────────────
fig = plt.figure(figsize=(18, 15))
fig.patch.set_facecolor("#0f0f1a")

gs = gridspec.GridSpec(3, 3, figure=fig,
                        hspace=0.45, wspace=0.38,
                        left=0.07, right=0.97, top=0.93, bottom=0.05)

DARK_AX = "#1a1a2e"
TEXT_COLOR = "white"

def style_ax(ax):
    ax.set_facecolor(DARK_AX)
    ax.tick_params(colors=TEXT_COLOR, labelsize=7)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_edgecolor("#444466")

# ── FILA 1: SimPEG Synthetic ──────────────────────────────────────────────────
fig.text(0.5, 0.96,
         "Datasets Geofisicos para Validacion TerraQuantum — Fase 1",
         ha="center", fontsize=13, fontweight="bold", color=TEXT_COLOR)

ax1 = fig.add_subplot(gs[0, 0])
if sim_grav is not None and sim_grav.shape[1] >= 4:
    grid_map(ax1, sim_grav[:,0], sim_grav[:,1], sim_grav[:,3],
             "SimPEG Synthetic\nGravimetria Bouguer", "RdBu_r", "mGal")
    style_ax(ax1)

ax2 = fig.add_subplot(gs[0, 1])
if sim_mag is not None and sim_mag.shape[1] >= 4:
    grid_map(ax2, sim_mag[:,0], sim_mag[:,1], sim_mag[:,3],
             "SimPEG Synthetic\nMagnetometria TMI", "RdYlBu_r", "nT")
    style_ax(ax2)

# Panel de texto con info del dataset
ax3 = fig.add_subplot(gs[0, 2])
ax3.set_facecolor(DARK_AX)
ax3.axis("off")
n_g = sim_grav.shape[0] if sim_grav is not None else "?"
n_m = sim_mag.shape[0]  if sim_mag  is not None else "?"
info_sim = (
    "SIMEPG SYNTHETIC\n"
    "─────────────────────\n"
    "Tipo: Cuerpo sintetico 3D\n"
    "      (alta densidad +\n"
    "       alta susceptibilidad)\n\n"
    f"Observaciones grav: {n_g}\n"
    f"Observaciones mag:  {n_m}\n"
    f"Extension: 160x160 m\n\n"
    "Ground truth:\n"
    "  Modelo verdadero CONOCIDO\n"
    "  -> Comparacion directa\n"
    "     100% verificable\n\n"
    "Formato: ASCII X Y Z val\n"
    "Licencia: MIT (SimPEG)\n"
    "Descarga: GCS bucket\n"
    "Registro: No requerido\n\n"
    "Uso: Validacion basica\n"
    "del motor de inversion"
)
ax3.text(0.05, 0.97, info_sim, transform=ax3.transAxes,
         fontsize=7.5, color=TEXT_COLOR, va="top", fontfamily="monospace",
         bbox=dict(facecolor="#2a2a4a", edgecolor="#5555aa", boxstyle="round,pad=0.5"))

# ── FILA 2: DO-27 Kimberlite ──────────────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 0])
if do27_grav is not None and do27_grav.shape[1] >= 4:
    scatter_map(ax4, do27_grav[:,0], do27_grav[:,1], do27_grav[:,3],
                "DO-27 Kimberlite (NWT, Canada)\nGravimetria (mGal)", "RdBu_r", "mGal",
                marker_size=12)
    style_ax(ax4)

ax5 = fig.add_subplot(gs[1, 1])
if do27_mag is not None and do27_mag.shape[1] >= 4:
    scatter_map(ax5, do27_mag[:,0], do27_mag[:,1], do27_mag[:,3],
                "DO-27 Kimberlite (NWT, Canada)\nMagnetometria TMI (nT)", "RdYlBu_r", "nT",
                marker_size=12)
    style_ax(ax5)

ax6 = fig.add_subplot(gs[1, 2])
ax6.set_facecolor(DARK_AX)
ax6.axis("off")
n_dg = do27_grav.shape[0] if do27_grav is not None else "?"
n_dm = do27_mag.shape[0]  if do27_mag  is not None else "?"
info_do27 = (
    "DO-27 / TLI KWI CHO\n"
    "─────────────────────\n"
    "Tipo: Kimberlita\n"
    "      (cuerpo enterrado)\n"
    "Loc:  NWT, Canada\n\n"
    f"Obs. grav: {n_dg}\n"
    f"Obs. mag:  {n_dm}\n"
    f"Inc. IGRF: {do27_hdr.get('incl','?')} deg\n"
    f"Dec. IGRF: {do27_hdr.get('decl','?')} deg\n\n"
    "Ground truth:\n"
    "  Superficies GoCad (.ts)\n"
    "  de sondajes reales:\n"
    "  HK1, PK1/2/3, VK, Till\n"
    "  Profundidad techo: ~300m\n\n"
    "Formato: UBC-GIF .obs\n"
    "Ref: Astic & Oldenburg 2020\n"
    "     Geophys. J. Int.\n"
    "Licencia: MIT\n"
    "Descarga: Zenodo + GitHub"
)
ax6.text(0.05, 0.97, info_do27, transform=ax6.transAxes,
         fontsize=7.5, color=TEXT_COLOR, va="top", fontfamily="monospace",
         bbox=dict(facecolor="#2a2a4a", edgecolor="#5555aa", boxstyle="round,pad=0.5"))

# ── FILA 3: Raglan Ni-Sulfide ─────────────────────────────────────────────────
ax7 = fig.add_subplot(gs[2, 0])
if rag_mag is not None and rag_mag.shape[1] >= 4:
    scatter_map(ax7, rag_mag[:,0], rag_mag[:,1], rag_mag[:,3],
                "Raglan Ni-Sulfide (Quebec, Canada)\nMagnetometria TMI — Survey completo",
                "RdYlBu_r", "nT", marker_size=5)
    style_ax(ax7)

# Zoom en la anomalia principal
ax8 = fig.add_subplot(gs[2, 1])
if rag_mag is not None and rag_mag.shape[1] >= 4:
    # Filtrar zona de alta anomalia (percentil 90)
    tmi = rag_mag[:,3]
    p90 = np.percentile(tmi, 80)
    mask = tmi >= p90
    xz, yz, vz = rag_mag[mask,0], rag_mag[mask,1], rag_mag[mask,3]
    # Centrar en la anomalia
    cx = (xz.max() + xz.min()) / 2
    cy = (yz.max() + yz.min()) / 2
    half = 2500  # 5km de ventana
    win = ((rag_mag[:,0] > cx-half) & (rag_mag[:,0] < cx+half) &
           (rag_mag[:,1] > cy-half) & (rag_mag[:,1] < cy+half))
    xw, yw, vw = rag_mag[win,0], rag_mag[win,1], rag_mag[win,3]
    scatter_map(ax8, xw, yw, vw,
                "Raglan Ni-Sulfide\nZoom anomalia magnetica principal",
                "hot_r", "nT", marker_size=15)
    style_ax(ax8)

# Panel de info Raglan + modelo invertido
ax9 = fig.add_subplot(gs[2, 2])
ax9.set_facecolor(DARK_AX)
ax9.axis("off")
n_rm = rag_mag.shape[0] if rag_mag is not None else "?"
sus_max = f"{rag_sus.max():.3f}" if rag_sus is not None else "?"
sus_mean = f"{rag_sus[rag_sus > 1e-5].mean():.4f}" if rag_sus is not None else "?"
info_rag = (
    "RAGLAN Ni-Cu-Co SULFIDE\n"
    "─────────────────────\n"
    "Tipo: Sulfuro masivo\n"
    "      en komatiita\n"
    "Loc:  Nunavik, Quebec\n\n"
    f"Obs. magneticas: {n_rm}\n"
    f"Inc. IGRF: {rag_hdr.get('incl','?')} deg\n"
    f"Dec. IGRF: {rag_hdr.get('decl','?')} deg\n"
    f"Fza. IGRF: 60,000 nT\n\n"
    "Modelo de referencia\n"
    "(UBC-GIF MAG3D, 1997):\n"
    f"  Sus. max: {sus_max} SI\n"
    f"  Sus. media: {sus_mean} SI\n"
    f"  16,000 celdas (40x40x10)\n\n"
    "Ground truth:\n"
    "  Resultado MAG3D legacy\n"
    "  Geometria de la mina\n"
    "  (Raglan Mine, Glencore)\n\n"
    "Formato: UBC-GIF .obs/.msh\n"
    "Ref: Transform 2021 Tutorial\n"
    "     Falconbridge Ltd. 1997\n"
    "Solo magnetometria (sin grav)"
)
ax9.text(0.05, 0.97, info_rag, transform=ax9.transAxes,
         fontsize=7.5, color=TEXT_COLOR, va="top", fontfamily="monospace",
         bbox=dict(facecolor="#2a2a4a", edgecolor="#5555aa", boxstyle="round,pad=0.5"))

# ── Guardar ────────────────────────────────────────────────────────────────────
print(f"\nGuardando PNG:  {OUT_PNG}")
plt.savefig(OUT_PNG, dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())

print(f"Guardando PDF:  {OUT_PDF}")
plt.savefig(OUT_PDF, bbox_inches="tight",
            facecolor=fig.get_facecolor())

plt.close()

# ── Segunda figura: Modelo verdadero DO-27 (slice) ────────────────────────────
print("\nGenerando figura 2: Modelos verdaderos DO-27...")

if do27_sus is not None:
    # Leer mesh
    with open(DO27_MESH, "r", errors="replace") as fh:
        mesh_lines = fh.readlines()

    try:
        # Linea 1: nx ny nz
        dims = list(map(int, mesh_lines[0].split()[:3]))
        nx, ny, nz = dims
        # Linea 2: x0 y0 z0
        origin = list(map(float, mesh_lines[1].split()[:3]))
        x0, y0, z0 = origin

        # Lineas 3,4,5: tamanios de celdas (pueden ser "N*val" o lista)
        def parse_cell_sizes(s):
            parts = s.strip().split()
            sizes = []
            for p in parts:
                if "*" in p:
                    n, v = p.split("*")
                    sizes.extend([float(v)] * int(n))
                else:
                    try:
                        sizes.append(float(p))
                    except:
                        pass
            return np.array(sizes)

        dx_arr = parse_cell_sizes(mesh_lines[2])
        dy_arr = parse_cell_sizes(mesh_lines[3])
        dz_arr = parse_cell_sizes(mesh_lines[4])

        # Centros de celdas
        xc = x0 + np.cumsum(dx_arr) - dx_arr/2
        yc = y0 + np.cumsum(dy_arr) - dy_arr/2
        zc = z0 - np.cumsum(dz_arr) + dz_arr/2  # UBC-GIF z positivo hacia arriba

        # Reshape modelo (UBC-GIF: orden xzy)
        n_cells = nx * ny * nz
        if len(do27_sus) >= n_cells:
            sus_3d = do27_sus[:n_cells].reshape((nz, ny, nx), order="C")

            fig2, axes2 = plt.subplots(1, 3, figsize=(16, 5))
            fig2.patch.set_facecolor("#0f0f1a")
            fig2.suptitle("DO-27 Kimberlite — Modelo Verdadero de Susceptibilidad (Ground Truth)\n"
                          "Slices del modelo 3D (formato UBC-GIF) — derivado de sondajes",
                          fontsize=11, fontweight="bold", color="white", y=1.01)

            cmaps = ["plasma", "plasma", "plasma"]
            titles = [
                f"Slice horizontal Z={zc[nz//4]:.0f} m (profundidad)",
                f"Slice horizontal Z={zc[nz//2]:.0f} m (profundidad)",
                f"Slice horizontal Z={zc[3*nz//4]:.0f} m (profundidad)",
            ]
            slices_z = [nz//4, nz//2, 3*nz//4]

            for i, (ax, iz, title) in enumerate(zip(axes2, slices_z, titles)):
                ax.set_facecolor("#1a1a2e")
                Z_slice = sus_3d[iz, :, :]
                vmax_s = np.percentile(Z_slice[Z_slice > 0], 95) if np.any(Z_slice > 0) else 0.01
                im = ax.pcolormesh(xc, yc, Z_slice, cmap="plasma",
                                   vmin=0, vmax=vmax_s, shading="auto")
                cb = plt.colorbar(im, ax=ax, pad=0.02, shrink=0.85)
                cb.set_label("Susceptibilidad (SI)", fontsize=8, color="white")
                cb.ax.tick_params(labelsize=7, colors="white")
                cb.ax.yaxis.set_tick_params(color="white")
                cb.outline.set_edgecolor("white")
                ax.set_title(title, fontsize=9, color="white", fontweight="bold")
                ax.set_xlabel("X (m)", fontsize=8, color="white")
                ax.set_ylabel("Y (m)", fontsize=8, color="white")
                ax.tick_params(colors="white", labelsize=7)
                ax.contour(xc, yc, Z_slice, levels=[0.01, 0.05, 0.1],
                           colors="cyan", linewidths=0.8, alpha=0.7)
                ax.set_aspect("equal")
                for spine in ax.spines.values():
                    spine.set_edgecolor("#444466")

            plt.tight_layout()
            OUT_PNG2 = os.path.join(BASE, "modelo_verdadero_DO27.png")
            plt.savefig(OUT_PNG2, dpi=150, bbox_inches="tight",
                        facecolor=fig2.get_facecolor())
            plt.close()
            print(f"Guardado: {OUT_PNG2}")

    except Exception as e:
        print(f"  [WARN] No se pudo generar slices del modelo DO-27: {e}")

# ── Figura 3: Perfil 1D de las anomalias ─────────────────────────────────────
print("\nGenerando figura 3: Perfiles 1D sobre el maximo...")

fig3, axes3 = plt.subplots(1, 3, figsize=(15, 4))
fig3.patch.set_facecolor("#0f0f1a")
fig3.suptitle("Perfiles 1D de Anomalia sobre el Cuerpo Mineralizado",
              fontsize=11, fontweight="bold", color="white")

profile_data = [
    (sim_grav,  "SimPEG Synthetic — Gravimetria", "mGal",  "RdBu_r",    0),
    (do27_grav, "DO-27 — Gravimetria",             "mGal",  "RdBu_r",    0),
    (rag_mag,   "Raglan — Magnetometria TMI",       "nT",    "RdYlBu_r",  0),
]

for ax, (data, title, units, cmap, col) in zip(axes3, profile_data):
    ax.set_facecolor("#1a1a2e")
    if data is None or data.shape[1] < 4:
        ax.text(0.5, 0.5, "Sin datos", ha="center", color="white", transform=ax.transAxes)
        continue

    x, y, val = data[:,0], data[:,1], data[:,3]

    # Encontrar el perfil que cruza el maximo
    imax = np.argmax(val)
    y_max = y[imax]
    # Seleccionar puntos en esa linea (+-2 unidades en Y)
    tol_y = (y.max() - y.min()) / len(np.unique(y)) * 1.5 if len(np.unique(y)) > 1 else 200
    mask = np.abs(y - y_max) < tol_y
    if mask.sum() < 3:
        mask = np.ones(len(y), dtype=bool)

    xp, vp = x[mask], val[mask]
    sort_idx = np.argsort(xp)
    xp, vp = xp[sort_idx], vp[sort_idx]

    ax.plot(xp, vp, color="#00d4ff", linewidth=1.5, label="Anomalia")
    ax.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax.fill_between(xp, 0, vp, where=(vp > 0),
                    color="#00d4ff", alpha=0.2, label="Positivo")
    ax.fill_between(xp, 0, vp, where=(vp < 0),
                    color="#ff6b6b", alpha=0.2, label="Negativo")
    ax.axvline(xp[np.argmax(vp)], color="#ffd700", linewidth=1,
               linestyle="--", alpha=0.7, label=f"Pico: {vp.max():.3f}")

    ax.set_title(title, fontsize=9, color="white", fontweight="bold")
    ax.set_xlabel("X (m)", fontsize=8, color="white")
    ax.set_ylabel(units, fontsize=8, color="white")
    ax.tick_params(colors="white", labelsize=7)
    ax.legend(fontsize=6, facecolor="#2a2a4a", labelcolor="white", edgecolor="#5555aa")
    ax.grid(True, alpha=0.2, linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_edgecolor("#444466")

plt.tight_layout()
OUT_PNG3 = os.path.join(BASE, "perfiles_anomalia_1D.png")
plt.savefig(OUT_PNG3, dpi=150, bbox_inches="tight",
            facecolor=fig3.get_facecolor())
plt.close()
print(f"Guardado: {OUT_PNG3}")

# ── Resumen ────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("ARCHIVOS GENERADOS:")
print("="*60)
for f in [OUT_PNG, OUT_PDF, 
          os.path.join(BASE, "modelo_verdadero_DO27.png"),
          OUT_PNG3]:
    if os.path.exists(f):
        kb = os.path.getsize(f) / 1024
        print(f"  [OK] {os.path.basename(f):50s}  {kb:.0f} KB")
    else:
        print(f"  [--] {os.path.basename(f)}")
print("\nListo. Abrir los PNG para ver los resultados.")
