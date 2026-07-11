import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "./page";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const emptyReview = {
  daily_review_limit: 20,
  pending: [],
  completed: [],
  completed_count: 0,
  total: 0,
};

describe("ReviewPage", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("loads today's sequence and persists an allowed daily limit", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path, init) => {
      if (path === "/reviews/today") return emptyReview;
      if (path === "/reviews/settings" && init?.method === "PATCH") {
        return { daily_review_limit: 30 };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    renderWithProviders(<ReviewPage />);

    const limit = await screen.findByRole("combobox", { name: "每日复习数量" });
    expect(limit).toHaveValue("20");
    await user.selectOptions(limit, "30");

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/reviews/settings", {
        method: "PATCH",
        body: JSON.stringify({ daily_review_limit: 30 }),
      });
    });
    expect(screen.getByText("每日数量已更新")).toBeVisible();
  });
});
