"""
Script v2: Descomprime el tar.gz descargado y descarga datos
de los tutoriales via URLs actualizadas de SimPEG.
"""

import sys, io, os, tarfile, requests, numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("="*60)
print("SimPEG - Descompresion y descarga de datos geofisicos")
print("="*60)

# ============================================================
# PASO 1: Descomprimir gravity.tar.gz ya descargado
# ============================================================
TAR_PATH = "./simpeg_data_joint_inversion/gravity.tar.gz"
OUT_DIR  = "./simpeg_data_joint_inversion"

print(f"\n[1] Descomprimiendo: {TAR_PATH}")
if os.path.exists(TAR_PATH):
    with tarfile.open(TAR_PATH, "r:gz") as tar:
        members = tar.getnames()
        print(f"    Contenido del tar ({len(members)} archivos):")
        for m in members:
            print(f"      {m}")
        tar.extractall(OUT_DIR)
    print(f"[OK] Extraido en: {OUT_DIR}")
else:
    print("[WARN] Archivo tar no encontrado. Descargando...")
    from simpeg.utils import download
    download("https://storage.googleapis.com/simpeg/doc-assets/gravity.tar.gz",
             overwrite=True, folder=OUT_DIR)
    with tarfile.open(TAR_PATH, "r:gz") as tar:
        tar.extractall(OUT_DIR)

# ============================================================
# PASO 2: Listar todo lo que hay ahora
# ============================================================
print(f"\n[2] Archivos en {OUT_DIR}:")
all_files = []
for root, dirs, files in os.walk(OUT_DIR):
    for f in files:
        fpath = os.path.join(root, f)
        size_kb = os.path.getsize(fpath) / 1024
        rel = os.path.relpath(fpath, OUT_DIR)
        all_files.append((rel, size_kb, fpath))
        print(f"    {rel}  ({size_kb:.1f} KB)")

# ============================================================
# PASO 3: Descargar datos de tutorials SimPEG via URLs alternativas
# ============================================================
print("\n[3] Descargando datasets via URLs alternativas...")

# URLs conocidas del GCS bucket de SimPEG para tutoriales de campos potenciales
urls_to_try = [
    # Tutorial: 3D gravity inversion on tensor mesh
    ("https://storage.googleapis.com/simpeg/doc-assets/gravity.tar.gz",
     "./simpeg_data_joint_inversion", "ya descargado"),
    # Tutorial: 3D mag inversion (tensor mesh)
    ("https://storage.googleapis.com/simpeg/doc-assets/magnetics.tar.gz",
     "./simpeg_data_mag", "magneticos"),
    # Tutorial alternativo (desde el repo de ejemplos de SimPEG en GCS)
    ("https://storage.googleapis.com/simpeg/doc-assets/potential_fields.tar.gz",
     "./simpeg_data_potential", "potential fields"),
]

