import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AiAdvice } from "./ai-advice";

describe("AiAdvice", () => {
  it("labels demo advice and refreshes only after an explicit click", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      <AiAdvice
        advice="优先复习资料分析中的增长率。"
        providerMode="demo"
        onRefresh={onRefresh}
      />,
    );

    expect(screen.getByText("演示模式")).toBeVisible();
    expect(onRefresh).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "刷新学习建议" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});
