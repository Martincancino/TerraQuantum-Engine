const FRONTEND_URL = "http://localhost:3000";
const VALIDATION_PROJECT_ID = "validation_project";
const VALIDATION_RUN_ID = "validation_run_001";

function printSection(title) {
  console.log("");
  console.log("=".repeat(70));
  console.log(title);
  console.log("=".repeat(70));
}

async function fetchJson(path, options = {}) {
  const url = `${FRONTEND_URL}${path}`;

  const timeoutMs = options.timeoutMs || 120000;
  const controller = new AbortController();

  const timeout = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      method: options.method || "GET",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    const raw = await res.text();

    let data;

    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      throw new Error(
        `${options.method || "GET"} ${path} no devolvió JSON válido. Respuesta: ${raw.slice(
          0,
          500
        )}`
      );
    }

    if (!res.ok) {
      throw new Error(
        `${options.method || "GET"} ${path} falló con status ${res.status}: ${JSON.stringify(
          data,
          null,
          2
        )}`
      );
    }

    return data;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        `${options.method || "GET"} ${path} superó timeout de ${timeoutMs / 1000}s`
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function assertTrue(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function fetchBinary(path, options = {}) {
  const url = `${FRONTEND_URL}${path}`;

  const timeoutMs = options.timeoutMs || 120000;
  const controller = new AbortController();

  const timeout = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      method: options.method || "GET",
      headers: {
        Accept: options.accept || "*/*",
      },
      signal: controller.signal,
    });

    const contentType = res.headers.get("content-type") || "";
    const buffer = await res.arrayBuffer();

    if (!res.ok) {
      const raw = new TextDecoder().decode(buffer);
      throw new Error(
        `${options.method || "GET"} ${path} falló con status ${res.status}: ${raw.slice(
          0,
          500
        )}`
      );
    }

    return {
      status: res.status,
      contentType,
      bytes: buffer.byteLength,
    };
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        `${options.method || "GET"} ${path} superó timeout de ${timeoutMs / 1000}s`
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function buildGeophysicsPayload() {
  return {
    depth: 80,
    nir: 83,
    fe: 79,
    region: "norte_chile",
    lat: "-22.28",
    lon: "-68.89",
    nx: 8,
    ny: 8,
    nz: 8,
    block_size: 10,
    cutoff_radius: 160,
    lambda_mag: 0.00005,
    alpha_spatial: 1.5,
    observations: [
      { x_m: 5, y_m: 0, z_m: 5, g: 0.0000008 },
      { x_m: 15, y_m: 0, z_m: 5, g: 0.0000009 },
      { x_m: 25, y_m: 0, z_m: 5, g: 0.0000011 },
      { x_m: 35, y_m: 0, z_m: 5, g: 0.0000015 },
      { x_m: 45, y_m: 0, z_m: 5, g: 0.00000145 },
      { x_m: 55, y_m: 0, z_m: 5, g: 0.0000011 },
      { x_m: 65, y_m: 0, z_m: 5, g: 0.0000009 },
      { x_m: 75, y_m: 0, z_m: 5, g: 0.0000008 },

      { x_m: 5, y_m: 0, z_m: 35, g: 0.00000085 },
      { x_m: 15, y_m: 0, z_m: 35, g: 0.000001 },
      { x_m: 25, y_m: 0, z_m: 35, g: 0.00000135 },
      { x_m: 35, y_m: 0, z_m: 35, g: 0.0000022 },
      { x_m: 45, y_m: 0, z_m: 35, g: 0.0000023 },
      { x_m: 55, y_m: 0, z_m: 35, g: 0.00000135 },
      { x_m: 65, y_m: 0, z_m: 35, g: 0.000001 },
      { x_m: 75, y_m: 0, z_m: 35, g: 0.00000085 },

      { x_m: 5, y_m: 0, z_m: 65, g: 0.00000075 },
      { x_m: 15, y_m: 0, z_m: 65, g: 0.0000009 },
      { x_m: 25, y_m: 0, z_m: 65, g: 0.0000011 },
      { x_m: 35, y_m: 0, z_m: 65, g: 0.00000145 },
      { x_m: 45, y_m: 0, z_m: 65, g: 0.0000014 },
      { x_m: 55, y_m: 0, z_m: 65, g: 0.0000011 },
      { x_m: 65, y_m: 0, z_m: 65, g: 0.0000009 },
      { x_m: 75, y_m: 0, z_m: 65, g: 0.00000075 },
    ],
  };
}

