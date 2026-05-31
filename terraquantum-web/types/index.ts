// types/index.ts

export type TargetData = { id: string; probabilidad: number; profundidad: number; coordenadas: string; estado: string; };

export type AnalysisReport = { 
  profundidad: number; masaKg: number; clasificacionEstructural: string; justificacion: string; 
  contrasteDensidad: string; leyPromedio: string; indiceAnomalia: string; anomaliaPico: number; 
  zonaGeografica: string; firmaSuperficial: string; notasTerreno: string; recomendacionPerforacion: boolean; 
  rankingTargets: TargetData[]; score: number; uncertainty: number; 
};

// Tipos legacy de FMS/mina/sondaje eliminados en el rediseño geofísico (Fase A).