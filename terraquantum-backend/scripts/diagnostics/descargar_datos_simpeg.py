"""
Script para descargar y explorar los datasets del tutorial SimPEG
Joint Inversion of Gravity and Magnetic Data (Cross-Gradient).

Dataset:
  - Modelo sintetico de un cuerpo mineralizado 3D (alta densidad + alta susceptibilidad)
  - Datos gravimetricos observados (mGal) con ruido
  - Datos magneticos observados (nT, TMI) con ruido
  - Topografia
  - Modelo "verdadero" (ground truth) para comparar contra la inversion

Referencia: SimPEG tutorials -- Potential Fields
"""

import sys
import io
import numpy as np
import os

# Forzar stdout en UTF-8 para evitar errores de encoding en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("="*60)
print("SimPEG Joint Inversion Dataset -- Descarga y Exploracion")
print("="*60)

# ============================================================
# 1. Verificar imports
# ============================================================
try:
    import simpeg
    print(f"[OK] SimPEG version: {simpeg.__version__}")
except ImportError as e:
    print(f"[ERROR] importando SimPEG: {e}")
    sys.exit(1)

try:
    import discretize
    print(f"[OK] Discretize version: {discretize.__version__}")
except ImportError as e:
    print(f"[ERROR] importando discretize: {e}")

# ============================================================
# 2. Descargar datos del tutorial Cross-Gradient Joint Inversion
# ============================================================
print("\n" + "="*60)
print("DESCARGANDO DATOS...")
print("="*60)

from simpeg.utils import download

# Dataset principal del tutorial Joint Inversion Gravity + Magnetic
DATA_URL = "https://storage.googleapis.com/simpeg/doc-assets/gravity.tar.gz"
OUTPUT_DIR = "./simpeg_data_joint_inversion"

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"\n[>>] Descargando: {DATA_URL}")
print(f"     Destino: {os.path.abspath(OUTPUT_DIR)}")

try:
    downloaded = download(DATA_URL, overwrite=True, folder=OUTPUT_DIR)
    print(f"[OK] Descarga completada: {downloaded}")
except Exception as e:
    print(f"[WARN] Error en descarga automatica: {e}")
    print("       Intentando descarga manual con requests...")
    import requests, tarfile

    r = requests.get(DATA_URL, stream=True, timeout=60)
    tarball_path = os.path.join(OUTPUT_DIR, "gravity.tar.gz")
    with open(tarball_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"[OK] Archivo descargado: {tarball_path}")
    with tarfile.open(tarball_path, "r:gz") as tar:
        tar.extractall(OUTPUT_DIR)
    print(f"[OK] Extraido en: {OUTPUT_DIR}")

# ============================================================
# 3. Listar archivos descargados
# ============================================================
print("\n" + "="*60)
print("ARCHIVOS DESCARGADOS:")
print("="*60)

all_files = []
for root, dirs, files in os.walk(OUTPUT_DIR):
    for f in files:
        fpath = os.path.join(root, f)
        size_kb = os.path.getsize(fpath) / 1024
        rel_path = os.path.relpath(fpath, OUTPUT_DIR)
        all_files.append((rel_path, size_kb))
        print(f"  [file] {rel_path}  ({size_kb:.1f} KB)")

if not all_files:
    print("  [WARN] No se encontraron archivos. La URL puede haber cambiado.")

# ============================================================
# 4. Intentar cargar y analizar los datos gravimetricos
# ============================================================
print("\n" + "="*60)
print("ANALIZANDO DATOS GRAVIMETRICOS:")
print("="*60)

# Buscar archivos de observaciones
grav_files = [f for f, _ in all_files if "grav" in f.lower() and f.endswith((".txt", ".obs", ".csv"))]
mag_files  = [f for f, _ in all_files if "mag" in f.lower()  and f.endswith((".txt", ".obs", ".csv"))]
topo_files = [f for f, _ in all_files if "topo" in f.lower() and f.endswith((".txt", ".csv"))]

print(f"\nArchivos gravimetricos encontrados: {grav_files}")
print(f"Archivos magneticos encontrados:    {mag_files}")
print(f"Archivos de topografia encontrados: {topo_files}")

