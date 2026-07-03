"""
Script para convertir los archivos .obs (UBC-GIF) a formato .csv estandar
con encabezados, para facilitar su uso en TerraQuantum.
"""

import os
import numpy as np

BASE_DIR = r"C:\Users\marti\OneDrive\Documentos\TerraQuantum"

# Definir los archivos de entrada (.obs o .txt) y su salida (.csv)
# (Ruta entrada, Ruta salida, Encabezados)
archivos_a_convertir = [
    # 1. SimPEG Synthetic
    (
        os.path.join(BASE_DIR, "simpeg_data_joint_inversion", "gravity", "gravity_data.obs"),
        os.path.join(BASE_DIR, "simpeg_data_joint_inversion", "gravity_data.csv"),
        "X,Y,Z,Anomalia_Bouguer_mGal"
    ),
    (
        os.path.join(BASE_DIR, "simpeg_data_mag", "magnetics", "magnetics_data.obs"),
        os.path.join(BASE_DIR, "simpeg_data_mag", "magnetics_data.csv"),
        "X,Y,Z,TMI_nT"
    ),
    # 2. DO-27 Kimberlite
    (
        os.path.join(BASE_DIR, "DO-27_Kimberlite", "Forward", "GRAV_noisydata.obs"),
        os.path.join(BASE_DIR, "DO-27_Kimberlite", "DO27_Gravity_mGal.csv"),
        "X,Y,Z,Anomalia_Bouguer_mGal,Error_Est"
    ),
    (
        os.path.join(BASE_DIR, "DO-27_Kimberlite", "Forward", "MAG_noisydata.obs"),
        os.path.join(BASE_DIR, "DO-27_Kimberlite", "DO27_Magnetic_TMI_nT.csv"),
        "X,Y,Z,TMI_nT,Error_Est"
    ),
    # 3. Raglan Ni-Sulfide
    (
        os.path.join(BASE_DIR, "Raglan_Magnetic", "data", "Raglan_1997", "obs.mag"),
        os.path.join(BASE_DIR, "Raglan_Magnetic", "Raglan_Magnetic_TMI_nT.csv"),
        "X,Y,Z,TMI_nT,Std_nT"
    )
]

print("Convirtiendo archivos de datos a formato CSV...\n")

def parse_ubc_obs(filepath):
    """Parsea un archivo .obs de UBC, ignorando las lineas de cabecera."""
    data_rows = []
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!') or line.startswith('#'):
                continue
            
            parts = line.split()
            # Si solo tiene un numero, suele ser la cantidad de datos (N)
            if len(parts) == 1:
                continue
                
            try:
                # Intentar convertir a float
                row = [float(p) for p in parts]
                data_rows.append(row)
            except ValueError:
                pass # Linea de texto (header IGRF, etc)
                
    if not data_rows:
        return None
        
    # Asegurar que todas las filas tengan la misma longitud
    max_cols = max(len(row) for row in data_rows)
    # Rellenar con NaN las filas mas cortas
    padded_rows = [row + [np.nan] * (max_cols - len(row)) for row in data_rows]
    
    return np.array(padded_rows)

for ruta_in, ruta_out, header in archivos_a_convertir:
    if not os.path.exists(ruta_in):
        print(f"[!] No encontrado: {os.path.basename(ruta_in)}")
        continue
        
    try:
        # Cargar los datos saltando cabeceras raras
        datos = parse_ubc_obs(ruta_in)
        
        if datos is not None and len(datos) > 0:
            # Forzar maximo 5 columnas segun el header que pasamos
            if datos.shape[1] > 5:
                datos = datos[:, :5]
                
            # Guardar como CSV
            np.savetxt(ruta_out, datos, delimiter=',', header=header, comments='', fmt='%.5f')
            print(f"[OK] Creado: {ruta_out}")
            print(f"     -> {len(datos)} filas, {datos.shape[1]} columnas guardadas.")
        else:
            print(f"[!] No se pudieron extraer datos numéricos de {ruta_in}")
            
    except Exception as e:
        print(f"[ERROR] Procesando {ruta_in}: {e}")

print("\n¡Conversión terminada! Ya puedes usar los .csv")
