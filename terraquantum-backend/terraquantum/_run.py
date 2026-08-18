"""FASE 11 — La corrida vista desde un script.

`Run` es un ASA sobre `(project_id, run_id)`, no una copia del modelo. Todo lo
que devuelve lo lee del backend en el momento, porque el modelo 3D es un DATO
EVALUADO: el invariante que la Fase 1 puso en el store del frontend
(`modelRunKey`) vale igual aquí — un informe de una corrida jamás debe poder
mezclarse con el modelo de otra.

Lo que un script hace con esto, en orden de frecuencia real:
    r.wait()                  esperar (si se encoló)
    r.verdict                 el veredicto reconciliado (worst-of, B3)
    r.best_target             dónde perforar, con su procedencia
    r.depth_resolution        qué NO resuelve el dato (null-space, B2)
    r.save_bundle("out.zip")  el entregable
"""
from __future__ import annotations

import pathlib
import time
from typing import Any, Dict, List, Optional

from ._session import Session
from .errors import InversionFailed, RunTimeout, TerraquantumError

#: Estados terminales que publica el backend (F3: SIEMPRE se escribe uno).
ESTADOS_TERMINALES = ("done", "error", "cancelled", "interrumpida")
#: De los terminales, el único que significa que hay un modelo.
ESTADO_OK = "done"


