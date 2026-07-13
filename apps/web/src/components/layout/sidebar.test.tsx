import { useRef, useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "./sidebar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

function SidebarHarness() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>
        打开导航
      </button>
      <Sidebar open={open} onClose={() => setOpen(false)} />
    </>
  );
}

describe("Sidebar mobile drawer", () => {
  it("traps focus and restores it after Escape closes the dialog", async () => {
    const user = userEvent.setup();
    render(<SidebarHarness />);
    const trigger = screen.getByRole("button", { name: "打开导航" });

    await user.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "主导航" });
    const closeButton = within(drawer).getByRole("button", { name: "关闭导航菜单" });

    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(closeButton).toHaveFocus();

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(within(drawer).getByRole("link", { name: "数据统计" })).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});
