"""
Inspeccion de los datos del DO-27 Kimberlite (Astic 2020)
Dataset real con ground truth de sondajes.
"""
import sys, io, os, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = r"C:\Users\marti\OneDrive\Documentos\TerraQuantum\DO-27_Kimberlite"

print("="*65)
print("DO-27 KIMBERLITE -- Inspeccion de datos")
print("Paper: Astic & Oldenburg (2020), GJI 220(2), 1138-1153")
print("="*65)

# ============================================================
# 1. Datos de observacion Gravimetria y Magnetometria
# ============================================================

files_to_inspect = {
    "GRAVIMETRIA (.obs)":        r"Forward\GRAV_noisydata.obs",
    "MAGNETOMETRIA (.obs)":      r"Forward\MAG_noisydata.obs",
    "TOPOGRAFIA":                r"Geology_Surfaces\TKCtopo.dat",
    "MODELO GRAV (verdad)":      r"Forward\model_grav.den",
    "MODELO MAG (verdad)":       r"Forward\model_mag.sus",
    "MESH inversa":              r"Forward\mesh_inverse_ubc.msh",
}

def inspect(rel_path, label):
    fpath = os.path.join(BASE, rel_path)
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"  Archivo: {rel_path}")
    print(f"{'='*55}")

    if not os.path.exists(fpath):
        print("  [NO ENCONTRADO]")
        return None

    size_kb = os.path.getsize(fpath) / 1024
    print(f"  Tamano: {size_kb:.1f} KB")

    try:
        with open(fpath, "r", errors="replace") as fh:
            lines = [l.rstrip() for l in fh.readlines()]

        print(f"  Total lineas: {len(lines)}")
        print(f"\n  Primeras 10 lineas (cabecera / formato):")
        for i, l in enumerate(lines[:10]):
            print(f"    {i+1:3d}: {l}")

        # Intentar parsear como numerico (ignorando headers)
        numeric_lines = []
        for l in lines:
            stripped = l.strip()
            if stripped and not stripped.startswith("!") and not stripped.startswith("#"):
                parts = stripped.split()
                try:
                    vals = [float(p) for p in parts]
                    if len(vals) >= 1:
                        numeric_lines.append(vals)
                except:
                    pass

        if numeric_lines:
            max_cols = max(len(r) for r in numeric_lines)
            # Filtrar filas con el numero de columnas predominante
            col_count = {}
            for r in numeric_lines:
                col_count[len(r)] = col_count.get(len(r), 0) + 1
            dominant_cols = max(col_count, key=col_count.get)
            data_rows = [r for r in numeric_lines if len(r) == dominant_cols]

            if data_rows:
                data = np.array(data_rows)
                nrows, ncols = data.shape
                print(f"\n  Datos numericos: {nrows} filas x {ncols} columnas")
                for i in range(ncols):
                    print(f"    Col {i}: min={data[:,i].min():.4f}  max={data[:,i].max():.4f}  mean={data[:,i].mean():.4f}")

                if ncols >= 3:
                    dx = data[:,0].max() - data[:,0].min()
                    dy = data[:,1].max() - data[:,1].min()
                    print(f"\n  Extension X: {dx:.1f} m   Extension Y: {dy:.1f} m")
                if ncols >= 4:
                    val_range = data[:,3].max() - data[:,3].min()
                    print(f"  Rango anomalia (Col3): {val_range:.6f}")

        return lines

    except Exception as e:
        print(f"  [ERROR] {e}")
        return None

for label, rel in files_to_inspect.items():
    inspect(rel, label)

# ============================================================
# 2. Superficies geologicas (ground truth de sondajes)
# ============================================================
print(f"\n{'='*65}")
print("  SUPERFICIES GEOLOGICAS (Ground Truth de sondajes)")
print(f"{'='*65}")

