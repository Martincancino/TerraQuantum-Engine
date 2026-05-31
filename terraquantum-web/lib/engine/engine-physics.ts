// DEMO ONLY — Modelo sintético procedural. No representa inversión geofísica real.
// No importar en flujos de inversión. Solo para demos sin backend activo.
import { VoxelData } from '../terraQuantumGeology';

export function buildPhysicsModel(
    physics: { machineId: string, depthM: number, angleDeg: number, gravMg: number },
    heatScore: number
) {
    const voxels: VoxelData[] = [];
    const resolution = 4; // 🔥 ALTA RESOLUCIÓN RECUPERADA
    const sizeX = 200; const sizeY = 200; const sizeZ = 200;
    
    const centerX = sizeX / 2; const centerY = sizeY / 2; const centerZ = sizeZ / 2;
    
    // Forma orgánica y profunda (Veta magmática real)
    const radiusA = 40 + (physics.gravMg * 20); 
    const radiusB = 80 + (physics.gravMg * 40); 
    const radiusC = 30 + (physics.gravMg * 15); 
    
    const maxGrade = 2.5 + (heatScore * 2.5); 

    for (let x = 0; x < sizeX; x += resolution) {
        for (let y = 0; y < sizeY; y += resolution) {
            if (y > physics.depthM) continue;

            for (let z = 0; z < sizeZ; z += resolution) {
                const dx = x - centerX; 
                const dy = y - centerY; 
                const dz = z - centerZ;

                // Combinación de elipsoides para romper la esfera perfecta
                const dist1 = Math.sqrt(Math.pow(dx/radiusA, 2) + Math.pow(dy/radiusB, 2) + Math.pow(dz/radiusC, 2));
                const dist2 = Math.sqrt(Math.pow((dx-15)/(radiusA*0.7), 2) + Math.pow((dy+30)/(radiusB*0.9), 2) + Math.pow(dz/(radiusC*1.2), 2));

                const distance = Math.min(dist1, dist2);

                if (distance <= 1.0) {
                    let currentGrade = maxGrade * (1.0 - distance);
                    // Ruido caótico en los bordes
                    const noise = (Math.sin(x*0.1) * Math.cos(y*0.1) * Math.sin(z*0.1)) * 0.4 * currentGrade;
                    currentGrade = Math.max(0.01, currentGrade + noise);
                    
                    voxels.push({
                        x: x - (sizeX/2), 
                        y: -y,            
                        z: z - (sizeZ/2),
                        grade: parseFloat(currentGrade.toFixed(3)),
                        alteration: 0
                    });
                }
            }
        }
    }

    return {
        domainL: sizeX, domainH: sizeY, domainW: sizeZ,
        cellSize: resolution, cells: voxels, volumeM3: voxels.length * Math.pow(resolution, 3)
    };
}