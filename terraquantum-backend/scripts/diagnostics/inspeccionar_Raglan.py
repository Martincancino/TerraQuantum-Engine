"""
Inspeccion de los datos del Raglan Ni-Sulfide Deposit (Transform 2021)
Datos magneticos reales de 1997 (Falconbridge Ltd.)
"""
import sys, io, os, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = r"C:\Users\marti\OneDrive\Documentos\TerraQuantum\Raglan_Magnetic"
DATA = os.path.join(BASE, "data", "Raglan_1997")

print("="*65)
print("RAGLAN Ni-Cu-Co SULFIDE -- Datos Magneticos Reales (1997)")
print("Deposito: Cape Smith Belt, Nunavik, Quebec, Canada")
print("Datos originales: Falconbridge Ltd.")
print("Tutorial: Transform 2021 (SWUNG / SimPEG)")
print("="*65)

# ============================================================
# README
# ============================================================
readme = os.path.join(BASE, "README.md")
print(f"\n{'='*55}")
print("  README del repositorio:")
print(f"{'='*55}")
with open(readme, "r", errors="replace") as fh:
    print(fh.read())

# ============================================================
# 1. obs.mag -- Observaciones magneticas
# ============================================================
obs_path = os.path.join(DATA, "obs.mag")
print(f"\n{'='*55}")
print("  MAGNETOMETRIA: obs.mag")
print(f"{'='*55}")
size_kb = os.path.getsize(obs_path) / 1024
print(f"  Tamano: {size_kb:.1f} KB")

with open(obs_path, "r", errors="replace") as fh:
    lines = [l.rstrip() for l in fh.readlines()]

print(f"  Total lineas: {len(lines)}")
print(f"\n  Primeras 15 lineas (formato UBC-GIF MAG3D):")
for i, l in enumerate(lines[:15]):
    print(f"    {i+1:3d}: {l}")

# Parsear header UBC-GIF para magnetometria
# Formato: INCL DECL IGRF_STRENGTH  (primera linea)
# Luego: INCL_obj DECL_obj  (segunda linea)
# Luego: N_datos
# Luego: X Y Z TMI std
print(f"\n  Interpretacion del formato UBC-GIF (MAG3D):")
try:
    # Linea 1: campo inductor
    parts1 = lines[0].split()
    print(f"  Campo inductor IGRF:")
    print(f"    Inclinacion: {parts1[0]} deg")
    print(f"    Declinacion: {parts1[1]} deg")
    if len(parts1) >= 3:
        print(f"    Intensidad:  {parts1[2]} nT")

    # Buscar linea con numero de observaciones
    n_obs = None
    header_end = 0
    for i, l in enumerate(lines[:10]):
        parts = l.split()
        if len(parts) == 1 and parts[0].isdigit():
            n_obs = int(parts[0])
            header_end = i + 1
            print(f"\n  Numero de observaciones: {n_obs}")
            break

    # Parsear datos
    if n_obs:
        data_lines = lines[header_end:header_end + n_obs]
        data = []
        for l in data_lines:
            parts = l.split()
            if len(parts) >= 4:
                try:
                    data.append([float(p) for p in parts[:5]])
                except:
                    pass
        if data:
            data = np.array(data)
            ncols = data.shape[1]
            labels = ["X (E, m)", "Y (N, m)", "Z (elev, m)", "TMI (nT)", "std (nT)"]
            print(f"\n  Datos: {data.shape[0]} obs x {ncols} columnas")
            print(f"  Columnas: X  Y  Z  TMI  std")
            for i in range(min(ncols, 5)):
                lbl = labels[i] if i < len(labels) else f"Col{i}"
                print(f"    {lbl:20s}: min={data[:,i].min():.2f}  max={data[:,i].max():.2f}  mean={data[:,i].mean():.2f}")

            dx = data[:,0].max() - data[:,0].min()
            dy = data[:,1].max() - data[:,1].min()
            dz = data[:,2].max() - data[:,2].min()
            print(f"\n  Extension del survey:")
            print(f"    E-O: {dx:.0f} m  ({dx/1000:.2f} km)")
            print(f"    N-S: {dy:.0f} m  ({dy/1000:.2f} km)")
            print(f"    Z:   {dz:.0f} m  (variacion de altitud)")
            print(f"\n  Anomalia magnetica TMI:")
            print(f"    Rango: {data[:,3].min():.1f} a {data[:,3].max():.1f} nT")
            print(f"    Amplitud pico-pico: {data[:,3].max()-data[:,3].min():.1f} nT")

            # Posicion central aproximada
            cx = (data[:,0].max() + data[:,0].min()) / 2
            cy = (data[:,1].max() + data[:,1].min()) / 2
            print(f"\n  Centro del survey: X={cx:.0f} m, Y={cy:.0f} m (coordenadas locales)")
