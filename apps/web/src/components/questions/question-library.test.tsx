import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionLibrary } from "./question-library";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

const replace = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  usePathname: () => "/questions",
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams("page=1&module=%E8%B5%84%E6%96%99%E5%88%86%E6%9E%90"),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

describe("QuestionLibrary", () => {
  beforeEach(() => {
    replace.mockReset();
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 21 });
  });

  it("moves pagination through URL state while preserving filters", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionLibrary />);

    await user.click(await screen.findByRole("button", { name: "下一页" }));

    expect(replace).toHaveBeenCalledWith(
      "/questions?page=2&module=%E8%B5%84%E6%96%99%E5%88%86%E6%9E%90",
    );
  });
});
