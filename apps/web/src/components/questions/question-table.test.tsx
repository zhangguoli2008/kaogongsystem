import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionTable } from "./question-table";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";
import type { Question } from "@/types/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

const twoQuestions = [
  {
    id: "q1",
    user_id: "u1",
    stem: "资料分析题一",
    exam_type: "国考",
    module: "资料分析",
    options: [],
    user_answer: "A",
    correct_answer: "B",
    original_explanation: null,
    source: null,
    notes: null,
    image_path: null,
    ocr_raw_text: null,
    knowledge_points: ["增长率"],
    error_reason: "粗心",
    mastery_status: "复习中",
    analysis_status: "已完成",
    tags: [],
    current_analysis_id: null,
    current_analysis: null,
    analysis_error_code: null,
    created_at: "2026-07-10T08:00:00Z",
    updated_at: "2026-07-10T08:00:00Z",
  },
  {
    id: "q2",
    user_id: "u1",
    stem: "判断推理题二",
    exam_type: "省考",
    module: "判断推理",
    options: [],
    user_answer: "C",
    correct_answer: "D",
    original_explanation: null,
    source: null,
    notes: null,
    image_path: null,
    ocr_raw_text: null,
    knowledge_points: ["图形推理"],
    error_reason: "不会",
    mastery_status: "未掌握",
    analysis_status: "未分析",
    tags: [],
    current_analysis_id: null,
    current_analysis: null,
    analysis_error_code: null,
    created_at: "2026-07-09T08:00:00Z",
    updated_at: "2026-07-09T08:00:00Z",
  },
] satisfies Question[];

describe("QuestionTable", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({ deleted: 2, not_found: [] });
  });

  it("requires confirmation before bulk deletion", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionTable items={twoQuestions} />);

    await user.click(screen.getByRole("checkbox", { name: "选择全部错题" }));
    await user.click(screen.getByRole("button", { name: "批量删除" }));

    expect(screen.getByRole("dialog", { name: "确认删除错题" })).toBeVisible();
  });

  it("does not call the delete endpoint until confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionTable items={twoQuestions} />);

    await user.click(screen.getByRole("checkbox", { name: "选择全部错题" }));
    await user.click(screen.getByRole("button", { name: "批量删除" }));

    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("deletes only the selected ids after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionTable items={twoQuestions} />);

    await user.click(screen.getByRole("checkbox", { name: "选择错题 资料分析题一" }));
    await user.click(screen.getByRole("button", { name: "批量删除" }));
    await user.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/questions/bulk-delete", {
        method: "POST",
        body: JSON.stringify({ ids: ["q1"] }),
      });
    });
  });

  it("closes the confirmation dialog with Escape", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionTable items={twoQuestions} />);

    await user.click(screen.getByRole("checkbox", { name: "选择全部错题" }));
    const trigger = screen.getByRole("button", { name: "批量删除" });
    await user.click(trigger);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "确认删除错题" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps keyboard focus inside the confirmation dialog", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionTable items={twoQuestions} />);

    await user.click(screen.getByRole("checkbox", { name: "选择全部错题" }));
    await user.click(screen.getByRole("button", { name: "批量删除" }));
    const cancel = screen.getByRole("button", { name: "取消" });
    const confirm = screen.getByRole("button", { name: "确认删除" });
    expect(cancel).toHaveFocus();

    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
  });
});
