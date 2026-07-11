import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "./page";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

describe("DashboardPage", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("loads the dashboard contract and keeps capture as a quick action", async () => {
    apiFetchMock.mockResolvedValue({
      today_review: {
        daily_review_limit: 20,
        pending: [],
        completed: [],
        completed_count: 0,
        total: 0,
      },
      current_question: null,
      recent_questions: [],
      weak_modules: [],
      trend_7d: [],
      ai_advice: "先录入错题，系统会根据你的数据生成学习建议。",
      provider_mode: "demo",
    });

    renderWithProviders(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "今日学习概览" })).toBeVisible();
    expect(await screen.findByRole("heading", { name: "今日复习" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "录入错题" })[0]).toHaveAttribute(
      "href",
      "/questions/new",
    );
    expect(apiFetchMock).toHaveBeenCalledWith("/dashboard");
  });
});
