import { NextRequest, NextResponse } from "next/server";
import http from "node:http";
import https from "node:https";

// FASE R4 — BFF: proxya el ensamblado del "paquete CSV" auto-contenido al backend
// y devuelve el archivo text/csv descargable. La normalización + decisión de combo
// multimodal viven 100% en el backend (build-package); aquí solo se reenvía el
// multipart (file + magnetic_file? + config_json + boreholes_json) y los query
// params (data_type, strict, allow_g_raw), conservando el Content-Disposition.

// Fase 2 (H-21): primero la variable de EJECUCIÓN. Next hornea NEXT_PUBLIC_*
// en tiempo de build, así que si existía un .env.local al construir, este
// proxy quedaría clavado a ese puerto e ignoraría el que fija el orquestador
// de escritorio cuando el 8010 está ocupado.
const BACKEND_URL =
  process.env.TERRAQUANTUM_BACKEND_URL ||
  process.env.NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL ||
  "http://127.0.0.1:8010";

async function buildMultipartBody(
  formData: FormData
): Promise<{ body: Buffer; boundary: string }> {
  const boundary = `TQBoundary${Date.now().toString(36)}x${Math.floor(Math.random() * 1e9).toString(36)}`;
  const parts: Buffer[] = [];

  for (const [key, value] of formData.entries()) {
    if (value instanceof File) {
      const bytes = await value.arrayBuffer();
      parts.push(
        Buffer.from(
          `--${boundary}\r\nContent-Disposition: form-data; name="${key}"; filename="${value.name}"\r\nContent-Type: ${value.type || "application/octet-stream"}\r\n\r\n`
        )
      );
      parts.push(Buffer.from(bytes));
      parts.push(Buffer.from("\r\n"));
    } else {
      parts.push(
        Buffer.from(
          `--${boundary}\r\nContent-Disposition: form-data; name="${key}"\r\n\r\n${value}\r\n`
        )
      );
    }
  }
  parts.push(Buffer.from(`--${boundary}--\r\n`));

  return { body: Buffer.concat(parts), boundary };
}

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const { body, boundary } = await buildMultipartBody(formData);

    const parsedUrl = new URL(`${BACKEND_URL}/v2/gravity-import/build-package`);
    for (const key of ["data_type", "strict", "allow_g_raw"]) {
      const v = req.nextUrl.searchParams.get(key);
      if (v !== null) parsedUrl.searchParams.set(key, v);
    }
    const apiKey = process.env.TQ_API_KEY ?? "";
    const isHttps = parsedUrl.protocol === "https:";
    const transport = isHttps ? https : http;

    const { status, contentType, disposition, text } = await new Promise<{
      status: number;
      contentType: string;
      disposition: string;
      text: string;
    }>((resolve, reject) => {
      const options: http.RequestOptions = {
        hostname: parsedUrl.hostname,
        port: parseInt(parsedUrl.port) || (isHttps ? 443 : 80),
        path: parsedUrl.pathname + parsedUrl.search,
        method: "POST",
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": body.length,
          ...(apiKey ? { "X-TQ-API-Key": apiKey } : {}),
        },
      };

      const httpReq = transport.request(options, (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () =>
          resolve({
            status: res.statusCode ?? 500,
            contentType: String(res.headers["content-type"] || ""),
            disposition: String(res.headers["content-disposition"] || ""),
            text: Buffer.concat(chunks).toString("utf8"),
          })
        );
        res.on("error", reject);
      });

      httpReq.setTimeout(2 * 60 * 1000, () => {
        httpReq.destroy(new Error("Timeout: el ensamblado del paquete tardó demasiado"));
      });
      httpReq.on("error", reject);
      httpReq.write(body);
      httpReq.end();
    });

    if (status < 200 || status >= 300) {
      let detail: unknown = "Error del backend al ensamblar el paquete";
      try {
        const parsed = JSON.parse(text);
        detail = parsed?.detail ?? detail;
      } catch {
        /* mantiene el mensaje genérico */
      }
      return NextResponse.json({ detail, backendStatus: status }, { status });
    }

    return new NextResponse(text, {
      status,
      headers: {
        "Content-Type": contentType || "text/csv; charset=utf-8",
        "Content-Disposition": disposition || 'attachment; filename="package.tqpkg.csv"',
      },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[gravity-import/build-package] proxy error:", message);
    return NextResponse.json(
      { detail: "Error interno del proxy", error: message },
      { status: 500 }
    );
  }
}
