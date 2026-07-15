import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import NewQuestionPage from "./page";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

describe("NewQuestionPage", () => {
  it("uses pressed buttons instead of incomplete tab semantics", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewQuestionPage />);

    const group = screen.getByRole("group", { name: "录入方式" });
    const image = within(group).getByRole("button", { name: "图片识别" });
    const manual = within(group).getByRole("button", { name: "手动录入" });
    expect(image).toHaveAttribute("aria-pressed", "true");
    expect(manual).toHaveAttribute("aria-pressed", "false");

    await user.click(manual);
    expect(image).toHaveAttribute("aria-pressed", "false");
    expect(manual).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
