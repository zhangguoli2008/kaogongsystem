import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModuleChart } from "./module-chart";

describe("ModuleChart", () => {
  it("provides a titled numeric list as a non-color chart alternative", () => {
    render(
      <ModuleChart
        data={[
          { label: "资料分析", count: 8 },
          { label: "判断推理", count: 4 },
        ]}
        total={12}
      />,
    );

    expect(screen.getByRole("heading", { name: "五大模块错题占比" })).toBeVisible();
    expect(screen.getByText("共 12 题")).toBeVisible();
    expect(screen.getByRole("list", { name: "模块错题明细" })).toHaveTextContent(
      "资料分析8 题66.7%",
    );
    expect(screen.getByRole("list", { name: "模块错题明细" })).toHaveTextContent(
      "判断推理4 题33.3%",
    );
  });
});
