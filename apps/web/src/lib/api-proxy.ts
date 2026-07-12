const PRIVATE_API_URL = "http://api.railway.internal:8000";
const HOST_LABEL = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;
const LOCAL_HOSTNAME_SUFFIXES = new Set(["internal", "local", "localhost"]);

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type NodeRequestInit = RequestInit & { duplex?: "half" };

function safeUnavailable(): Response {
  return Response.json(
    { code: "api_proxy_unavailable", message: "服务暂时不可用" },
    { status: 503 },
  );
}

function railwayPublicDomain(): string | null {
  const domain = process.env.RAILWAY_PUBLIC_DOMAIN;
  if (!domain || domain.length > 253) return null;

  let parsed: URL;
  try {
    parsed = new URL(`https://${domain}`);
  } catch {
    return null;
  }

  const labels = domain.split(".");
  const suffix = labels.at(-1);
  if (
    parsed.hostname !== domain ||
    parsed.host !== domain ||
    labels.length < 2 ||
    labels.some((label) => label.length > 63 || !HOST_LABEL.test(label)) ||
    !suffix ||
    LOCAL_HOSTNAME_SUFFIXES.has(suffix) ||
    (labels.length === 4 && labels.every((label) => /^\d+$/.test(label)))
  ) {
    return null;
  }

  return domain;
}

function blockedHeaderNames(headers: Headers): Set<string> {
  const blocked = new Set(HOP_BY_HOP_HEADERS);
  for (const name of headers.get("connection")?.split(",") ?? []) {
    const normalized = name.trim().toLowerCase();
    if (normalized) blocked.add(normalized);
  }
  return blocked;
}

function copyEndToEndHeaders(headers: Headers, copyCookies = false): Headers {
  const blocked = blockedHeaderNames(headers);
  const copied = new Headers();

  for (const [name, value] of headers) {
    const normalized = name.toLowerCase();
    if (!blocked.has(normalized) && normalized !== "set-cookie") {
      copied.append(name, value);
    }
  }

  if (copyCookies && !blocked.has("set-cookie")) {
    for (const cookie of headers.getSetCookie()) {
      copied.append("set-cookie", cookie);
    }
  }

  return copied;
}

export async function proxyApiRequest(
  request: Request,
  path: string[],
): Promise<Response> {
  const publicDomain = railwayPublicDomain();
  if (process.env.API_INTERNAL_URL !== PRIVATE_API_URL || !publicDomain) {
    return safeUnavailable();
  }
  if (path.length === 0 || path.some((segment) => !segment || segment === "." || segment === "..")) {
    return safeUnavailable();
  }

  let target: URL;
  let incoming: URL;
  try {
    incoming = new URL(request.url);
    const suffix = path.map(encodeURIComponent).join("/");
    target = new URL(`/api/v1/${suffix}`, PRIVATE_API_URL);
    target.search = incoming.search;
  } catch {
    return safeUnavailable();
  }

  const headers = copyEndToEndHeaders(request.headers);
  headers.set("x-forwarded-host", publicDomain);
  headers.set("x-forwarded-proto", "https");

  const hasBody = request.method !== "GET" && request.method !== "HEAD" && request.body !== null;
  const init: NodeRequestInit = {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    cache: "no-store",
    redirect: "manual",
    signal: request.signal,
  };
  if (hasBody) init.duplex = "half";

  try {
    const upstream = await fetch(target, init);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: copyEndToEndHeaders(upstream.headers, true),
    });
  } catch {
    return safeUnavailable();
  }
}