except Exception as e:
    print(f"  [ERROR al parsear]: {e}")

# ============================================================
# 2. mesh.msh -- Malla de inversion
# ============================================================
mesh_path = os.path.join(DATA, "mesh.msh")
print(f"\n{'='*55}")
print("  MALLA DE INVERSION: mesh.msh (formato UBC-GIF)")
print(f"{'='*55}")
with open(mesh_path, "r", errors="replace") as fh:
    mesh_lines = fh.readlines()
print(f"  Contenido completo ({len(mesh_lines)} lineas):")
for l in mesh_lines:
    print(f"    {l.rstrip()}")
print(f"  -> Formato: nx ny nz / x0 y0 z0 / dx dy dz")

# ============================================================
# 3. maginv3d.sus -- Modelo invertido (resultado de referencia MAG3D legacy)
# ============================================================
sus_path = os.path.join(DATA, "maginv3d.sus")
print(f"\n{'='*55}")
print("  MODELO INVERTIDO (referencia): maginv3d.sus")
print(f"  Este es el RESULTADO de la inversion UBC-GIF MAG3D (1997)")
print(f"  Susceptibilidad en SI por celda de la malla")
print(f"{'='*55}")
size_kb = os.path.getsize(sus_path) / 1024
print(f"  Tamano: {size_kb:.1f} KB")

try:
    sus_data = np.loadtxt(sus_path)
    print(f"  Num. celdas: {len(sus_data)}")
    print(f"  Susceptibilidad (SI):")
    nonzero = sus_data[sus_data > 1e-6]
    print(f"    Min:     {sus_data.min():.6f}")
    print(f"    Max:     {sus_data.max():.6f}")
    print(f"    Media:   {sus_data.mean():.6f}")
    print(f"    >0 (cuerpo): {len(nonzero)} celdas ({100*len(nonzero)/len(sus_data):.1f}%)")
    if len(nonzero) > 0:
        print(f"    Sus media cuerpo: {nonzero.mean():.4f} SI")
        print(f"    Sus max cuerpo:   {nonzero.max():.4f} SI")
except Exception as e:
    print(f"  [ERROR]: {e}")

# ============================================================
# 4. inv.inp -- Parametros de inversion de referencia
# ============================================================
inp_path = os.path.join(DATA, "inv.inp")
print(f"\n{'='*55}")
print("  PARAMETROS DE INVERSION DE REFERENCIA: inv.inp")
print(f"{'='*55}")
with open(inp_path, "r", errors="replace") as fh:
    print(fh.read())

# ============================================================
# 5. Resumen para TerraQuantum
# ============================================================
print(f"\n{'='*65}")
print("  RESUMEN PARA TerraQuantum")
print(f"{'='*65}")
print("""
DEPOSITO: Raglan Ni-Cu-Co Sulfide
  Tipo:       Sulfuro masivo en roca ultramafica (komatiita)
  Ubicacion:  Cape Smith Belt, Nunavik (Quebec norte), Canada
  Profundidad techo: ~200-400 m bajo superficie
  Geometria:  Cuerpo tabular N-S, buzamiento ~70 grados
  Prop. fisicas: Alta susceptibilidad magnetica (minerales magneticos
                 asociados a la roca huesped ultramafica)

DATOS DISPONIBLES:
  obs.mag        -> Observaciones TMI reales (nT) con X/Y/Z
                    Formato UBC-GIF (listo para inversion)
  maginv3d.sus   -> Resultado de referencia UBC-GIF MAG3D (1997)
                    = susceptibilidad invertida por celda

COMO USAR EN TerraQuantum:
  Input:  obs.mag + mesh.msh
  Output: modelo 3D de susceptibilidad
  Validar: comparar geometria del cuerpo recuperado vs.
           resultado de referencia maginv3d.sus (inversion legacy MAG3D)
  NOTA: No hay archivo de sondajes en el repo, pero la geometria
        del cuerpo magnetico esta bien documentada en la literatura
        Raglan Mine y en los notebooks del tutorial (figuras de seccion)

LIMITACION IMPORTANTE:
  Solo magnetometria (sin gravimetria).
  Util para validar el componente magnetico de TerraQuantum
  de forma independiente.

Notebooks con el flujo completo de inversion:
  1-magnetic-inversion-raglan-reproduce.ipynb  (285 KB)
  3-magnetic-inversion-raglan-lp.ipynb         (253 KB)
  Incluyen figuras del resultado contra la geologia conocida.

PDFs del tutorial:
  pdfs/inversion-for-geologists-part1.pdf  (3.7 MB)
  pdfs/inversion-for-geologists-part2.pdf  (3.1 MB)
""")

print("Inspeccion completada.")
