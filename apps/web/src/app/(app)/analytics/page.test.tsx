import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AnalyticsPage from "./page";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

describe("AnalyticsPage", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("explains the empty state instead of rendering a wall of zero charts", async () => {
    apiFetchMock.mockResolvedValue({
      total_questions: 0,
      module_distribution: [],
      knowledge_point_ranking: [],
      error_reason_distribution: [],
      mastery_distribution: [],
      trend_7d: [],
      trend_30d: [],
      ai_summary: "先录入错题，系统会根据你的数据生成学习建议。",
      is_demo: true,
    });

    renderWithProviders(<AnalyticsPage />);

    expect(screen.getByRole("heading", { name: "数据统计" })).toBeVisible();
    expect(await screen.findByText("还没有可统计的错题数据")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "五大模块错题占比" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "录入错题" })).toHaveAttribute("href", "/questions/new");
  });

  it("updates the weak-point summary from one explicit advice POST", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path, init) => {
      if (path === "/analytics/summary") return populatedSummary;
      if (path === "/analytics/advice" && init?.method === "POST") {
        return { advice: "新的薄弱点建议", provider_name: "demo", model_name: null, is_demo: true };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    renderWithProviders(<AnalyticsPage />);
    expect(await screen.findByText("旧的薄弱点建议")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "刷新统计建议" }));

    expect(await screen.findByText("新的薄弱点建议")).toBeVisible();
    expect(apiFetchMock.mock.calls.filter(([path]) => path === "/analytics/advice")).toHaveLength(1);
    expect(apiFetchMock.mock.calls.filter(([path]) => path === "/analytics/summary")).toHaveLength(1);
  });

  it("keeps the previous advice and exposes a retryable in-card error", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/analytics/summary") return populatedSummary;
      if (path === "/analytics/advice") throw new Error("network down");
      throw new Error(`unexpected request: ${path}`);
    });

    renderWithProviders(<AnalyticsPage />);
    expect(await screen.findByText("旧的薄弱点建议")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "刷新统计建议" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("AI 建议刷新失败，请检查网络后重试。");
    expect(screen.getByText("旧的薄弱点建议")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重试刷新建议" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.filter(([path]) => path === "/analytics/advice")).toHaveLength(2));
  });
});

const populatedSummary = {
  total_questions: 1,
  module_distribution: [{ label: "资料分析", count: 1 }],
  knowledge_point_ranking: [{ label: "增长率", count: 1 }],
  error_reason_distribution: [{ label: "计算错", count: 1 }],
  mastery_distribution: [{ label: "未掌握", count: 1 }],
  trend_7d: [{ date: "2026-07-10", count: 1 }],
  trend_30d: [{ date: "2026-07-10", count: 1 }],
  ai_summary: "旧的薄弱点建议",
  is_demo: true,
};
