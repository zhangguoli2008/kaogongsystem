import { describe, expect, it } from "vitest";

import { resolveReturnTo } from "./return-to";

describe("resolveReturnTo", () => {
  it("keeps a local protected path and its query string", () => {
    expect(resolveReturnTo("/questions?module=%E6%95%B0%E9%87%8F%E5%85%B3%E7%B3%BB")).toBe(
      "/questions?module=%E6%95%B0%E9%87%8F%E5%85%B3%E7%B3%BB",
    );
  });

  it.each(["https://evil.example", "//evil.example", "/login", "/register", "dashboard", null])(
    "falls back to dashboard for unsafe returnTo %s",
    (value) => {
      expect(resolveReturnTo(value)).toBe("/dashboard");
    },
  );
});
