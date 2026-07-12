import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppHeader } from "./app-header";

describe("AppHeader", () => {
  it("keeps the date and account metadata in a spaced header group", () => {
    render(
      <AppHeader
        user={{ id: "user-1", email: "demo@example.com" }}
        onOpenNavigation={vi.fn()}
        onLogout={vi.fn()}
        logoutPending={false}
      />,
    );

    const accountGroup = screen.getByLabelText("学习日期与当前用户");

    expect(accountGroup).toHaveClass("gap-6");
    expect(accountGroup).toContainElement(screen.getByText("demo@example.com"));
  });

  it("exposes one logout action and disables it while the request is pending", async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();
    const { rerender } = render(
      <AppHeader
        user={{ id: "user-1", email: "demo@example.com" }}
        onOpenNavigation={vi.fn()}
        onLogout={onLogout}
        logoutPending={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: "退出登录" }));
    expect(onLogout).toHaveBeenCalledTimes(1);

    rerender(
      <AppHeader
        user={{ id: "user-1", email: "demo@example.com" }}
        onOpenNavigation={vi.fn()}
        onLogout={onLogout}
        logoutPending
      />,
    );
    expect(screen.getByRole("button", { name: "正在退出…" })).toBeDisabled();
  });
});
