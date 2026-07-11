import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DistributionList } from "./distribution-list";

describe("DistributionList", () => {
  it("exposes labels and counts without relying on bar color", () => {
    render(
      <DistributionList
        title="掌握状态分布"
        data={[
          { label: "未掌握", count: 6 },
          { label: "已掌握", count: 4 },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "掌握状态分布" })).toBeVisible();
    expect(screen.getByRole("list", { name: "掌握状态分布明细" })).toHaveTextContent("未掌握6 题60%");
    expect(screen.getByRole("list", { name: "掌握状态分布明细" })).toHaveTextContent("已掌握4 题40%");
  });
});
