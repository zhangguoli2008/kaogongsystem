import { expect, it, vi } from "vitest";

import { GET } from "./route";

it("reports Web liveness without calling the API", async () => {
  process.env.API_INTERNAL_URL = "http://api.railway.internal:8000";
  const upstream = vi.fn();
  vi.stubGlobal("fetch", upstream);

  const response = GET();

  expect(upstream).not.toHaveBeenCalled();
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ status: "ok" });
  delete process.env.API_INTERNAL_URL;
});
