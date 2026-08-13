import { NextRequest, NextResponse } from "next/server";
import http from "node:http";
import https from "node:https";

// BFF: proxya el PARSEO COMPLETO de filas al backend (/v2/gravity-import/
// parse-rows). El cliente NO parsea CSV (regla: cero detección de formato en
// TS — el sniffer y el lector oficial viven en el backend); aquí solo se
// reenvía el multipart y se devuelve {headers, rows, sniff_report}.

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

    const parsedUrl = new URL(`${BACKEND_URL}/v2/gravity-import/parse-rows`);
    const maxRows = req.nextUrl.searchParams.get("max_rows");
    if (maxRows !== null) parsedUrl.searchParams.set("max_rows", maxRows);
    const apiKey = process.env.TQ_API_KEY ?? "";
    const isHttps = parsedUrl.protocol === "https:";
    const transport = isHttps ? https : http;

    const { status, text } = await new Promise<{ status: number; text: string }>(
      (resolve, reject) => {
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
              text: Buffer.concat(chunks).toString("utf8"),
            })
          );
          res.on("error", reject);
        });

        httpReq.setTimeout(120 * 1000, () => {
          httpReq.destroy(new Error("Timeout: el parseo del CSV tardó demasiado"));
        });
        httpReq.on("error", reject);
        httpReq.write(body);
        httpReq.end();
      }
    );

    let parsed: unknown = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { detail: "Respuesta no-JSON del backend al parsear filas" };
    }

    if (status < 200 || status >= 300) {
      const detail =
        (parsed as { detail?: unknown })?.detail ??
        "Error del backend al parsear el CSV";
      return NextResponse.json({ detail, backendStatus: status }, { status });
    }

    return NextResponse.json(parsed, { status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[gravity-import/parse-rows] proxy error:", message);
    return NextResponse.json(
      { detail: "Error interno del proxy", error: message },
      { status: 500 }
    );
  }
}
