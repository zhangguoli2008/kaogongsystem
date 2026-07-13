import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("requests fresh AI advice only through one explicit POST and updates the card", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path, init) => {
      if (path === "/dashboard") {
        return {
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
          ai_advice: "旧建议",
          provider_mode: "demo",
        };
      }
      if (path === "/analytics/advice" && init?.method === "POST") {
        return {
          advice: "新的个性化建议",
          provider_name: "demo",
          model_name: null,
          is_demo: true,
        };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("旧建议")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "刷新学习建议" }));

    expect(await screen.findByText("新的个性化建议")).toBeVisible();
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.filter(([path]) => path === "/analytics/advice")).toHaveLength(1);
      expect(apiFetchMock.mock.calls.filter(([path]) => path === "/dashboard")).toHaveLength(1);
    });
    expect(apiFetchMock).toHaveBeenCalledWith("/analytics/advice", { method: "POST" });
  });

  it("keeps the previous advice and lets the user retry a failed refresh", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/dashboard") {
        return {
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
          ai_advice: "保留这条建议",
          provider_mode: "demo",
        };
      }
      if (path === "/analytics/advice") throw new Error("network down");
      throw new Error(`unexpected request: ${path}`);
    });

    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("保留这条建议")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "刷新学习建议" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "AI 建议刷新失败，请检查网络后重试。",
    );
    expect(screen.getByText("保留这条建议")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重试刷新建议" }));
    await waitFor(() => {
      expect(
        apiFetchMock.mock.calls.filter(([path]) => path === "/analytics/advice"),
      ).toHaveLength(2);
    });
  });
});
