import numpy as np
import maxflow
import scipy.sparse as sp

class LerchsGrossmannEngine:
    def __init__(self, block_data, dx, dy, dz, angle_matrix):
        self.blocks = block_data
        self.nx, self.ny, self.nz = block_data.shape
        self.dx = dx
        self.dy = dy
        self.dz = dz
        
        # Geotecnia dinámica: Si pasan un solo número, lo convertimos en matriz global
        if isinstance(angle_matrix, (int, float)):
            self.angle_matrix = np.full(block_data.shape, angle_matrix, dtype=np.float32)
        else:
            self.angle_matrix = angle_matrix
            
        self.total_nodes = self.nx * self.ny * self.nz
        self.INF = 1e12

    def build_sparse_graph(self):
        """
        Construye el grafo de precedencia usando estructuras dispersas (CSR)
        para soportar millones de bloques sin agotar la RAM.
        """
        print(f"[{'LG-ENGINE'}] Construyendo grafo disperso para {self.total_nodes:,} bloques...")
        
        node_weights = self.blocks.flatten(order='F')
        angle_flat = self.angle_matrix.flatten(order='F')
        
        all_sources, all_targets = [], []
        grid_x, grid_z = np.mgrid[0:self.nx, 0:self.nz]
        flat_x, flat_z = grid_x.ravel(), grid_z.ravel()
        
        # Alcance máximo de búsqueda basado en el ángulo más tendido
        min_angle_rad = np.radians(max(15.0, np.min(self.angle_matrix)))
        max_reach_meters = self.dy / np.tan(min_angle_rad)
        reach_blocks_x = int(np.ceil(max_reach_meters / self.dx))
        reach_blocks_z = int(np.ceil(max_reach_meters / self.dz))
        
        ix_range = np.arange(-reach_blocks_x, reach_blocks_x + 1)
        iz_range = np.arange(-reach_blocks_z, reach_blocks_z + 1)
        IX, IZ = np.meshgrid(ix_range, iz_range)
        kernel_dx, kernel_dz = IX.ravel(), IZ.ravel()
        
        kernel_dist = np.sqrt((kernel_dx * self.dx)**2 + (kernel_dz * self.dz)**2)
        
        for y in range(self.ny - 1):
            y_target = y + 1 
            # order="F": idx = ix + nx*iy + nx*ny*iz
            base_node_ids = flat_x + self.nx * y + self.nx * self.ny * flat_z
            
            target_x_matrix = flat_x[:, None] + kernel_dx
            target_z_matrix = flat_z[:, None] + kernel_dz
            
            valid_mask = (target_x_matrix >= 0) & (target_x_matrix < self.nx) & \
                         (target_z_matrix >= 0) & (target_z_matrix < self.nz)
            
            base_indices, offset_indices = np.where(valid_mask)
            
            valid_target_x = target_x_matrix[base_indices, offset_indices]
            valid_target_z = target_z_matrix[base_indices, offset_indices]
            valid_base_ids = base_node_ids[base_indices]
            valid_target_ids = valid_target_x + self.nx * y_target + self.nx * self.ny * valid_target_z
            
            # Radios geotécnicos locales bloque a bloque
            local_angles_rad = np.radians(angle_flat[valid_base_ids])
            allowed_reach = self.dy / np.tan(local_angles_rad)
            
            actual_dist = kernel_dist[offset_indices]
            geotech_mask = actual_dist <= allowed_reach
            
            all_sources.append(valid_target_ids[geotech_mask])
            all_targets.append(valid_base_ids[geotech_mask])
                
        edge_sources = np.concatenate(all_sources)
        edge_targets = np.concatenate(all_targets)
        
        # CREACIÓN DE LA MATRIZ DISPERSA (CSR)
        edge_weights = np.full(len(edge_sources), self.INF, dtype=np.float64)
        
        sparse_adj_matrix = sp.coo_matrix(
            (edge_weights, (edge_sources, edge_targets)), 
            shape=(self.total_nodes, self.total_nodes)
        )
        
        sparse_adj_matrix = sparse_adj_matrix.tocsr()
        
        print(f"[{'LG-ENGINE'}] Grafo CSR construido. Conexiones (Arcos): {sparse_adj_matrix.nnz:,}")
        
        return node_weights, sparse_adj_matrix

    def optimize_with_maxflow(self):
        """
        Ejecuta el corte de grafo alimentado por la matriz dispersa CSR.
        """
        node_weights, sparse_adj_matrix = self.build_sparse_graph()
        
        print(f"[{'LG-ENGINE'}] Iniciando optimización Max-Flow/Min-Cut...")
        g = maxflow.Graph[float](self.total_nodes, sparse_adj_matrix.nnz)
        nodes = g.add_nodes(self.total_nodes)
        
        # 1. Conectar a Fuente/Sumidero
        for i, weight in enumerate(node_weights):
            if weight > 0:
                g.add_tedge(nodes[i], weight, 0)
            else:
                g.add_tedge(nodes[i], 0, -weight)
                
        # 2. Inyectar precedencia desde CSR
        sources = sparse_adj_matrix.nonzero()[0]
        targets = sparse_adj_matrix.nonzero()[1]
        
        for sup, inf in zip(sources, targets):
            g.add_edge(nodes[inf], nodes[sup], self.INF, 0)
            
        print(f"[{'LG-ENGINE'}] Resolviendo flujo máximo...")
        g.maxflow()
        
        # 3. Extraer envolvente óptima
        mined_mask_1d = np.array([g.get_segment(n) == 0 for n in nodes])
        mined_mask_3d = mined_mask_1d.reshape((self.nx, self.ny, self.nz), order='F')
        
        print(f"[{'LG-ENGINE'}] Optimización completada. Bloques a extraer: {np.sum(mined_mask_1d):,}")
        
        return mined_mask_3d, node_weights