class Run:
    """Una corrida de inversión: su estado, su informe y sus entregables."""

    def __init__(
        self,
        session: Session,
        project_id: str,
        run_id: str,
        *,
        route: Optional[str] = None,
        status: Optional[str] = None,
        warnings: Optional[List[str]] = None,
        budget: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
        inversion_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.run_id = run_id
        self.route = route
        self.status = status
        self.warnings: List[str] = list(warnings or [])
        self.budget: Dict[str, Any] = dict(budget or {})
        self.plan: Dict[str, Any] = dict(plan or {})
        #: Resultado que devolvió el camino síncrono, si se usó (sin vóxeles).
        self.inversion_result: Dict[str, Any] = dict(inversion_result or {})
        self._report_cache: Optional[Dict[str, Any]] = None

    # ── Estado ────────────────────────────────────────────────────────────────

    def status_now(self) -> Dict[str, Any]:
        """`GET /geophysics-status`: etapa, progreso y mensaje REALES."""
        datos = self.session.get(f"/geophysics-status/{self.project_id}/{self.run_id}")
        estado = datos.get("status")
        if estado:
            self.status = str(estado)
        return datos

    @property
    def done(self) -> bool:
        return self.status == ESTADO_OK

    def wait(self, *, timeout_s: float = 3600.0, poll_s: float = 2.0,
             on_progress: Optional[Any] = None) -> "Run":
        """Espera hasta un estado terminal.

        Sube `InversionFailed` si termina en error/cancelled/interrumpida, y
        `RunTimeout` si se agota el plazo — sin cancelar la corrida, que sigue
        viva (un plazo del cliente no es una decisión de abortar).

        `on_progress(dict)` se llama en cada sondeo con el estado crudo: es el
        gancho para una barra de progreso en un cuaderno.
        """
        if self.status in ESTADOS_TERMINALES and self.status != ESTADO_OK:
            raise InversionFailed(
                f"La corrida ya había terminado en estado {self.status!r}.",
                run_status={"status": self.status},
            )
        limite = time.monotonic() + timeout_s
        ultimo: Dict[str, Any] = {}
        while True:
            ultimo = self.status_now()
            if callable(on_progress):
                on_progress(ultimo)
            estado = str(ultimo.get("status") or "")
            if estado in ESTADOS_TERMINALES:
                break
            if time.monotonic() >= limite:
                raise RunTimeout(
                    f"La corrida {self.project_id}/{self.run_id} no terminó en "
                    f"{timeout_s:.0f} s (etapa: {ultimo.get('stage')!r}, "
                    f"progreso: {ultimo.get('progress')!r}). Sigue en marcha.",
                    run_status=ultimo,
                )
            time.sleep(poll_s)

        if estado != ESTADO_OK:
            detalles = ultimo.get("error_details") or {}
            raise InversionFailed(
                str(ultimo.get("message") or f"La corrida terminó en {estado!r}."),
                run_status=ultimo,
                code=(detalles.get("code") or detalles.get("error") or None),
            )
        self._report_cache = None
        return self

    def cancel(self) -> Dict[str, Any]:
        """Cancela de verdad (bandera cooperativa + terminate del worker)."""
        return self.session.post(f"/geophysics-cancel/{self.project_id}/{self.run_id}")

    # ── Informe ───────────────────────────────────────────────────────────────

    @property
    def report(self) -> Dict[str, Any]:
        """El informe completo de la corrida, leído del backend.

        Se prefiere `GET /project-run-detail` (que lee el `report.json`
        persistido) antes que el eco del camino síncrono: es la MISMA fuente que
        alimenta los widgets de la interfaz, así que un script y la pantalla no
        pueden contar cosas distintas.
        """
        if self._report_cache is not None:
            return self._report_cache
        informe: Dict[str, Any] = {}
        try:
            detalle = self.session.get(
                "/project-run-detail",
                params={"project_id": self.project_id, "run_id": self.run_id},
            )
            if isinstance(detalle, dict) and isinstance(detalle.get("report"), dict):
                informe = detalle["report"]
        except TerraquantumError:
            informe = {}
        if not informe:
            eco = self.inversion_result.get("report")
            informe = eco if isinstance(eco, dict) else {}
        self._report_cache = informe
        return informe

    @property
    def verdict(self) -> Optional[Dict[str, Any]]:
        """`overall_verdict`: UN veredicto, el del eslabón más débil (B3).

        `None` si la corrida no lo publica; no se fabrica un nivel «por defecto»,
        que es exactamente el pecado que B3 vino a cerrar.
        """
        valor = self.report.get("overall_verdict")
        return valor if isinstance(valor, dict) else None

    @property
    def best_target(self) -> Optional[Dict[str, Any]]:
        """El blanco recomendado, con su procedencia y sus degradaciones (B1)."""
        valor = self.report.get("best_target") or self.inversion_result.get("best_target")
        return valor if isinstance(valor, dict) else None

    @property
    def depth_resolution(self) -> Optional[Dict[str, Any]]:
        """Qué resuelve y qué NO resuelve el dato en profundidad (B2).

        `deep_mass_fraction` es la cola de null-space MEDIDA. Un script que
        tome decisiones con `best_target` sin mirar esto está usando la mitad
        del informe.
        """
        valor = self.report.get("depthResolution")
        return valor if isinstance(valor, dict) else None

    @property
    def fit(self) -> Dict[str, Any]:
        """Diagnósticos de ajuste, tal como los publica ESTA física.

        ⚠️ MEDIDO: **gravimetría y magnetometría publican informes distintos**,
        no dos versiones del mismo. La gravimetría trae `fitDiagnostics` en la
        raíz (con `chi_squared_final`); la magnetometría no lo trae en absoluto
        y pone lo suyo en `report["solver"]` (con `chi2_final` y
        `misfit_percent`). Aquí se devuelve el bloque que exista, SIN renombrar
        sus claves: unificarlas sería fabricar un contrato que el backend no
        tiene. Para leer el número sin saber de qué física vienes, usa
        `Run.chi2` / `Run.misfit_pct`.
        """
        for fuente in (self.report, self.inversion_result):
            for clave in ("fitDiagnostics", "fit_diagnostics"):
                if isinstance(fuente.get(clave), dict) and fuente[clave]:
                    return fuente[clave]
        solver = self.report.get("solver")
        return solver if isinstance(solver, dict) else {}

    @property
    def chi2(self) -> Optional[float]:
        """χ² final, venga de donde venga (`chi_squared_final` o `chi2_final`).

        No es un cálculo: es leer dos sitios conocidos. `None` si la corrida no
        lo publica — que también es una respuesta.
        """
        return self._primer_numero(
            (self.fit, ("chi_squared_final", "chi2_final", "chi_squared")),
            (self.report, ("chi2_final",)),
        )

    @property
    def misfit_pct(self) -> Optional[float]:
        """Error de ajuste en %, en cualquiera de sus tres nombres publicados."""
        return self._primer_numero(
            (self.fit, ("misfit_percent", "misfit_pct", "misfit_error_percent")),
            (self.inversion_result, ("misfit_error_percent", "misfit_pct")),
            (self.report, ("misfit_error_percent", "misfit_pct")),
        )

    @staticmethod
    def _primer_numero(*fuentes: Any) -> Optional[float]:
        for origen, claves in fuentes:
            if not isinstance(origen, dict):
                continue
            for clave in claves:
                valor = origen.get(clave)
                if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                    return float(valor)
        return None

    def misfit(self) -> Dict[str, Any]:
        """Observado vs calculado por estación (`GET /geophysics-misfit`)."""
        return self.session.get(f"/geophysics-misfit/{self.project_id}/{self.run_id}")

    def convergence(self) -> Dict[str, Any]:
        """Traza de la selección de λ (`GET /v2/geophysics-convergence`).

        Ojo con `available: false`: significa que esta corrida no barrió λ, no
        que convergiera mal.
        """
        return self.session.get(
            f"/v2/geophysics-convergence/{self.project_id}/{self.run_id}"
        )

    # ── Modelo 3D ─────────────────────────────────────────────────────────────

    def block_model(self, *, limit: int = 200_000, mode: str = "exploration",
                    **extra: Any) -> Dict[str, Any]:
        """El modelo de bloques por el mismo endpoint que consume el visor."""
        params: Dict[str, Any] = {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "limit": limit,
            "mode": mode,
        }
        params.update(extra)
        return self.session.get("/block-model", params=params)

    def block_model_frame(self) -> Any:
        """El parquet persistido, como DataFrame de pandas.

        Es la FUENTE de verdad del modelo (lo que valida la tormenta F8), no una
        vista recortada: `/block-model` aplica límites y modo de presentación.
        Sólo funciona con una sesión en proceso o en la misma máquina, porque
        lee un archivo local — y lo dice en voz alta si no lo encuentra.
        """
        import pandas as pd

        from services.block_model_store import get_run_dir

        directorio = get_run_dir(self.project_id, self.run_id)
        parquets = sorted(pathlib.Path(directorio).glob("block_model*.parquet"))
        if not parquets:
            raise TerraquantumError(
                f"No hay parquet del modelo en {directorio}.",
                code="BLOCK_MODEL_NOT_PERSISTED",
                suggested_action=(
                    "Comprueba que la corrida terminó en 'done'. Con una sesión "
                    "remota el archivo vive en la otra máquina: usa block_model()."
                ),
            )
        return pd.read_parquet(parquets[0])

    def isosurface(self, *, field: str = "density", **extra: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "project_id": self.project_id, "run_id": self.run_id, "field": field,
        }
        params.update(extra)
        return self.session.get("/v2/isosurface", params=params)

    def section(self, *, axis: str, position: float, field: str = "density",
                **extra: Any) -> Dict[str, Any]:
        """Cara del corte en el plano `axis=position` (`GET /v2/section`).

        `axis` ∈ {x, y, z} y `position` van en **coordenadas visuales del
        visor**, no en las del CSV: es el mismo raster que pinta la interfaz. Los
        dos son obligatorios en el endpoint, así que lo son aquí — un default
        inventado (¿el centro? ¿la primera capa?) sería una decisión de
        visualización tomada en la capa equivocada.
        """
        base: Dict[str, Any] = {
            "project_id": self.project_id, "run_id": self.run_id,
            "axis": axis, "position": position, "field": field,
        }
        base.update(extra)
        return self.session.get("/v2/section", params=base)

    def profile(self, *, x0_m: float, z0_m: float, x1_m: float, z1_m: float,
                halfwidth_m: float = 50.0, include_observations: bool = True) -> Dict[str, Any]:
        """Perfil A-A' del modelo con obs/calc de las estaciones del corredor.

        (`GET /v2/block-model-profile` — una de las rutas que la Fase 9 dejó sin
        consumidor y declaró «superficie natural del scripting». Aquí lo es.)
        """
        return self.session.get(
            "/v2/block-model-profile",
            params={
                "project_id": self.project_id, "run_id": self.run_id,
                "x0_m": x0_m, "z0_m": z0_m, "x1_m": x1_m, "z1_m": z1_m,
                "halfwidth_m": halfwidth_m,
                "include_observations": include_observations,
            },
        )

    # ── Entregables ───────────────────────────────────────────────────────────

    def save_bundle(self, path: "str | pathlib.Path") -> pathlib.Path:
        """ZIP industrial de la corrida (`GET /export/bundle`)."""
        return self._descargar(
            f"/export/bundle/{self.project_id}/{self.run_id}", path,
            f"{self.project_id}_{self.run_id}_bundle.zip",
        )

    def save_block_model_csv(self, path: "str | pathlib.Path") -> pathlib.Path:
        """Block model en CSV estándar minero (`GET /export/block-model-csv`)."""
        return self._descargar(
            f"/export/block-model-csv/{self.project_id}/{self.run_id}", path,
            f"{self.project_id}_{self.run_id}_block_model.csv",
        )

    def save_report(self, path: "str | pathlib.Path") -> pathlib.Path:
        """Informe imprimible (`GET /export-report`)."""
        return self._descargar(
            "/export-report", path, f"{self.project_id}_{self.run_id}_reporte.html",
            params={"project_id": self.project_id, "run_id": self.run_id},
        )

    def _descargar(self, ruta: str, destino: "str | pathlib.Path", nombre: str,
                   params: Optional[Dict[str, Any]] = None) -> pathlib.Path:
        contenido = self.session.get(ruta, params=params, expect_json=False)
        salida = pathlib.Path(destino)
        if salida.is_dir() or str(destino).endswith(("/", "\\")):
            salida = pathlib.Path(destino) / nombre
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_bytes(contenido if isinstance(contenido, bytes) else bytes(contenido))
        return salida

    def __repr__(self) -> str:  # pragma: no cover - presentación
        nivel = (self.verdict or {}).get("level") if self.status == ESTADO_OK else None
        extra = f", verdict={nivel}" if nivel else ""
        return (
            f"Run({self.project_id}/{self.run_id}, status={self.status!r}, "
            f"route={self.route!r}{extra})"
        )
