import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionForm } from "./question-form";
import { ApiError, apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";
import type { Question } from "@/types/api";

const push = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

const existingQuestion = {
  id: "question-1",
  user_id: "user-1",
  exam_type: "国考",
  module: "资料分析",
  stem: "原题干",
  options: [{ label: "A", content: "原选项" }],
  user_answer: "A",
  correct_answer: "B",
  original_explanation: null,
  source: null,
  notes: null,
  image_path: null,
  ocr_raw_text: null,
  knowledge_points: [],
  error_reason: null,
  mastery_status: "未掌握",
  analysis_status: "未分析",
  tags: [],
  current_analysis_id: null,
  current_analysis: null,
  analysis_error_code: null,
  created_at: "2026-07-10T00:00:00Z",
  updated_at: "2026-07-10T00:00:00Z",
} satisfies Question;

describe("QuestionForm", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    push.mockReset();
    const NativeURL = URL;
    vi.stubGlobal("URL", class TestURL extends NativeURL {
      static createObjectURL = vi.fn(() => "blob:question-preview");
      static revokeObjectURL = vi.fn();
    });
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/uploads/questions") {
        return {
          id: "upload-1",
          original_name: "question.png",
          storage_name: "question.png",
          mime_type: "image/png",
          size_bytes: 128,
          created_at: "2026-07-10T00:00:00Z",
        };
      }

      if (path === "/ocr") {
        return {
          stem: "根据材料，下列说法正确的是？",
          options: [
            { label: "A", content: "选项 A" },
            { label: "B", content: "选项 B" },
          ],
          user_answer: "A",
          correct_answer: "B",
          original_explanation: "材料说明正确答案为 B。",
          raw_text: "OCR 原始文本",
          is_demo: true,
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });
  });

  it("fills OCR fields without saving automatically", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionForm mode="image" />);

    await user.upload(
      screen.getByLabelText("上传错题图片"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传图片" }));
    await user.click(await screen.findByRole("button", { name: "开始识别" }));

    await waitFor(() => {
      expect(screen.getByLabelText("题干")).toHaveValue("根据材料，下列说法正确的是？");
    });
    expect(screen.getByLabelText("我的答案")).toHaveValue("A");
    expect(apiFetchMock).not.toHaveBeenCalledWith("/questions", expect.anything());
  });

  it("keeps the image preview and allows an explicit upload retry", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockRejectedValueOnce(new ApiError(413, {
      code: "upload_too_large",
      message: "图片大小超过限制",
    }));
    renderWithProviders(<QuestionForm mode="image" />);

    await user.upload(
      screen.getByLabelText("上传错题图片"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传图片" }));

    expect(await screen.findByText("图片大小超过限制")).toBeVisible();
    expect(screen.getByAltText("待识别错题预览")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "上传图片" }));
    expect(await screen.findByRole("button", { name: "开始识别" })).toBeEnabled();
  });

  it("creates a question and navigates to its API id", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({
      id: "question-1",
      user_id: "user-1",
      exam_type: "国考",
      module: "言语理解",
      stem: "题干内容",
      options: [],
      user_answer: "A",
      correct_answer: "B",
      original_explanation: null,
      source: null,
      notes: null,
      image_path: null,
      ocr_raw_text: null,
      knowledge_points: [],
      error_reason: null,
      mastery_status: "未掌握",
      analysis_status: "未分析",
      tags: [],
      current_analysis_id: null,
      current_analysis: null,
      analysis_error_code: null,
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
    });
    renderWithProviders(<QuestionForm mode="manual" />);

    await user.type(screen.getByLabelText("题干"), "题干内容");
    await user.type(screen.getByLabelText("我的答案"), "A");
    await user.type(screen.getByLabelText("正确答案"), "B");
    await user.click(screen.getByRole("button", { name: "保存错题" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/questions", expect.objectContaining({ method: "POST" }));
      expect(push).toHaveBeenCalledWith("/questions/question-1");
    });
  });

  it("maps API field errors without clearing entered content", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockRejectedValue(new ApiError(422, {
      code: "validation_error",
      message: "请求参数校验失败",
      field_errors: { stem: ["题干内容无效"] },
    }));
    renderWithProviders(<QuestionForm mode="manual" />);

    await user.type(screen.getByLabelText("题干"), "保留这段题干");
    await user.type(screen.getByLabelText("我的答案"), "A");
    await user.type(screen.getByLabelText("正确答案"), "B");
    await user.click(screen.getByRole("button", { name: "保存错题" }));

    expect(await screen.findByText("题干内容无效")).toBeVisible();
    expect(screen.getByLabelText("题干")).toHaveValue("保留这段题干");
  });

  it("updates saved content without triggering AI analysis", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    apiFetchMock.mockResolvedValue({ ...existingQuestion, stem: "修改后的题干" });
    renderWithProviders(<QuestionForm mode="manual" question={existingQuestion} onSaved={onSaved} />);

    await user.clear(screen.getByLabelText("题干"));
    await user.type(screen.getByLabelText("题干"), "修改后的题干");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/questions/question-1", expect.objectContaining({ method: "PATCH" }));
      expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ stem: "修改后的题干" }));
    });
    expect(apiFetchMock).not.toHaveBeenCalledWith("/questions/question-1/analyze", expect.anything());
  });
});
