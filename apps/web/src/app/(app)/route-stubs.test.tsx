import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AnalyticsPage from "./analytics/page";
import DashboardPage from "./dashboard/page";
import ReviewPage from "./review/page";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(() => new Promise(() => undefined)),
}));

const routes = [
  { Page: DashboardPage, heading: "今日学习概览", action: "录入错题" },
  { Page: ReviewPage, heading: "今日复习", action: "查看错题库" },
  { Page: AnalyticsPage, heading: "数据统计", action: "查看错题库" },
];

describe("authenticated route entry points", () => {
  it.each(routes)("renders an accessible $heading while data loads", ({ Page, heading, action }) => {
    const { unmount } = renderWithProviders(<Page />);

    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: action })).toBeInTheDocument();
    unmount();
  });
});
