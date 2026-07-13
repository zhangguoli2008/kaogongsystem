import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useSession } from "./use-session";

const { mockReplace } = vi.hoisted(() => ({ mockReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/questions",
  useRouter: () => ({ replace: mockReplace }),
}));

function SessionProbe() {
  useSession();
  return null;
}

describe("useSession", () => {
  it("clears an unauthorized session and redirects with a local returnTo", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const removeQueries = vi.spyOn(queryClient, "removeQueries");
    mockReplace.mockReset();
    window.history.replaceState({}, "", "/questions?module=%E6%95%B0%E9%87%8F%E5%85%B3%E7%B3%BB");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ code: "unauthorized", message: "未登录" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProbe />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith(
        "/login?returnTo=%2Fquestions%3Fmodule%3D%25E6%2595%25B0%25E9%2587%258F%25E5%2585%25B3%25E7%25B3%25BB",
      ),
    );
    expect(removeQueries).toHaveBeenCalledWith({ queryKey: ["session"], exact: true });
    expect(queryClient.getQueryData(["session"])).toBeUndefined();
  });
});
