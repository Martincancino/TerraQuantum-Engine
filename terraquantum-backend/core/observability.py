"""
OpenTelemetry tracing setup — HITO 7 observability.

Auto-instruments all FastAPI HTTP endpoints (span per request + per route).
Optionally exports traces to an OTLP-compatible backend (Jaeger, Grafana Tempo, etc.).

Configuration via env vars:
    OTEL_ENABLED=true           Enable OTel tracing (default: false — zero overhead when off)
    OTEL_SERVICE_NAME=...       Service name in traces (default: "terraquantum-backend")
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   Export to OTLP HTTP endpoint.
                                                        Omit to use console exporter (dev).

Quick start with Jaeger:
    docker run -d --name jaeger \\
      -p 16686:16686 -p 4318:4318 \\
      jaegertracing/all-in-one:latest
    OTEL_ENABLED=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn main:app
    # Then open http://localhost:16686 to see traces.

Quick start with Grafana Tempo (docker-compose):
    OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318

Usage — manual spans in services (optional):
    from core.observability import tracer
    with tracer.start_as_current_span("run_inversion") as span:
        span.set_attribute("run_type", "gravity")
        span.set_attribute("nx", params.nx)
        result = run_geophysics_inversion(params)
"""
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from core.config import OTEL_ENABLED, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME
from core.logging import get_logger

_log = get_logger(__name__)

# Module-level tracer — always safe to call even when OTel is disabled
# (returns a no-op tracer when not initialized).
tracer: trace.Tracer = trace.get_tracer(__name__)


def init_tracing() -> None:
    """
    Initialize OpenTelemetry tracing.
    Call once at application startup (before FastAPIInstrumentor().instrument(app)).
    No-op when OTEL_ENABLED=false.
    """
    if not OTEL_ENABLED:
        _log.info("otel_tracing_disabled", reason="OTEL_ENABLED=false")
        return

    resource = Resource(attributes={SERVICE_NAME: OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    if OTEL_EXPORTER_OTLP_ENDPOINT:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(
                endpoint=f"{OTEL_EXPORTER_OTLP_ENDPOINT.rstrip('/')}/v1/traces"
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            _log.info(
                "otel_otlp_exporter_configured",
                endpoint=OTEL_EXPORTER_OTLP_ENDPOINT,
                service=OTEL_SERVICE_NAME,
            )
        except Exception as exc:
            _log.warning("otel_otlp_exporter_failed", error=str(exc), fallback="console")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # Dev fallback: print spans to stdout.
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        _log.info("otel_console_exporter_active", service=OTEL_SERVICE_NAME)

    trace.set_tracer_provider(provider)

    # Update module-level tracer to the real one now that the provider is set.
    global tracer
    tracer = trace.get_tracer(OTEL_SERVICE_NAME)

    _log.info("otel_tracing_initialized", service=OTEL_SERVICE_NAME)


def instrument_app(app) -> None:
    """
    Auto-instrument a FastAPI app with OTel spans for every HTTP request.
    Call after init_tracing() and after all routers are registered.
    No-op when OTEL_ENABLED=false.
    """
    if not OTEL_ENABLED:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        _log.info("otel_fastapi_instrumented")
    except Exception as exc:
        _log.warning("otel_fastapi_instrument_failed", error=str(exc))
