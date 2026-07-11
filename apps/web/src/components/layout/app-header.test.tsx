import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppHeader } from "./app-header";

describe("AppHeader", () => {
  it("keeps the date and account metadata in a spaced header group", () => {
    render(
      <AppHeader
        user={{ id: "user-1", email: "demo@example.com" }}
        onOpenNavigation={vi.fn()}
      />,
    );

    const accountGroup = screen.getByLabelText("学习日期与当前用户");

    expect(accountGroup).toHaveClass("gap-6");
    expect(accountGroup).toContainElement(screen.getByText("demo@example.com"));
  });
});