def try_download(url, out_dir, label):
    os.makedirs(out_dir, exist_ok=True)
    fname = url.split("/")[-1]
    fpath = os.path.join(out_dir, fname)
    if os.path.exists(fpath):
        print(f"  [{label}] Ya existe: {fpath}")
        return fpath
    print(f"  [{label}] GET {url}")
    try:
        r = requests.get(url, stream=True, timeout=30)
        if r.status_code == 200:
            with open(fpath, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            size_kb = os.path.getsize(fpath) / 1024
            print(f"  [OK] Descargado {size_kb:.1f} KB -> {fpath}")
            return fpath
        else:
            print(f"  [FAIL] HTTP {r.status_code}")
            return None
    except Exception as e:
        print(f"  [FAIL] {e}")
        return None

for url, out_dir, label in urls_to_try[1:]:  # skip el primero ya descargado
    fpath = try_download(url, out_dir, label)
    if fpath and os.path.exists(fpath):
        try:
            with tarfile.open(fpath, "r:gz") as tar:
                members = tar.getnames()
                print(f"    Contenido ({len(members)} items): {members[:5]}")
                tar.extractall(out_dir)
            print(f"    [OK] Extraido en {out_dir}")
        except Exception as e:
            print(f"    [WARN] No es tar valido: {e}")

# ============================================================
# PASO 4: Analizar TODOS los archivos de datos encontrados
# ============================================================
print("\n" + "="*60)
print("[4] ANALISIS DE ARCHIVOS DE DATOS:")
print("="*60)

search_dirs = [
    "./simpeg_data_joint_inversion",
    "./simpeg_data_mag",
    "./simpeg_data_potential",
]

DATA_EXTENSIONS = (".txt", ".obs", ".xyz", ".csv", ".loc", ".mag", ".grv")

def inspect(fpath, label=""):
    print(f"\n  --- {label or os.path.basename(fpath)} ---")
    try:
        data = np.loadtxt(fpath, comments=["#", "!", "//"], max_rows=5000)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        nrows, ncols = data.shape
        print(f"  Shape: {nrows} obs x {ncols} columnas")
        for i in range(min(ncols, 5)):
            print(f"    Col {i}: min={data[:,i].min():.4f}  max={data[:,i].max():.4f}  mean={data[:,i].mean():.4f}")
        if ncols >= 3:
            dx = data[:,0].max() - data[:,0].min()
            dy = data[:,1].max() - data[:,1].min()
            print(f"  Extension: {dx:.1f} x {dy:.1f}  (en unidades de Col0/Col1)")
        return data
    except Exception as e:
        # Mostrar primeras lineas como texto
        try:
            with open(fpath, "r", errors="replace") as fh:
                lines = fh.readlines()
            print(f"  [como texto] {len(lines)} lineas. Primeras 6:")
            for l in lines[:6]:
                print(f"    {l.rstrip()}")
        except:
            print(f"  [ERROR] No se pudo leer: {e}")
        return None

found_data = []
for sdir in search_dirs:
    if not os.path.exists(sdir):
        continue
    for root, dirs, files in os.walk(sdir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in DATA_EXTENSIONS:
                fpath = os.path.join(root, f)
                rel = os.path.relpath(fpath, sdir)
                found_data.append((fpath, f"{sdir}/{rel}"))

if found_data:
    for fpath, label in found_data:
        inspect(fpath, label)
else:
    print("\n  [INFO] No se encontraron archivos de datos con extension conocida.")
    print("  Mostrando TODOS los archivos disponibles:")
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for root, dirs, files in os.walk(sdir):
            for f in files:
                fpath = os.path.join(root, f)
                size_kb = os.path.getsize(fpath)/1024
                rel = os.path.relpath(fpath, sdir)
                print(f"    {sdir}/{rel}  ({size_kb:.1f} KB)")
                # Intentar leer los primeros bytes
                try:
                    with open(fpath, "r", errors="replace") as fh:
                        lines = fh.readlines()
                    print(f"      Primeras 4 lineas:")
                    for l in lines[:4]:
                        print(f"        {l.rstrip()}")
                    inspect(fpath, sdir+"/"+rel)
                except:
                    pass

# ============================================================
# PASO 5: Intentar descargar directamente los archivos individuales
#         del repositorio publico de SimPEG en GitHub
# ============================================================
print("\n" + "="*60)
print("[5] DESCARGA DIRECTA DESDE GITHUB (simpeg-research / ejemplos):")
print("="*60)

github_files = [
    # Datos del tutorial de inversion gravimetrica de SimPEG docs
    ("https://raw.githubusercontent.com/simpeg/simpeg/main/tutorials/03-gravity/gravity_obs.obs",
     "./simpeg_github/gravity_obs.obs"),
    ("https://raw.githubusercontent.com/simpeg/simpeg/main/tutorials/03-gravity/topo.txt",
     "./simpeg_github/topo.txt"),
    # Datos magneticos
    ("https://raw.githubusercontent.com/simpeg/simpeg/main/tutorials/04-magnetics/magnetics_obs.obs",
     "./simpeg_github/magnetics_obs.obs"),
]

os.makedirs("./simpeg_github", exist_ok=True)

for url, dest in github_files:
    print(f"\n  GET {url}")
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(dest, "wb") as f:
                f.write(r.content)
            size_kb = len(r.content)/1024
            print(f"  [OK] {size_kb:.1f} KB -> {dest}")
            inspect(dest)
        else:
            print(f"  [FAIL] HTTP {r.status_code}")
    except Exception as e:
        print(f"  [FAIL] {e}")

print("\n" + "="*60)
print("DONE")
print("="*60)
