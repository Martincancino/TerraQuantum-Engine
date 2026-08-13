import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "../_lib/backend";

const ALLOWED_TEXTURE_HOSTS = new Set([
  "127.0.0.1",
  "localhost",
  "earthengine.googleapis.com",
  "storage.googleapis.com",
]);

function parseAllowedUrl(rawUrl: string): URL | null {
  try {
    const url = new URL(rawUrl);

    if (!["http:", "https:"].includes(url.protocol)) return null;
    if (!ALLOWED_TEXTURE_HOSTS.has(url.hostname)) return null;

    return url;
  } catch {
    return null;
  }
}

async function fetchAllowedImage(url: URL, signal: AbortSignal, redirects = 0) {
  if (redirects > 3) {
    return { error: "Demasiados redirects al cargar textura.", status: 508 };
  }

  const response = await fetch(url, {
    cache: "no-store",
    redirect: "manual",
    signal,
  });

  if (response.status >= 300 && response.status < 400) {
    const location = response.headers.get("location");
    if (!location) {
      return { error: "Redirect de textura sin Location.", status: 502 };
    }

    const nextUrl = parseAllowedUrl(new URL(location, url).toString());
    if (!nextUrl) {
      return { error: "Host de textura no permitido.", status: 400 };
    }

    return fetchAllowedImage(nextUrl, signal, redirects + 1);
  }

  return { response };
}

export async function GET(req: NextRequest) {
  const rawUrl = req.nextUrl.searchParams.get("url");

  if (!rawUrl) {
    return NextResponse.json({ detail: "url requerida" }, { status: 400 });
  }

  // Fase 2 (H-21): una ruta RELATIVA es un asset del backend y se resuelve
  // AQUÍ, en el servidor, contra el backend vigente. Antes llegaba ya absoluta
  // desde el navegador con el puerto horneado en tiempo de build.
  const absoluteUrl = /^https?:\/\//i.test(rawUrl) ? rawUrl : buildBackendUrl(rawUrl);
  const textureUrl = parseAllowedUrl(absoluteUrl);

  if (!textureUrl) {
    return NextResponse.json(
      { detail: "URL de textura no permitida." },
      { status: 400 }
    );
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  try {
    const result = await fetchAllowedImage(textureUrl, controller.signal);

    if ("error" in result) {
      return NextResponse.json(
        { detail: result.error },
        { status: result.status }
      );
    }

    const upstream = result.response;

    if (!upstream.ok) {
      return NextResponse.json(
        { detail: "No se pudo cargar la textura de terreno." },
        { status: upstream.status || 502 }
      );
    }

    const contentType = upstream.headers.get("content-type") || "";

    if (!contentType.toLowerCase().startsWith("image/")) {
      return NextResponse.json(
        { detail: "La respuesta de textura no es una imagen." },
        { status: 502 }
      );
    }

    const imageBytes = await upstream.arrayBuffer();

    return new NextResponse(imageBytes, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch (error: unknown) {
    const isTimeout =
      error instanceof Error &&
      (error.name === "AbortError" ||
        error.message.toLowerCase().includes("aborted"));

    return NextResponse.json(
      { detail: "Error cargando textura de terreno." },
      { status: isTimeout ? 504 : 502 }
    );
  } finally {
    clearTimeout(timeout);
  }
}
