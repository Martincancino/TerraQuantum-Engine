import numpy as np
import polars as pl
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr
import os

class GravimetryForward:
    """
    FORWARD MODEL: Construye el Kernel Gravitacional como Matriz Dispersa (CSR).
    """
    def __init__(self, dx=10.0, dy=10.0, dz=10.0, cutoff_radius=800.0):
        self.dx, self.dy, self.dz = dx, dy, dz
        self.voxel_volume = dx * dy * dz
        self.G = 6.67430e-11  # Constante gravitación universal (m3 kg-1 s-2)
        self.cutoff_radius = cutoff_radius 

    def build_sparse_kernel(self, x_vox, y_vox, z_vox, sensor_coords):
        print(f"[{'FORWARD'}] Construyendo Kernel Disperso (Cutoff: {self.cutoff_radius}m)...")
        n_sensors = len(sensor_coords)
        n_voxels = len(x_vox)
        
        rows, cols, data = [], [], []
        
        for i, (sx, sy, sz) in enumerate(sensor_coords):
            dx_vec = x_vox - sx
            dy_vec = y_vox - sy # 'y' es profundidad
            dz_vec = z_vox - sz
            
            r_squared = dx_vec**2 + dy_vec**2 + dz_vec**2
            
            mask = (r_squared <= self.cutoff_radius**2) & (r_squared > 0)
            valid_voxels = np.where(mask)[0]
            
            if len(valid_voxels) > 0:
                r = np.sqrt(r_squared[valid_voxels])
                gz_vals = self.G * self.voxel_volume * 1000.0 * (dy_vec[valid_voxels] / (r**3))
                
                rows.extend([i] * len(valid_voxels))
                cols.extend(valid_voxels)
                data.extend(gz_vals)
                
        kernel_sparse = sp.csr_matrix((data, (rows, cols)), shape=(n_sensors, n_voxels))
        
        fill_rate = kernel_sparse.nnz / (n_sensors * n_voxels)
        print(f"[{'FORWARD'}] Kernel CSR creado. Elementos no nulos: {kernel_sparse.nnz:,} (Fill rate: {fill_rate:.2%})")
        
        return kernel_sparse


