import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppLayout from "./layout";
import { ApiError } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

const { sessionState } = vi.hoisted(() => ({
  sessionState: {
    current: {
      data: { id: "u1", email: "learner@example.com" },
      error: null,
      isError: false,
      isPending: false,
    },
  },
}));

vi.mock("@/hooks/use-session", () => ({
  useSession: () => sessionState.current,
}));

describe("AppLayout", () => {
  beforeEach(() => {
    sessionState.current = {
      data: { id: "u1", email: "learner@example.com" },
      error: null,
      isError: false,
      isPending: false,
    };
  });

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

  it("does not render protected navigation while a 401 redirects to login", () => {
    sessionState.current = {
      data: undefined,
      error: new ApiError(401, { code: "unauthorized", message: "未登录" }),
      isError: true,
      isPending: false,
    };

    renderWithProviders(
      <AppLayout>
        <p>受保护内容</p>
      </AppLayout>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("正在返回登录页…");
    expect(screen.queryByRole("navigation", { name: "主导航" })).not.toBeInTheDocument();
    expect(screen.queryByText("受保护内容")).not.toBeInTheDocument();
  });
});
