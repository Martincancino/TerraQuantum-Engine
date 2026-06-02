import { NextRequest, NextResponse } from "next/server";
import http from "node:http";
import https from "node:https";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL ||
  process.env.TERRAQUANTUM_BACKEND_URL ||
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

    const parsedUrl = new URL(`${BACKEND_URL}/gravity-import/invert`);
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

        // Override undici's hardcoded 300s default — allow up to 20 min
        httpReq.setTimeout(20 * 60 * 1000, () => {
          httpReq.destroy(new Error("Timeout: inversión tardó más de 20 minutos"));
        });

        httpReq.on("error", reject);
        httpReq.write(body);
        httpReq.end();
      }
    );

    let data: unknown;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      return NextResponse.json(
        {
          detail: `Error del backend (HTTP ${status})`,
          raw: text.slice(0, 1000),
        },
        { status: status || 500 }
      );
    }

    if (status < 200 || status >= 300) {
      const detail =
        data !== null && typeof data === "object" && !Array.isArray(data)
          ? ((data as Record<string, unknown>).detail ?? "Error del backend importador")
          : "Error del backend importador";
      return NextResponse.json({ detail, backendStatus: status }, { status });
    }

    return NextResponse.json(data, { status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    console.error("[gravity-import/invert] proxy error:", message);
    return NextResponse.json(
      { detail: "Error interno del proxy", error: message },
      { status: 500 }
    );
  }
}
