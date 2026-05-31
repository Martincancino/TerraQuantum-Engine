import json
import sys
import time
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8010"


def print_section(title: str):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def request_json(method: str, path: str, payload=None, timeout=120):
    url = f"{BASE_URL}{path}"

    data = None
    headers = {
        "Accept": "application/json",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url=url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = response.status

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"{method} {path} no devolvió JSON válido. Respuesta: {raw[:500]}"
                )

            if status < 200 or status >= 300:
                raise RuntimeError(
                    f"{method} {path} devolvió status {status}. Respuesta: {parsed}"
                )

            return parsed

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw

        raise RuntimeError(
            f"{method} {path} falló con HTTP {exc.code}. Respuesta: {parsed}"
        )

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo conectar con backend en {BASE_URL}. "
            f"¿Está abierto start-backend.bat? Error: {exc}"
        )


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def build_geophysics_payload():
    return {
        "depth": 80,
        "nir": 83,
        "fe": 79,
        "region": "norte_chile",
        "lat": "-22.28",
        "lon": "-68.89",
        "nx": 8,
        "ny": 8,
        "nz": 8,
        "block_size": 10,
        "cutoff_radius": 160,
        "lambda_mag": 0.00005,
        "alpha_spatial": 1.5,
        "observations": [
            {"x_m": 5, "y_m": 0, "z_m": 5, "g": 0.00000080},
            {"x_m": 15, "y_m": 0, "z_m": 5, "g": 0.00000090},
            {"x_m": 25, "y_m": 0, "z_m": 5, "g": 0.00000110},
            {"x_m": 35, "y_m": 0, "z_m": 5, "g": 0.00000150},
            {"x_m": 45, "y_m": 0, "z_m": 5, "g": 0.00000145},
            {"x_m": 55, "y_m": 0, "z_m": 5, "g": 0.00000110},
            {"x_m": 65, "y_m": 0, "z_m": 5, "g": 0.00000090},
            {"x_m": 75, "y_m": 0, "z_m": 5, "g": 0.00000080},
            {"x_m": 5, "y_m": 0, "z_m": 35, "g": 0.00000085},
            {"x_m": 15, "y_m": 0, "z_m": 35, "g": 0.00000100},
            {"x_m": 25, "y_m": 0, "z_m": 35, "g": 0.00000135},
            {"x_m": 35, "y_m": 0, "z_m": 35, "g": 0.00000220},
            {"x_m": 45, "y_m": 0, "z_m": 35, "g": 0.00000230},
            {"x_m": 55, "y_m": 0, "z_m": 35, "g": 0.00000135},
            {"x_m": 65, "y_m": 0, "z_m": 35, "g": 0.00000100},
            {"x_m": 75, "y_m": 0, "z_m": 35, "g": 0.00000085},
            {"x_m": 5, "y_m": 0, "z_m": 65, "g": 0.00000075},
            {"x_m": 15, "y_m": 0, "z_m": 65, "g": 0.00000090},
            {"x_m": 25, "y_m": 0, "z_m": 65, "g": 0.00000110},
            {"x_m": 35, "y_m": 0, "z_m": 65, "g": 0.00000145},
            {"x_m": 45, "y_m": 0, "z_m": 65, "g": 0.00000140},
            {"x_m": 55, "y_m": 0, "z_m": 65, "g": 0.00000110},
            {"x_m": 65, "y_m": 0, "z_m": 65, "g": 0.00000090},
            {"x_m": 75, "y_m": 0, "z_m": 65, "g": 0.00000075},
        ],
    }


def build_pit_payload():
    return {
        "file": "block_model_001.parquet",
        "price": 8500,
        "recovery": 0.88,
        "mining_cost": 2.2,
        "processing_cost": 14.0,
        "pit_angle": 45,
        "bench_height": 10,
        "berm_width": 8,
        "haulage_cost_per_m": 0.002,
        "ramp_gradient": 0.10,
        "block_size_x": 10,
        "block_size_y": 10,
        "block_size_z": 10,
        "exclude_inferred": False,
        "p_cap": 80000000,
        "discount_rate": 0.10,
        "fleet_size": 20,
    }


def main():
    started_at = time.time()

    try:
        print_section("1. Probando /health")
        health = request_json("GET", "/health")
        print(json.dumps(health, indent=2, ensure_ascii=False))
        assert_true(health.get("status") == "ok", "/health no respondió status ok")

        print_section("2. Probando /system-status")
        status = request_json("GET", "/system-status")
        print(json.dumps(status, indent=2, ensure_ascii=False))
        assert_true(status.get("status") == "ok", "/system-status no respondió status ok")

        print_section("3. Ejecutando /geophysics-invert")
        geo_payload = build_geophysics_payload()
        geo_result = request_json("POST", "/geophysics-invert", geo_payload, timeout=180)

        print(
            json.dumps(
                {
                    "best_target": geo_result.get("best_target"),
                    "report": geo_result.get("report"),
                    "voxels_returned": len(geo_result.get("voxels", [])),
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        assert_true("report" in geo_result, "/geophysics-invert no devolvió report")
        assert_true(
            geo_result["report"].get("total_voxels", 0) > 0,
            "/geophysics-invert devolvió total_voxels inválido",
        )

        print_section("4. Probando /block-model exploration")
        block_model = request_json("GET", "/block-model?mode=exploration&limit=1000")

        print(
            json.dumps(
                {
                    "mode": block_model.get("mode"),
                    "visualMode": block_model.get("visualMode"),
                    "totalRows": block_model.get("totalRows"),
                    "returnedCells": block_model.get("returnedCells"),
                    "densityMin": block_model.get("densityMin"),
                    "densityMax": block_model.get("densityMax"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        assert_true(
            block_model.get("returnedCells", 0) > 0,
            "/block-model no devolvió cells",
        )

        print_section("5. Ejecutando /generate")
        pit_payload = build_pit_payload()
        pit_result = request_json("POST", "/generate", pit_payload, timeout=240)

        print(
            json.dumps(
                {
                    "status": pit_result.get("status"),
                    "jobId": pit_result.get("jobId"),
                    "modelUrl": pit_result.get("modelUrl"),
                    "metrics": pit_result.get("metrics"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        assert_true(
            pit_result.get("status") == "done",
            "/generate no devolvió status done",
        )

        assert_true(
            "modelUrl" in pit_result,
            "/generate no devolvió modelUrl",
        )

        elapsed = time.time() - started_at

        print_section("SMOKE TEST COMPLETADO ✅")
        print(f"Todo correcto. Tiempo total: {elapsed:.1f} segundos.")
        print("Backend industrial operativo.")

    except Exception as exc:
        print_section("SMOKE TEST FALLÓ ❌")
        print(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()