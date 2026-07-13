import { isIP } from "node:net";

const PRIVATE_API_URL = "http://api.railway.internal:8000";
const PRIVATE_PROXY_HEADER = "x-kaogong-proxy-secret";
const HOST_LABEL = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;
const INTERNAL_PROXY_SECRET = /^[0-9a-f]{64}$/;
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

function internalProxySecret(): string | null {
  const secret = process.env.INTERNAL_PROXY_SECRET;
  return secret && INTERNAL_PROXY_SECRET.test(secret) ? secret : null;
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
    if (
      !blocked.has(normalized) &&
      normalized !== "set-cookie" &&
      normalized !== PRIVATE_PROXY_HEADER
    ) {
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

function exposesPrivateHostname(value: string): boolean {
  let decoded = value;
  for (let pass = 0; pass < 8; pass += 1) {
    if (decoded.toLowerCase().includes("railway.internal")) return true;
    const next = decoded.replace(
      /%([0-9a-f]{2})/gi,
      (_match, octet: string) =>
        String.fromCharCode(Number.parseInt(octet, 16)),
    );
    if (next === decoded) return false;
    decoded = next;
  }
  return (
    /%[0-9a-f]{2}/i.test(decoded) ||
    decoded.toLowerCase().includes("railway.internal")
  );
}

function safeResponseHeaders(
  upstreamHeaders: Headers,
  publicDomain: string,
  target: URL,
): Headers | null {
  const headers = copyEndToEndHeaders(upstreamHeaders, true);
  const location = headers.get("location");
  if (location === null) return headers;

  let redirect: URL;
  try {
    redirect = new URL(location, target);
  } catch {
    return null;
  }

  const privateTarget =
    redirect.protocol === "http:" &&
    redirect.hostname === "api.railway.internal" &&
    (redirect.port === "" || redirect.port === "8000");
  const publicTarget =
    redirect.protocol === "https:" &&
    redirect.hostname === publicDomain &&
    redirect.port === "";
  const apiPath =
    redirect.pathname === "/api/v1" || redirect.pathname.startsWith("/api/v1/");
  if ((!privateTarget && !publicTarget) || !apiPath) return null;

  const rewrittenLocation = `${redirect.pathname}${redirect.search}${redirect.hash}`;
  if (exposesPrivateHostname(rewrittenLocation)) return null;
  headers.set("location", rewrittenLocation);
  return headers;
}

export async function proxyApiRequest(
  request: Request,
  path: string[],
): Promise<Response> {
  const publicDomain = railwayPublicDomain();
  const proxySecret = internalProxySecret();
  if (
    process.env.API_INTERNAL_URL !== PRIVATE_API_URL ||
    !publicDomain ||
    !proxySecret
  ) {
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
  const clientIp = request.headers.get("x-real-ip");
  headers.delete("x-real-ip");
  if (clientIp !== null && isIP(clientIp) !== 0) {
    // Railway's public edge owns X-Real-IP. Revalidating and replacing the
    // copied value keeps a malformed browser-supplied header off the private hop.
    headers.set("x-real-ip", clientIp);
  }
  headers.set("x-forwarded-host", publicDomain);
  headers.set("x-forwarded-proto", "https");
  headers.set(PRIVATE_PROXY_HEADER, proxySecret);

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
    const responseHeaders = safeResponseHeaders(upstream.headers, publicDomain, target);
    if (responseHeaders === null) {
      await upstream.body?.cancel();
      return safeUnavailable();
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch {
    return safeUnavailable();
  }
}
