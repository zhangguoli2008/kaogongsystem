import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TrendChart } from "./trend-chart";
import { renderWithProviders } from "@/test/test-utils";

describe("TrendChart", () => {
  it("switches between labeled 7-day and 30-day numeric alternatives", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TrendChart
        trend7d={[{ date: "2026-07-10", count: 2 }]}
        trend30d={[{ date: "2026-06-11", count: 5 }]}
      />,
    );

    expect(screen.getByRole("button", { name: "最近 7 天" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("table", { name: "最近 7 天录入明细" })).toHaveTextContent("2026-07-102");

    await user.click(screen.getByRole("button", { name: "最近 30 天" }));
    expect(screen.getByRole("button", { name: "最近 30 天" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("table", { name: "最近 30 天录入明细" })).toHaveTextContent("2026-06-115");
  });
});
