import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AnalyticsPage from "./analytics/page";
import DashboardPage from "./dashboard/page";
import ReviewPage from "./review/page";

const routes = [
  { Page: DashboardPage, heading: "今日学习概览", action: "录入错题" },
  { Page: ReviewPage, heading: "今日复习", action: "查看错题库" },
  { Page: AnalyticsPage, heading: "数据统计", action: "查看错题库" },
];

describe("remaining authenticated route placeholders", () => {
  it.each(routes)("renders an accessible $heading placeholder", ({ Page, heading, action }) => {
    const { unmount } = render(<Page />);

    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: action })).toBeInTheDocument();
    unmount();
  });
});