geo_dir = os.path.join(BASE, "Geology_Surfaces")
for f in sorted(os.listdir(geo_dir)):
    fpath = os.path.join(geo_dir, f)
    size_kb = os.path.getsize(fpath) / 1024
    ext = os.path.splitext(f)[1].lower()
    desc = {
        ".ts":   "-> Superficie triangulada (GoCad format) -- GEOMETRIA 3D",
        ".vtp":  "-> VTK PolyData (visualizacion 3D)",
        ".vtu":  "-> VTK UnstructuredGrid (malla 3D)",
        ".dat":  "-> Datos ASCII",
    }.get(ext, "")
    print(f"  {f:40s}  {size_kb:8.1f} KB  {desc}")

# ============================================================
# 3. Resumen de facies geologicas del DO-27
# ============================================================
print(f"\n{'='*65}")
print("  FACIES GEOLOGICAS IDENTIFICADAS (Ground Truth)")
print(f"{'='*65}")

facies = {
    "HK1.ts":  "HK = Hypabyssal Kimberlite (kimberlita hipabisal, densa, magnetica)",
    "PK1.ts":  "PK1 = Pyroclastic Kimberlite fase 1 (menos densa)",
    "PK2.ts":  "PK2 = Pyroclastic Kimberlite fase 2",
    "PK3.ts":  "PK3 = Pyroclastic Kimberlite fase 3",
    "VK.ts":   "VK = Volcaniclastic Kimberlite (mas somera)",
    "Till.ts": "Till = Glacial till (cubierta superficial)",
}

for f, desc in facies.items():
    fpath = os.path.join(geo_dir, f)
    exists = "[OK]" if os.path.exists(fpath) else "[NO]"
    size = os.path.getsize(fpath)/1024 if os.path.exists(fpath) else 0
    print(f"  {exists} {f:12s} ({size:6.1f} KB) -- {desc}")

# Inspeccionar un .ts para ver el formato
ts_path = os.path.join(geo_dir, "HK1.ts")
if os.path.exists(ts_path):
    print(f"\n  Primeras 15 lineas de HK1.ts (superficie HK ground truth):")
    with open(ts_path, "r", errors="replace") as fh:
        for i, l in enumerate(fh):
            if i >= 15: break
            print(f"    {i+1:3d}: {l.rstrip()}")

# ============================================================
# 4. Resumen ejecutivo
# ============================================================
print(f"\n{'='*65}")
print("  RESUMEN EJECUTIVO PARA TerraQuantum")
print(f"{'='*65}")
print("""
DATOS DISPONIBLES:
  [GRAV] GRAV_noisydata.obs  -- Observaciones gravimetricas con ruido
  [MAG]  MAG_noisydata.obs   -- Observaciones magneticas TMI con ruido
  [TOPO] TKCtopo.dat         -- Topografia del area DO-27 (Lac de Gras, NWT)
  [MESH] mesh_inverse_ubc.msh -- Malla de inversion (formato UBC-GIF)
  [TRUE] model_grav.den      -- Modelo verdadero de densidad (ground truth)
  [TRUE] model_mag.sus       -- Modelo verdadero de susceptibilidad (ground truth)

GROUND TRUTH GEOMETRICO (superficies de sondajes):
  HK1.ts  -- Superficie techo/base de kimberlita hipabisal (~-300 a -700 m)
  PK1/2/3.ts -- Diferentes facies kimberlitas (piroclaicas)
  VK.ts   -- Kimberlita volcanoclastica
  Formato .ts = GoCad triangulated surface (ASCII legible)

COMO USAR EN TerraQuantum:
  1. Input:  GRAV_noisydata.obs (X Y Z anomalia_mGal)
             MAG_noisydata.obs  (X Y Z TMI_nT)
  2. Run inversión TerraQuantum
  3. Comparar geometria recuperada vs HK1.ts (posicion y profundidad del cuerpo)
  4. Resultado de referencia: Paper Astic 2020, Figura 8 (inversion PGI)

DEPOSITO: Kimberlita DO-27, NWT Canada
  Profundidad techo: ~300 m
  Extension: cuerpo elongado N-S, ~1 km diametro
  Cobertura: lago + till glacial (~50-100 m)
""")

print("Inspeccion completada.")
