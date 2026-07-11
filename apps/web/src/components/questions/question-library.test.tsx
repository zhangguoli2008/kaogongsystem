import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionLibrary } from "./question-library";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

const replace = vi.hoisted(() => vi.fn());
const currentSearch = vi.hoisted(() => ({ value: "page=1&module=%E8%B5%84%E6%96%99%E5%88%86%E6%9E%90" }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/questions",
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(currentSearch.value),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

describe("QuestionLibrary", () => {
  beforeEach(() => {
    currentSearch.value = "page=1&module=%E8%B5%84%E6%96%99%E5%88%86%E6%9E%90";
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

  it("converts date filters from browser-local day boundaries to ISO timestamps", async () => {
    currentSearch.value = "created_from=2026-07-10&created_to=2026-07-10";
    renderWithProviders(<QuestionLibrary />);

    const expected = new URLSearchParams();
    expected.set("created_from", new Date(2026, 6, 10, 0, 0, 0, 0).toISOString());
    expected.set("created_to", new Date(2026, 6, 10, 23, 59, 59, 999).toISOString());
    expected.set("page", "1");
    expected.set("page_size", "20");

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(`/questions?${expected.toString()}`);
    });
  });
});
