import io

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

from services.block_model_service import (
    build_block_model_response,
    build_block_model_arrow_bytes,
)

router = APIRouter()


@router.get("/block-model")
async def get_block_model(
    mode: str = "exploration",
    limit: int = 5000,
    project_id: str = None,
    run_id: str = None,
):
    print(
        f"[BLOCK-MODEL-API] GET /block-model mode={mode} limit={limit} "
        f"project_id={project_id} run_id={run_id}"
    )

    return build_block_model_response(
        mode=mode,
        limit=limit,
        project_id=project_id,
        run_id=run_id,
    )


@router.get("/block-model-arrow")
async def get_block_model_arrow(
    mode: str = "exploration",
    project_id: str = None,
    run_id: str = None,
):
    """Endpoint Arrow IPC — transporte binario, sin iter_rows ni deep_sanitize_nan.

    Content-Type: application/vnd.apache.arrow.stream
    Headers extra: X-TQ-Total-Voxels, X-TQ-Bounds-Min, X-TQ-Bounds-Max, X-TQ-Run-Id
    """
    print(
        f"[BLOCK-MODEL-ARROW] GET /block-model-arrow mode={mode} "
        f"project_id={project_id} run_id={run_id}"
    )

    try:
        ipc_bytes, tq_headers = build_block_model_arrow_bytes(
            mode=mode,
            limit=0,
            project_id=project_id,
            run_id=run_id,
        )
    except FileNotFoundError as exc:
        return Response(content=str(exc), status_code=404)
    except ValueError as exc:
        return Response(content=str(exc), status_code=400)
    except Exception as exc:
        print(f"[BLOCK-MODEL-ARROW] Error inesperado: {exc}")
        return Response(content="Error interno al construir Arrow payload.", status_code=500)

    response = StreamingResponse(
        io.BytesIO(ipc_bytes),
        media_type="application/vnd.apache.arrow.stream",
    )
    for key, val in tq_headers.items():
        response.headers[key] = val

    return response