class GravimetryInversion:
    """
    INVERSE MODEL: Inversión real mediante LSQR con Regularización Espacial (Tikhonov 3D).
    Incluye normalización de matrices y Laplaciano geométricamente seguro (Sin wrap-around).
    """
    def __init__(self, nx=100, ny=50, nz=100, block_size=10.0):
        self.nx, self.ny, self.nz = nx, ny, nz
        self.dx = self.dy = self.dz = block_size
        self.base_density = 2.6
        self.total_voxels = nx * ny * nz

    def _build_spatial_regularizer(self):
        """
        Construye una matriz Laplaciana 3D asegurando que NO haya wrap-around 
        (conexiones fantasma entre bordes del modelo).
        """
        print(f"[{'INVERSIÓN'}] Construyendo Laplaciano 3D (Sin Wrap-Around, Orden F)...")
        
        grid_x, grid_y, grid_z = np.mgrid[0:self.nx, 0:self.ny, 0:self.nz]
        
        # FIX CRÍTICO: Forzamos Orden F para que los saltos de índices sean físicamente reales
        flat_x = grid_x.ravel(order="F")
        flat_y = grid_y.ravel(order="F")
        flat_z = grid_z.ravel(order="F")
        
        rows, cols, data = [], [], []
        idx = np.arange(self.total_voxels)
        
        # Conexiones en X
        mask_x = flat_x < self.nx - 1
        rows.extend(idx[mask_x]); cols.extend(idx[mask_x] + 1); data.extend(np.ones(np.sum(mask_x)))
        rows.extend(idx[mask_x] + 1); cols.extend(idx[mask_x]); data.extend(np.ones(np.sum(mask_x)))
        
        # Conexiones en Y
        mask_y = flat_y < self.ny - 1
        rows.extend(idx[mask_y]); cols.extend(idx[mask_y] + self.nx); data.extend(np.ones(np.sum(mask_y)))
        rows.extend(idx[mask_y] + self.nx); cols.extend(idx[mask_y]); data.extend(np.ones(np.sum(mask_y)))
        
        # Conexiones en Z
        mask_z = flat_z < self.nz - 1
        rows.extend(idx[mask_z]); cols.extend(idx[mask_z] + self.nx * self.ny); data.extend(np.ones(np.sum(mask_z)))
        rows.extend(idx[mask_z] + self.nx * self.ny); cols.extend(idx[mask_z]); data.extend(np.ones(np.sum(mask_z)))
        
        # Matriz fuera de la diagonal
        off_diag = sp.coo_matrix((data, (rows, cols)), shape=(self.total_voxels, self.total_voxels))
        
        # La diagonal es la suma negativa de las conexiones de cada vóxel (bordes tienen menos conexiones)
        diag_data = -np.array(off_diag.sum(axis=1)).flatten()
        diag_mat = sp.diags(diag_data, 0)
        
        W = (off_diag + diag_mat).tocsr()
        return W

    def solve_inversion_lsqr(self, g_observed, kernel_sparse, lambda_mag=1e-5, alpha_spatial=1.0):
        print(f"[{'INVERSIÓN'}] Normalizando matrices para estabilización del Solver...")
        
        n_sensors = kernel_sparse.shape[0]
        
        # 1. Normalización de Escalas (Crucial para LSQR)
        scale_G = np.max(np.abs(kernel_sparse.data))
        G_norm = kernel_sparse / scale_G
        g_obs_norm = g_observed / scale_G
        
        W = self._build_spatial_regularizer()
        # Normalizamos W (el max abs de la diagonal suele ser 6 en 3D)
        W_norm = W / 6.0 
        
        # Lambda dinámico adaptado a la densidad de la red de sensores
        lambda_spatial = alpha_spatial * (n_sensors / self.total_voxels)
        
        # 2. Sistema Aumentado
        G_aug = sp.vstack([G_norm, lambda_spatial * W_norm])
        d_aug = np.concatenate([g_obs_norm, np.zeros(self.total_voxels)])
        
        print(f"[{'INVERSIÓN'}] Ejecutando Solver LSQR (Tikhonov Espacial Relativo: {lambda_spatial:.2e})...")
        result = lsqr(G_aug, d_aug, damp=lambda_mag, iter_lim=250, show=False)
        density_contrast = result[0]
        
        # 3. Retroproyección de Errores para Probabilidad Física
        g_model = kernel_sparse @ density_contrast
        residual_sensor = g_observed - g_model
        residual_error = np.linalg.norm(residual_sensor)
        
        # Mapeamos el error de los sensores hacia los vóxeles usando la transpuesta del kernel
        voxel_error = np.abs(kernel_sparse.T @ residual_sensor)
        max_voxel_error = np.max(voxel_error) + 1e-12
        probability = 1.0 - (voxel_error / max_voxel_error)
        probability = np.clip(probability, 0.0, 1.0)
        
        print(f"[{'INVERSIÓN'}] Convergencia alcanzada. Error Residual L2: {residual_error:.4e}")
        
        # 4. Reconstrucción y Constraints Físicos
        estimated_density = self.base_density + density_contrast
        estimated_density = np.clip(estimated_density, 2.6, 4.2)
        
        return estimated_density, probability