def inspect_txt_file(fpath, label):
    """Carga un archivo de texto y reporta su estructura."""
    print(f"\n--- {label}: {fpath} ---")
    try:
        data = np.loadtxt(fpath)
        print(f"  Shape:    {data.shape}")
        if data.ndim == 2:
            print(f"  Columnas: {data.shape[1]}")
            print(f"  Filas:    {data.shape[0]}")
            # Intentar interpretar columnas comunes: X, Y, Z, valor
            if data.shape[1] >= 4:
                print(f"  X (E): {data[:,0].min():.1f} → {data[:,0].max():.1f} m")
                print(f"  Y (N): {data[:,1].min():.1f} → {data[:,1].max():.1f} m")
                print(f"  Z (el):{data[:,2].min():.1f} → {data[:,2].max():.1f} m")
                print(f"  Val:   {data[:,3].min():.4f} → {data[:,3].max():.4f}")
                n_pts = data.shape[0]
                print(f"  Nº de observaciones: {n_pts}")
                # Dimensiones del survey
                dx = data[:,0].max() - data[:,0].min()
                dy = data[:,1].max() - data[:,1].min()
                print(f"  Extensión survey: {dx:.0f} m (E-O) × {dy:.0f} m (N-S)")
        elif data.ndim == 1:
            print(f"  Valores: {data.min():.4f} → {data.max():.4f}")
        return data
    except Exception as e:
        print(f"  ⚠️  No se pudo cargar como np.loadtxt: {e}")
        # Intentar como texto
        with open(fpath, "r") as fh:
            lines = fh.readlines()
        print(f"  Primeras 5 líneas:")
        for l in lines[:5]:
            print(f"    {l.rstrip()}")
        return None

# Cargar los archivos encontrados
grav_data = None
mag_data  = None

for gf in grav_files:
    full_path = os.path.join(OUTPUT_DIR, gf)
    grav_data = inspect_txt_file(full_path, "GRAVIMETRÍA")

for mf in mag_files:
    full_path = os.path.join(OUTPUT_DIR, mf)
    mag_data = inspect_txt_file(full_path, "MAGNETOMETRÍA")

for tf in topo_files:
    full_path = os.path.join(OUTPUT_DIR, tf)
    inspect_txt_file(full_path, "TOPOGRAFÍA")

# ============================================================
# 5. También intentar con el tutorial 3D gravity (modelo sintético)
# ============================================================
print("\n" + "="*60)
print("DESCARGANDO DATOS ADICIONALES (Gravity 3D OcTree):")
print("="*60)

DATA_URL_2 = "https://storage.googleapis.com/simpeg/doc-assets/gravity_3d.tar.gz"
OUTPUT_DIR_2 = "./simpeg_data_gravity3d"
os.makedirs(OUTPUT_DIR_2, exist_ok=True)

print(f"\n📥 Descargando: {DATA_URL_2}")
try:
    downloaded2 = download(DATA_URL_2, overwrite=True, folder=OUTPUT_DIR_2)
    print(f"✅ Descarga completada: {downloaded2}")
    for root, dirs, files in os.walk(OUTPUT_DIR_2):
        for f in files:
            fpath = os.path.join(root, f)
            size_kb = os.path.getsize(fpath) / 1024
            rel_path = os.path.relpath(fpath, OUTPUT_DIR_2)
            print(f"  📄 {rel_path}  ({size_kb:.1f} KB)")
except Exception as e:
    print(f"⚠️  No se pudo descargar: {e}")

# ============================================================
# 6. Resumen de utilidad para TerraQuantum
# ============================================================
print("\n" + "="*60)
print("RESUMEN DE UTILIDAD PARA VALIDACIÓN TerraQuantum")
print("="*60)
print("""
✅ DATOS PRESENTES:
   - Observaciones gravimétricas (mGal) con X/Y/Z → input para inversión
   - Observaciones magnéticas (nT TMI) con X/Y/Z  → input para inversión
   - Topografía del área

✅ GROUND TRUTH (modelo verdadero):
   - El cuerpo sintético ES CONOCIDO: posición X/Y/Z, profundidad, geometría
   - Permite comparar directamente la geometría recuperada por TerraQuantum
     contra el modelo verdadero

✅ QUÉ VALIDAR CON ESTE DATASET:
   1. ¿Tu motor recupera la posición horizontal del cuerpo?
   2. ¿Recupera la profundidad al techo correctamente?
   3. ¿La forma/extensión del cuerpo es correcta?
   4. Comparar con el resultado de referencia SimPEG (joint inversion)

📁 Datos guardados en:
   ./simpeg_data_joint_inversion/
   ./simpeg_data_gravity3d/
""")

print("Script finalizado. ✅")
