import { screen } from "@testing-library/react";
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
});
