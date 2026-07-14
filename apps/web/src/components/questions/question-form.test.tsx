import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionForm } from "./question-form";
import { ApiError, apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";
import type { OcrResult, Question } from "@/types/api";

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
  ocr_metadata: null,
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
      if (path === "/ocr/status") {
        return {
          provider: "mock",
          configured: true,
          api_name: "QuestionSplitOCR",
          supports_multi_question: true,
          supports_pdf: true,
          supports_options: true,
          use_new_model: false,
        };
      }

      if (path === "/uploads/questions") {
        return {
          id: "upload-1",
          original_name: "question.png",
          storage_name: "question.png",
          mime_type: "image/png",
          size_bytes: 128,
          created_at: "2026-07-10T00:00:00Z",
          file_kind: "image",
          width: 1200,
          height: 1600,
          page_count: null,
          warnings: [],
        };
      }

      if (path === "/ocr") {
        return {
          provider: "mock",
          api_name: "QuestionSplitOCR",
          request_id: "ocr-request-1",
          page_number: 1,
          question_count: 1,
          source: {
            file_id: "upload-1",
            image_url: "/uploads/upload-1",
            original_width: 1200,
            original_height: 1600,
            processed_width: 1200,
            processed_height: 1600,
            angle: 0,
          },
          warnings: [],
          questions: [{
            temporary_id: "draft-1",
            index: 0,
            source_info_index: 0,
            question_number: "8",
            question_type: "multiple_choice_unknown",
            question_text: "根据材料，下列说法正确的是？",
            full_text: "8. 根据材料，下列说法正确的是？\nA. 选项 A\nB. 选项 B",
            question_elements: [],
            options: [
              { label: "A", text: "选项 A", raw_text: "A. 选项 A", coord: null, asset_id: "option-1", image_url: "/uploads/option-1" },
              { label: "B", text: "选项 B", raw_text: "B. 选项 B", coord: null, asset_id: null, image_url: null },
            ],
            figures: [{ index: 0, text: "题内图形", coord: null, asset_id: "figure-1", image_url: "/uploads/figure-1" }],
            tables: [{ index: 0, text: "题内表格", coord: null, asset_id: "table-1", image_url: "/uploads/table-1" }],
            recognized_answer: "B",
            recognized_parse: "材料说明正确答案为 B。",
            coord: [],
            raw_group_type: "multiple-choice",
            warnings: [],
            crop_asset_id: "crop-1",
            crop_image_url: "/uploads/crop-1",
          }],
          is_demo: true,
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });
  });

  it("loads one chosen draft without silently adopting recognized answer or saving", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QuestionForm mode="image" />);

    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.click(await screen.findByRole("button", { name: "开始识别" }));
    await user.click(await screen.findByRole("button", { name: "载入第 8 题到表单" }));

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /^题干$/ })).toHaveValue("根据材料，下列说法正确的是？");
    });
    expect(screen.getByLabelText("我的答案")).toHaveValue("");
    expect(screen.getByLabelText("正确答案")).toHaveValue("");
    expect(screen.getByLabelText("原解析")).toHaveValue("");
    expect(apiFetchMock).not.toHaveBeenCalledWith("/questions", expect.anything());

    await user.click(screen.getByRole("button", { name: "采用识别答案 B" }));
    await user.click(screen.getByRole("button", { name: "采用第 8 题识别解析" }));
    expect(screen.getByLabelText("正确答案")).toHaveValue("B");
    expect(screen.getByLabelText("原解析")).toHaveValue("材料说明正确答案为 B。");
  });

  it("protects unsaved form content before loading a different OCR draft", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    renderWithProviders(<QuestionForm mode="image" />);

    await user.type(screen.getByRole("textbox", { name: /^题干$/ }), "尚未保存的手工题干");
    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.click(await screen.findByRole("button", { name: "开始识别" }));
    await user.click(await screen.findByRole("button", { name: "载入第 8 题到表单" }));

    expect(confirm).toHaveBeenCalledWith("当前表单有未保存内容，载入识别题目会覆盖题干和选项，确定继续吗？");
    expect(screen.getByRole("textbox", { name: /^题干$/ })).toHaveValue("尚未保存的手工题干");

    await user.click(screen.getByRole("button", { name: "采用识别答案 B" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("正确答案")).toHaveValue("");
    expect(screen.getByRole("textbox", { name: /^题干$/ })).toHaveValue("尚未保存的手工题干");
  });

  it("saves strict OCR provenance and only prepares the existing AI flow explicitly", async () => {
    const user = userEvent.setup();
    const defaultImplementation = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation(async (...args) => {
      if (args[0] === "/questions") {
        const payload = JSON.parse(String(args[1]?.body));
        return {
          ...existingQuestion,
          ...payload,
          id: "question-from-ocr",
          user_id: "user-1",
          analysis_status: "未分析",
          current_analysis_id: null,
          current_analysis: null,
          analysis_error_code: null,
        };
      }
      if (!defaultImplementation) throw new Error("missing default API implementation");
      return defaultImplementation(...args);
    });
    renderWithProviders(<QuestionForm mode="image" />);

    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.click(await screen.findByRole("button", { name: "开始识别" }));
    await user.click(await screen.findByRole("button", { name: "载入第 8 题并准备 AI 分析" }));
    expect(screen.getByText(/已准备 AI 分析/)).toBeVisible();
    expect(apiFetchMock).not.toHaveBeenCalledWith("/questions", expect.anything());

    await user.click(screen.getByRole("button", { name: "采用识别答案 B" }));
    await user.click(screen.getByRole("button", { name: "采用第 8 题识别解析" }));
    await user.type(screen.getByLabelText("我的答案"), "A");
    await user.click(screen.getByRole("button", { name: "保存错题" }));

    expect(await screen.findByRole("link", { name: "查看已保存错题" })).toHaveAttribute(
      "href",
      "/questions/question-from-ocr",
    );
    expect(push).not.toHaveBeenCalled();
    const createCall = apiFetchMock.mock.calls.find(([path]) => path === "/questions");
    expect(createCall).toBeDefined();
    const payload = JSON.parse(String(createCall?.[1]?.body));
    expect(payload.ocr_metadata).toMatchObject({
      source: { asset_id: "upload-1" },
      crop: { asset_id: "crop-1" },
      figures: [{ asset: { asset_id: "figure-1" } }],
      tables: [{ asset: { asset_id: "table-1" } }],
      options: [{ label: "A", asset: { asset_id: "option-1" } }, { label: "B", asset: null }],
      recognized_answer: "B",
      recognized_parse: "材料说明正确答案为 B。",
    });
    const serialized = JSON.stringify(payload.ocr_metadata);
    expect(serialized).not.toContain("image_url");
    expect(serialized).not.toContain("storage_name");
    expect(serialized).not.toContain("base64");
    expect(apiFetchMock.mock.calls.some(([path]) => String(path).includes("/analyze"))).toBe(false);
  });

  it("keeps remaining OCR drafts available while saving multiple questions in sequence", async () => {
    const user = userEvent.setup();
    const defaultImplementation = apiFetchMock.getMockImplementation();
    let savedCount = 0;
    let releaseFirstSave = () => {};
    const firstSaveGate = new Promise<void>((resolve) => {
      releaseFirstSave = resolve;
    });
    apiFetchMock.mockImplementation(async (...args) => {
      if (!defaultImplementation) throw new Error("missing default API implementation");
      if (args[0] === "/ocr") {
        const result = await defaultImplementation(...args) as OcrResult;
        const first = result.questions[0];
        return {
          ...result,
          question_count: 2,
          questions: [
            first,
            {
              ...first,
              temporary_id: "draft-2",
              index: 1,
              question_number: "9",
              question_text: "第二道识别题干",
              full_text: "9. 第二道识别题干\nA. 第二题选项 A\nB. 第二题选项 B",
              options: [
                { ...first.options[0], text: "第二题选项 A" },
                { ...first.options[1], text: "第二题选项 B" },
              ],
              crop_asset_id: "crop-2",
              crop_image_url: "/uploads/crop-2",
            },
          ],
        };
      }
      if (args[0] === "/questions") {
        savedCount += 1;
        const payload = JSON.parse(String(args[1]?.body));
        if (savedCount === 1) await firstSaveGate;
        return {
          ...existingQuestion,
          ...payload,
          id: `saved-question-${savedCount}`,
          user_id: "user-1",
        };
      }
      return defaultImplementation(...args);
    });
    renderWithProviders(<QuestionForm mode="image" />);

    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.click(await screen.findByRole("button", { name: "开始识别" }));
    expect(await screen.findByRole("button", { name: "载入第 9 题到表单" })).toBeVisible();

    const firstCard = screen.getByRole("heading", { name: "第 8 题" }).closest("article");
    if (!firstCard) throw new Error("missing first OCR card");
    await user.click(within(firstCard).getByRole("button", { name: "载入第 8 题到表单" }));
    await user.click(within(firstCard).getByRole("button", { name: "采用识别答案 B" }));
    await user.type(screen.getByLabelText("我的答案"), "A");
    await user.click(screen.getByRole("button", { name: "保存错题" }));

    const secondLoadWhileSaving = screen.getByRole("button", { name: "载入第 9 题到表单" });
    expect(secondLoadWhileSaving).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "题干" })).toBeDisabled();
    expect(screen.getByLabelText("第 8 题题干")).toBeDisabled();
    expect(screen.getByLabelText("从相册或文件选择错题")).toBeDisabled();
    await user.click(secondLoadWhileSaving);
    expect(screen.getByRole("textbox", { name: "题干" })).toHaveValue("根据材料，下列说法正确的是？");
    act(() => releaseFirstSave());

    expect(await screen.findByRole("link", { name: "查看已保存错题" })).toHaveAttribute(
      "href",
      "/questions/saved-question-1",
    );
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "载入第 8 题到表单" })).not.toBeInTheDocument();

    const secondCard = screen.getByRole("heading", { name: "第 9 题" }).closest("article");
    if (!secondCard) throw new Error("missing second OCR card");
    await user.click(within(secondCard).getByRole("button", { name: "载入第 9 题到表单" }));
    await user.click(within(secondCard).getByRole("button", { name: "采用识别答案 B" }));
    await user.type(screen.getByLabelText("我的答案"), "A");
    await user.click(screen.getByRole("button", { name: "保存错题" }));

    await waitFor(() => {
      expect(apiFetchMock.mock.calls.filter(([path]) => path === "/questions")).toHaveLength(2);
    });
    const createCalls = apiFetchMock.mock.calls.filter(([path]) => path === "/questions");
    expect(createCalls.map(([, request]) => JSON.parse(String(request?.body)).stem)).toEqual([
      "根据材料，下列说法正确的是？",
      "第二道识别题干",
    ]);
    expect(screen.getByRole("link", { name: "查看已保存错题" })).toHaveAttribute(
      "href",
      "/questions/saved-question-2",
    );
    expect(screen.queryByRole("button", { name: "载入第 9 题到表单" })).not.toBeInTheDocument();
    expect(apiFetchMock.mock.calls.filter(([path]) => path === "/uploads/questions")).toHaveLength(1);
    expect(apiFetchMock.mock.calls.filter(([path]) => path === "/ocr")).toHaveLength(1);
    expect(push).not.toHaveBeenCalled();
  });

  it("keeps the image preview and allows an explicit upload retry", async () => {
    const user = userEvent.setup();
    const defaultImplementation = apiFetchMock.getMockImplementation();
    let uploadAttempts = 0;
    apiFetchMock.mockImplementation(async (...args) => {
      if (args[0] === "/uploads/questions" && uploadAttempts++ === 0) {
        throw new ApiError(413, {
          code: "upload_too_large",
          message: "图片大小超过限制",
        });
      }
      if (!defaultImplementation) throw new Error("missing default API implementation");
      return defaultImplementation(...args);
    });
    renderWithProviders(<QuestionForm mode="image" />);

    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["png-content"], "question.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));

    expect(await screen.findByText("图片大小超过限制")).toBeVisible();
    expect(screen.getByAltText("待识别错题预览")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "上传文件" }));
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
      ocr_metadata: null,
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

  it("preserves unsaved edits when analysis updates the same question cache", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<QuestionForm mode="manual" question={existingQuestion} />);
    await user.clear(screen.getByLabelText("题干"));
    await user.type(screen.getByLabelText("题干"), "尚未保存的编辑");

    rerender(
      <QuestionForm
        mode="manual"
        question={{
          ...existingQuestion,
          analysis_status: "已完成",
          current_analysis_id: "analysis-1",
          updated_at: "2026-07-11T00:00:00Z",
        }}
      />,
    );

    expect(screen.getByLabelText("题干")).toHaveValue("尚未保存的编辑");
  });
});