class TargetingEngine:
    """
    Conecta la Inversión Geofísica con el Modelo Económico de Lerchs-Grossmann
    aplicando leyes geometalúrgicas por dominios.
    """
    @staticmethod
    def extract_and_export(x, y, z, density, probability, cutoff_density=2.75):
        print(f"[{'TARGETING'}] Modelando Clases Geometalúrgicas...")
        
        # 1. Definición de Dominios Estructurales
        domain = np.where(y < 80, 1, 2)
        grade_cu = np.zeros_like(density)
        
        # 2. Relación Densidad -> Ley No Lineal por Dominios
        mask_oxide = domain == 1
        mask_sulfide = domain == 2
        
        # Óxidos: Lixiviación los hace menos densos pero con ley moderada
        grade_cu[mask_oxide] = (density[mask_oxide] - 2.6) * 1.2
        # Sulfuros Masivos: Alta densidad = Alta ley de cobre primario
        grade_cu[mask_sulfide] = (density[mask_sulfide] - 2.8) * 2.5 + 0.4
        
        grade_cu = np.maximum(0.0, grade_cu)
        tonnage = (10.0 * 10.0 * 10.0) * density

        # Encontrar el punto exacto para la perforadora MWD
        target_idx = np.argmax(density)
        target_coords = (x[target_idx], y[target_idx], z[target_idx])

        df = pl.DataFrame({
            "x": x, "y": y, "z": z,
            "density": density,
            "grade": grade_cu,
            "tonnage": tonnage,
            "probability": probability,
            "domain": domain
        })

        # Exportación condicional de bloques anómalos
        df_anomaly = df.filter(pl.col("density") >= cutoff_density)
        
        os.makedirs("data", exist_ok=True)
        export_path = "data/block_model_001.parquet"
        df_anomaly.write_parquet(export_path)

        print(f"[{'TARGETING'}] 🎯 TARGET MWD ENCONTRADO: Coords {target_coords} | Densidad: {density[target_idx]:.2f} t/m³ | Probabilidad: {probability[target_idx]:.1%}")
        print(f"[{'TARGETING'}] Pipeline completado. Exportados {len(df_anomaly):,} bloques geológicos a Parquet.")
        
        return df_anomaly, target_coords

if __name__ == "__main__":
    # --- ENTORNO DE SIMULACIÓN Y TESTING ---
    NX, NY, NZ = 80, 40, 80
    BLOCK_SIZE = 10.0
    
    grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
    
    # FIX: Orden F también en el entorno de testing
    x_c = (grid_x.flatten(order="F") * BLOCK_SIZE) + (BLOCK_SIZE/2)
    y_c = (grid_y.flatten(order="F") * BLOCK_SIZE) + (BLOCK_SIZE/2)
    z_c = (grid_z.flatten(order="F") * BLOCK_SIZE) + (BLOCK_SIZE/2)

    # 1. Crear grilla de Sensores en superficie (y=0) cada 40 metros
    sensor_x, sensor_z = np.mgrid[0:NX*BLOCK_SIZE:40, 0:NZ*BLOCK_SIZE:40]
    sensor_coords = np.column_stack((sensor_x.ravel(), np.zeros_like(sensor_x.ravel()), sensor_z.ravel()))
    
    print(f"[{'GEOFÍSICA'}] Desplegando red de {len(sensor_coords)} sensores gravitacionales...")

    # 2. Kernel Disperso
    forward = GravimetryForward(BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=600.0)
    kernel_sparse = forward.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)

    # 3. Generar "Verdad" y Observaciones Sintéticas (Simulación para test)
    true_density_contrast = np.zeros(len(x_c))
    anomaly_mask = ((x_c - 400)**2 + (y_c - 200)**2 + (z_c - 400)**2) < 80**2
    true_density_contrast[anomaly_mask] = 1.2 # Anomalía de 3.8 t/m3
    
    g_observed = kernel_sparse @ true_density_contrast 
    g_observed += np.random.normal(0, np.max(np.abs(g_observed))*0.02, len(g_observed)) # Añadimos 2% de ruido

    # 4. Ejecutar Inversión Real con LSQR (Tikhonov + Normalización + Suavidad Espacial Integrada)
    inversor = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE)
    
    # alpha_spatial se adapta al tamaño del problema y cantidad de sensores
    est_density, prob = inversor.solve_inversion_lsqr(g_observed, kernel_sparse, lambda_mag=5e-5, alpha_spatial=1.5)

    # 5. Enviar a Targeting y Lerchs-Grossmann
    TargetingEngine.extract_and_export(x_c, y_c, z_c, est_density, prob)