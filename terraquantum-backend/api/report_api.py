from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from reporting.report_generator import generate_technical_report_html


router = APIRouter()


@router.get("/export-report")
async def export_report(
    project_id: str = Query(...),
    run_id: str = Query(...),
):
    try:
        html_content = generate_technical_report_html(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {exc}") from exc

    filename = (
        f"terraquantum_report_{_safe_filename_part(project_id)}_"
        f"{_safe_filename_part(run_id)}.html"
    )

    return HTMLResponse(
        content=html_content,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _safe_filename_part(value: str) -> str:
    clean = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(value)
    ).strip("._")
    return clean or "unknown"
