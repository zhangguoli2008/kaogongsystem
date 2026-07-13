import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as apiRoute from "../app/api/v1/[...path]/route";
import { proxyApiRequest } from "./api-proxy";

const PRIVATE_API_URL = "http://api.railway.internal:8000";
const PUBLIC_DOMAIN = "web-production-1234.up.railway.app";
const INTERNAL_PROXY_SECRET = "a".repeat(64);
const DEEPLY_ENCODED_PRIVATE_HOST = Array.from({ length: 6 }).reduce<string>(
  (value) => value.replaceAll("%", "%25"),
  "%61pi%2Erailway%2Einternal",
);
const unavailablePayload = {
  code: "api_proxy_unavailable",
  message: "服务暂时不可用",
};

type NodeRequestInit = RequestInit & { duplex?: "half" };
type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

beforeEach(() => {
  process.env.INTERNAL_PROXY_SECRET = INTERNAL_PROXY_SECRET;
});

afterEach(() => {
  delete process.env.API_INTERNAL_URL;
  delete process.env.INTERNAL_PROXY_SECRET;
  delete process.env.RAILWAY_PUBLIC_DOMAIN;
});

describe("proxyApiRequest", () => {
  it("fails safely when the private API target is missing", async () => {
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/me"),
      ["auth", "me"],
    );

    expect(upstream).not.toHaveBeenCalled();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual(unavailablePayload);
  });

  it.each([
    "",
    "https://api.railway.internal:8000",
    "http://external.example:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://api.railway.internal.evil.example:8000",
    "http://evil-api.railway.internal:8000",
    "http://user:pass@api.railway.internal:8000",
    "http://api.railway.internal",
    "http://api.railway.internal:9000",
    "http://api.railway.internal:8000/",
    "http://api.railway.internal:8000/api",
    "http://api.railway.internal:8000?target=external",
    "http://api.railway.internal:8000#fragment",
    "http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000",
  ])("rejects an unsafe private API target without fetching: %s", async (target) => {
    process.env.API_INTERNAL_URL = target;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/me"),
      ["auth", "me"],
    );

    expect(upstream).not.toHaveBeenCalled();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual(unavailablePayload);
  });

  it.each([
    undefined,
    "",
    "WEB-PRODUCTION-1234.up.railway.app",
    "web-production-1234.up.railway.app.",
    " web-production-1234.up.railway.app",
    "web-production-1234.up.railway.app ",
    "https://web-production-1234.up.railway.app",
    "user:pass@web-production-1234.up.railway.app",
    "web-production-1234.up.railway.app/path",
    "web-production-1234.up.railway.app?query=value",
    "web-production-1234.up.railway.app#fragment",
    "web-production-1234.up.railway.app:443",
    "localhost",
    "app.localhost",
    "127.0.0.1",
    "[::1]",
    "single-label",
    "-invalid.example.com",
    "invalid-.example.com",
    "invalid..example.com",
    "invalid_name.example.com",
  ])("rejects an unsafe Railway public domain without fetching: %s", async (domain) => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    if (domain === undefined) {
      delete process.env.RAILWAY_PUBLIC_DOMAIN;
    } else {
      process.env.RAILWAY_PUBLIC_DOMAIN = domain;
    }
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("http://0.0.0.0:3000/api/v1/auth/me"),
      ["auth", "me"],
    );

    expect(upstream).not.toHaveBeenCalled();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual(unavailablePayload);
  });

  it.each([
    undefined,
    "",
    "short",
    "A".repeat(64),
    "G".repeat(64),
    "a".repeat(63),
    `${"a".repeat(64)}\n`,
  ])(
    "rejects a missing or malformed internal proxy secret: %s",
    async (secret) => {
      process.env.API_INTERNAL_URL = PRIVATE_API_URL;
      process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
      if (secret === undefined) {
        delete process.env.INTERNAL_PROXY_SECRET;
      } else {
        process.env.INTERNAL_PROXY_SECRET = secret;
      }
      const upstream = vi.fn();
      vi.stubGlobal("fetch", upstream);

      const response = await proxyApiRequest(
        new Request("https://web.example/api/v1/auth/me"),
        ["auth", "me"],
      );

      expect(upstream).not.toHaveBeenCalled();
      expect(response.status).toBe(503);
      expect(await response.json()).toEqual(unavailablePayload);
    },
  );

  it("trusts the Railway public domain instead of the listener or spoofed headers", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn<FetchLike>().mockResolvedValue(new Response(null));
    vi.stubGlobal("fetch", upstream);

    await proxyApiRequest(
      new Request("http://0.0.0.0:3000/api/v1/auth/me?source=listener", {
        headers: {
          host: "attacker.example",
          "x-forwarded-host": "spoofed.example",
          "x-forwarded-proto": "http",
          "x-railway-edge": "railway/asia-southeast1-eqsg3a",
          "x-real-ip": "203.0.113.42",
          "x-kaogong-proxy-secret": "attacker-controlled",
        },
      }),
      ["auth", "me"],
    );

    const [target, init] = upstream.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(String(target)).toBe(`${PRIVATE_API_URL}/api/v1/auth/me?source=listener`);
    expect(headers.get("host")).toBeNull();
    expect(headers.get("x-forwarded-host")).toBe(PUBLIC_DOMAIN);
    expect(headers.get("x-forwarded-proto")).toBe("https");
    expect(headers.get("x-railway-edge")).toBe(
      "railway/asia-southeast1-eqsg3a",
    );
    expect(headers.get("x-real-ip")).toBe("203.0.113.42");
    expect(headers.get("x-kaogong-proxy-secret")).toBe(INTERNAL_PROXY_SECRET);
  });

  it("drops an invalid Railway client-IP header before private forwarding", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn<FetchLike>().mockResolvedValue(new Response(null));
    vi.stubGlobal("fetch", upstream);

    await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/me", {
        headers: { "x-real-ip": "spoofed, 203.0.113.42" },
      }),
      ["auth", "me"],
    );

    const headers = new Headers(upstream.mock.calls[0][1]?.headers);
    expect(headers.get("x-real-ip")).toBeNull();
  });

  it.each([
    "http://api.railway.internal:8000/api/v1/questions?source=slash",
    "http://api.railway.internal/api/v1/questions?source=slash",
    "/api/v1/questions?source=slash",
  ])("rewrites a safe upstream redirect to the Web origin: %s", async (location) => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn<FetchLike>().mockResolvedValue(
      new Response(null, {
        status: 307,
        headers: { location },
      }),
    );
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/questions/"),
      ["questions"],
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "/api/v1/questions?source=slash",
    );
  });

  it("preserves an encoded literal percent in a safe API redirect", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const location = "/api/v1/questions?discount=10%25";
    const upstream = vi.fn<FetchLike>().mockResolvedValue(
      new Response(null, {
        status: 307,
        headers: { location },
      }),
    );
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/questions/"),
      ["questions"],
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(location);
  });

  it.each([
    "https://evil.example/steal",
    "//evil.example/steal",
    "http://api.railway.internal:8000/private",
    "http://api.railway.internal:8000/api/v1/questions?next=api.railway.internal",
    "http://api.railway.internal:8000/api/v1/questions#api.railway.internal",
    "http://api.railway.internal:8000/api/v1/questions?next=api%2Erailway%2Einternal",
    "http://api.railway.internal:8000/api/v1/questions?next=%2561pi%252Erailway%252Einternal",
    `http://api.railway.internal:8000/api/v1/questions?next=${DEEPLY_ENCODED_PRIVATE_HOST}`,
  ])("fails closed for an unsafe upstream redirect: %s", async (location) => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn<FetchLike>().mockResolvedValue(
      new Response(null, {
        status: 307,
        headers: { location },
      }),
    );
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/questions/"),
      ["questions"],
    );

    expect(response.status).toBe(503);
    expect(response.headers.get("location")).toBeNull();
    expect(await response.json()).toEqual(unavailablePayload);
  });

  it("streams the request and response while preserving end-to-end metadata", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const firstCookie =
      "kaogong_session=token; Path=/; Expires=Wed, 21 Oct 2015 07:28:00 GMT; HttpOnly; Secure; SameSite=Lax";
    const secondCookie = "csrf=second; Path=/; Secure; SameSite=Lax";
    const upstreamHeaders = new Headers({
      connection: "keep-alive, x-remove-response",
      "content-length": "999",
      "content-type": "application/json",
      host: "api.railway.internal",
      "keep-alive": "timeout=5",
      "proxy-authenticate": "Basic",
      "proxy-authorization": "Basic secret",
      "proxy-connection": "keep-alive",
      te: "trailers",
      trailer: "x-checksum",
      "transfer-encoding": "chunked",
      upgrade: "websocket",
      "x-remove-response": "private-response-value",
      "x-request-id": "request-1",
      "x-kaogong-proxy-secret": "must-not-leak",
    });
    upstreamHeaders.append("set-cookie", firstCookie);
    upstreamHeaders.append("set-cookie", secondCookie);
    const upstream = vi
      .fn<FetchLike>()
      .mockResolvedValue(
        new Response(JSON.stringify({ email: "learner@example.com" }), {
          status: 418,
          statusText: "Upstream teapot",
          headers: upstreamHeaders,
        }),
      );
    vi.stubGlobal("fetch", upstream);

    const request = new Request(
      "https://web.example:8443/api/v1/auth/register?source=smoke&tag=a%2Fb",
      {
        method: "POST",
        headers: {
          connection: "keep-alive, x-remove-request",
          "content-length": "72",
          "content-type": "application/json",
          cookie: "existing=value",
          host: "attacker.example",
          "keep-alive": "timeout=5",
          "proxy-authenticate": "Basic",
          "proxy-authorization": "Basic secret",
          "proxy-connection": "keep-alive",
          te: "trailers",
          trailer: "x-checksum",
          "transfer-encoding": "chunked",
          upgrade: "websocket",
          "x-forwarded-host": "spoofed.example",
          "x-forwarded-proto": "http",
          "x-keep-request": "public-request-value",
          "x-remove-request": "private-request-value",
        },
        body: JSON.stringify({
          email: "learner@example.com",
          password: "strong-pass-123",
        }),
      },
    );

    const response = await proxyApiRequest(request, ["auth", "register"]);

    expect(upstream).toHaveBeenCalledTimes(1);
    const [target, rawInit] = upstream.mock.calls[0];
    const init = rawInit as NodeRequestInit;
    const requestHeaders = new Headers(init.headers);
    expect(String(target)).toBe(
      `${PRIVATE_API_URL}/api/v1/auth/register?source=smoke&tag=a%2Fb`,
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBe(request.body);
    expect(init.duplex).toBe("half");
    expect(init.signal).toBe(request.signal);
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("manual");
    expect(requestHeaders.get("cookie")).toBe("existing=value");
    expect(requestHeaders.get("content-type")).toBe("application/json");
    expect(requestHeaders.get("x-keep-request")).toBe("public-request-value");
    expect(requestHeaders.get("x-forwarded-host")).toBe(PUBLIC_DOMAIN);
    expect(requestHeaders.get("x-forwarded-proto")).toBe("https");

    const hopByHopHeaders = [
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
    ];
    for (const name of hopByHopHeaders) {
      expect(requestHeaders.get(name), `request header ${name}`).toBeNull();
      expect(response.headers.get(name), `response header ${name}`).toBeNull();
    }
    expect(requestHeaders.get("x-remove-request")).toBeNull();
    expect(response.headers.get("x-remove-response")).toBeNull();
    expect(response.headers.get("x-kaogong-proxy-secret")).toBeNull();

    expect(response.status).toBe(418);
    expect(response.statusText).toBe("Upstream teapot");
    expect(response.headers.get("content-type")).toBe("application/json");
    expect(response.headers.get("x-request-id")).toBe("request-1");
    expect(response.headers.getSetCookie()).toEqual([firstCookie, secondCookie]);
    expect(await response.json()).toEqual({ email: "learner@example.com" });
  });

  it("encodes catch-all path segments and preserves the original query", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn(async () => new Response(null));
    vi.stubGlobal("fetch", upstream);

    await proxyApiRequest(
      new Request("https://web.example/api/v1/questions/id?filter=a%2Fb&filter=c"),
      ["questions", "id/with?reserved#characters"],
    );

    expect(String(upstream.mock.calls[0][0])).toBe(
      `${PRIVATE_API_URL}/api/v1/questions/id%2Fwith%3Freserved%23characters?filter=a%2Fb&filter=c`,
    );
  });

  it.each([
    [["."]],
    [[".."]],
    [["questions", ""]],
    [[""]],
    [[]],
  ])(
    "rejects unsafe catch-all path segments without fetching: %j",
    async (path) => {
      process.env.API_INTERNAL_URL = PRIVATE_API_URL;
      process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
      const upstream = vi.fn();
      vi.stubGlobal("fetch", upstream);

      const response = await proxyApiRequest(
        new Request("https://web.example/api/v1/questions"),
        path,
      );

      expect(upstream).not.toHaveBeenCalled();
      expect(response.status).toBe(503);
      expect(await response.json()).toEqual(unavailablePayload);
    },
  );

  it.each(["GET", "HEAD"])("does not attach a body to %s requests", async (method) => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn<FetchLike>().mockResolvedValue(new Response(null));
    vi.stubGlobal("fetch", upstream);
    const request = new Request("https://web.example/api/v1/auth/me", { method });

    await proxyApiRequest(request, ["auth", "me"]);

    const init = upstream.mock.calls[0][1] as NodeRequestInit;
    expect(init.body).toBeUndefined();
    expect(init.duplex).toBeUndefined();
    expect(init.signal).toBe(request.signal);
  });

  it("does not enable streaming mode for a request without a body", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn<FetchLike>().mockResolvedValue(new Response(null));
    vi.stubGlobal("fetch", upstream);

    await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/logout", { method: "POST" }),
      ["auth", "logout"],
    );

    const init = upstream.mock.calls[0][1] as NodeRequestInit;
    expect(init.body).toBeUndefined();
    expect(init.duplex).toBeUndefined();
  });

  it("returns a fixed response when the upstream fetch fails", async () => {
    process.env.API_INTERNAL_URL = PRIVATE_API_URL;
    process.env.RAILWAY_PUBLIC_DOMAIN = PUBLIC_DOMAIN;
    const upstream = vi.fn(async () => {
      throw new Error(`connect failed for ${PRIVATE_API_URL}/secret-details`);
    });
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/me"),
      ["auth", "me"],
    );

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual(unavailablePayload);
  });
});

describe("catch-all API route", () => {
  it("exports every supported method with the Node dynamic runtime contract", () => {
    expect(Object.keys(apiRoute).sort()).toEqual(
      [
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
        "dynamic",
        "runtime",
      ].sort(),
    );
    expect(apiRoute.runtime).toBe("nodejs");
    expect(apiRoute.dynamic).toBe("force-dynamic");
  });
});
