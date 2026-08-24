import { NextRequest, NextResponse } from "next/server";
import http from "node:http";
import https from "node:https";

// FASE 12 — Importar sondajes desde un OMF de terceros (Leapfrog / Vulcan /
// Micromine). Proxy MULTIPART idéntico en forma a `borehole/parse-file`: los
// bytes viajan intactos al backend, que es quien lee el contenedor OMF.
//
// Dos diferencias respecto del proxy de CSV, ambas por el tamaño del formato:
// el timeout es mayor (un OMF trae el block model de otro software dentro) y el
// content-type por defecto es binario, no texto.

// Fase 2 (H-21): primero la variable de EJECUCIÓN. Next hornea NEXT_PUBLIC_* en
// tiempo de build, así que una URL horneada apuntaría al puerto equivocado
// cuando el orquestador de escritorio levanta el backend en otro.
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

    const parsedUrl = new URL(`${BACKEND_URL}/borehole/import-omf`);
    const apiKey = process.env.TQ_API_KEY ?? "";
    const isHttps = parsedUrl.protocol === "https:";
    const transport = isHttps ? https : http;

    const { status, text } = await new Promise<{ status: number; text: string }>(
      (resolve, reject) => {
        const options: http.RequestOptions = {
          hostname: parsedUrl.hostname,
          port: parseInt(parsedUrl.port) || (isHttps ? 443 : 80),
          path: parsedUrl.pathname,
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

        httpReq.setTimeout(180 * 1000, () => {
          httpReq.destroy(new Error("Timeout: la lectura del OMF tardó demasiado"));
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
      parsed = { detail: "Respuesta no-JSON del backend al importar el OMF" };
    }

    if (status < 200 || status >= 300) {
      const detail =
        (parsed as { detail?: unknown })?.detail ??
        "Error del backend al importar el OMF";
      return NextResponse.json({ detail, backendStatus: status }, { status });
    }

    return NextResponse.json(parsed, { status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[borehole/import-omf] proxy error:", message);
    return NextResponse.json(
      { detail: "Error interno del proxy", error: message },
      { status: 500 }
    );
  }
}