async function main() {
  const startedAt = Date.now();

  try {
    printSection("1. Probando /api/backend-health");
    const health = await fetchJson("/api/backend-health", {
      timeoutMs: 10000,
    });

    console.log(JSON.stringify(health, null, 2));
    assertTrue(health.online === true, "/api/backend-health no está online");

    printSection("2. Probando /api/system-check");
    const system = await fetchJson("/api/system-check", {
      timeoutMs: 15000,
    });

    console.log(
      JSON.stringify(
        {
          online: system.online,
          routesReady: system.routesReady,
          routes: system.routes,
          blockModel: system.blockModel,
          summary: system.summary,
        },
        null,
        2
      )
    );

    assertTrue(system.online === true, "/api/system-check no está online");
    assertTrue(system.routesReady === true, "Rutas críticas no están listas");

    printSection("3. Probando /api/geophysics-invert");
    const geo = await fetchJson("/api/geophysics-invert", {
      method: "POST",
      body: buildGeophysicsPayload(),
      timeoutMs: 180000,
    });

    console.log(
      JSON.stringify(
        {
          best_target: geo.best_target,
          report: geo.report,
          voxels_returned: Array.isArray(geo.voxels) ? geo.voxels.length : 0,
        },
        null,
        2
      )
    );

    assertTrue(Boolean(geo.report), "/api/geophysics-invert no devolvió report");
    assertTrue(
      geo.report.total_voxels > 0,
      "/api/geophysics-invert devolvió total_voxels inválido"
    );

    printSection("4. Probando /api/block-model");
    const block = await fetchJson("/api/block-model?mode=exploration&limit=1000", {
      timeoutMs: 45000,
    });

    console.log(
      JSON.stringify(
        {
          mode: block.mode,
          visualMode: block.visualMode,
          totalRows: block.totalRows,
          returnedCells: block.returnedCells,
          densityMin: block.densityMin,
          densityMax: block.densityMax,
        },
        null,
        2
      )
    );

    assertTrue(
      Array.isArray(block.cells) && block.cells.length > 0,
      "/api/block-model no devolvió cells"
    );

    printSection("5. Probando /api/project-runs");
    const projectRuns = await fetchJson("/api/project-runs", {
      timeoutMs: 30000,
    });

    const validationProject = Array.isArray(projectRuns.projects)
      ? projectRuns.projects.find(
          (project) => project?.projectId === VALIDATION_PROJECT_ID
        )
      : null;

    console.log(
      JSON.stringify(
        {
          totalProjects: projectRuns.totalProjects,
          totalRuns: projectRuns.totalRuns,
          validationProjectFound: Boolean(validationProject),
        },
        null,
        2
      )
    );

    assertTrue(Array.isArray(projectRuns.projects), "/api/project-runs no devolvió projects");
    assertTrue(Boolean(validationProject), "No aparece validation_project en /api/project-runs");

    printSection("7. Probando /api/project-run-detail");
    const detail = await fetchJson(
      `/api/project-run-detail?project_id=${encodeURIComponent(
        VALIDATION_PROJECT_ID
      )}&run_id=${encodeURIComponent(VALIDATION_RUN_ID)}`,
      { timeoutMs: 30000 }
    );

    console.log(
      JSON.stringify(
        {
          projectId: detail.projectId,
          runId: detail.runId,
          files: detail.files,
        },
        null,
        2
      )
    );

    assertTrue(detail.projectId === VALIDATION_PROJECT_ID, "project-run-detail projectId inválido");
    assertTrue(detail.runId === VALIDATION_RUN_ID, "project-run-detail runId inválido");
    assertTrue(detail.files?.block_model === true, "project-run-detail files.block_model no es true");
    assertTrue(detail.files?.inputs === true, "project-run-detail files.inputs no es true");
    assertTrue(detail.files?.report === true, "project-run-detail files.report no es true");
    assertTrue(detail.files?.metrics === true, "project-run-detail files.metrics no es true");
    assertTrue(detail.files?.schedule === true, "project-run-detail files.schedule no es true");

    printSection("8. Probando /api/compare-runs");
    const compare = await fetchJson(
      `/api/compare-runs?base_project_id=${encodeURIComponent(
        VALIDATION_PROJECT_ID
      )}&base_run_id=${encodeURIComponent(
        VALIDATION_RUN_ID
      )}&compare_project_id=${encodeURIComponent(
        VALIDATION_PROJECT_ID
      )}&compare_run_id=${encodeURIComponent(VALIDATION_RUN_ID)}`,
      { timeoutMs: 30000 }
    );

    console.log(
      JSON.stringify(
        {
          baseRun: compare.baseRun,
          compareRun: compare.compareRun,
          deltas: compare.deltas,
        },
        null,
        2
      )
    );

    assertTrue(Boolean(compare.baseRun), "/api/compare-runs no devolvió baseRun");
    assertTrue(Boolean(compare.compareRun), "/api/compare-runs no devolvió compareRun");
    assertTrue(Boolean(compare.deltas), "/api/compare-runs no devolvió deltas");

    printSection("9. Probando /api/export-run");
    const zip = await fetchBinary(
      `/api/export-run?project_id=${encodeURIComponent(
        VALIDATION_PROJECT_ID
      )}&run_id=${encodeURIComponent(VALIDATION_RUN_ID)}`,
      {
        accept: "application/zip",
        timeoutMs: 30000,
      }
    );

    console.log(JSON.stringify(zip, null, 2));

    assertTrue(zip.status === 200, "/api/export-run no devolvió status 200");
    assertTrue(
      zip.contentType.toLowerCase().includes("application/zip") ||
        zip.contentType.toLowerCase().includes("application/octet-stream"),
      "/api/export-run no devolvió Content-Type de ZIP"
    );
    assertTrue(zip.bytes > 0, "/api/export-run devolvió ZIP vacío");

    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);

    printSection("FRONTEND SMOKE TEST COMPLETADO ✅");
    console.log(`Todo correcto. Tiempo total: ${elapsed} segundos.`);
    console.log("Frontend conectado correctamente al backend Python.");
  } catch (error) {
    printSection("FRONTEND SMOKE TEST FALLÓ ❌");
    console.error(error?.message || error);
    process.exit(1);
  }
}

main();
