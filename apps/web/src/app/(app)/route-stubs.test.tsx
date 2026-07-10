import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AnalyticsPage from "./analytics/page";
import DashboardPage from "./dashboard/page";
import QuestionsPage from "./questions/page";
import NewQuestionPage from "./questions/new/page";
import ReviewPage from "./review/page";

const routes = [
  { Page: DashboardPage, heading: "今日学习概览", action: "录入错题" },
  { Page: QuestionsPage, heading: "错题库", action: "录入错题" },
  { Page: NewQuestionPage, heading: "录入错题", action: "返回错题库" },
  { Page: ReviewPage, heading: "今日复习", action: "查看错题库" },
  { Page: AnalyticsPage, heading: "数据统计", action: "查看错题库" },
];

describe("authenticated route stubs", () => {
  it.each(routes)("renders an accessible $heading placeholder", ({ Page, heading, action }) => {
    const { unmount } = render(<Page />);

    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: action })).toBeInTheDocument();
    unmount();
  });
});
