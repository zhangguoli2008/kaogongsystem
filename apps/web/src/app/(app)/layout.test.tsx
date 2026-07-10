import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "./layout";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({
    data: { id: "u1", email: "learner@example.com" },
    isPending: false,
    isError: false,
  }),
}));

describe("AppLayout", () => {
  it("renders the approved navigation in its visual order", () => {
    renderWithProviders(
      <AppLayout>
        <p>业务页面内容</p>
      </AppLayout>,
    );

    expect(screen.getAllByRole("link").map((link) => link.textContent?.trim())).toEqual([
      "首页",
      "错题录入",
      "错题库",
      "今日复习",
      "数据统计",
    ]);
    expect(screen.getByText("业务页面内容")).toBeInTheDocument();
  });
});
