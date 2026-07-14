import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImageOcrPanel } from "./image-ocr-panel";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

const status = {
  provider: "mock" as const,
  configured: true,
  api_name: "QuestionSplitOCR" as const,
  supports_multi_question: true as const,
  supports_pdf: true as const,
  supports_options: true as const,
  use_new_model: false as const,
};

const imageUpload = {
  id: "upload-1",
  original_name: "questions.png",
  storage_name: "questions.png",
  mime_type: "image/png",
  size_bytes: 128,
  created_at: "2026-07-10T00:00:00Z",
  file_kind: "image" as const,
  width: 1200,
  height: 1600,
  page_count: null,
  warnings: [],
};

const questions = [
  {
    temporary_id: "draft-1",
    index: 0,
    source_info_index: 0,
    question_number: "1",
    question_type: "multiple_choice_unknown" as const,
    question_text: "第一道题题干",
    full_text: "1. 第一道题题干\nA. 甲",
    question_elements: [],
    options: [{ label: "A", text: "甲", raw_text: "A. 甲", coord: null, asset_id: null, image_url: null }],
    figures: [],
    tables: [],
    recognized_answer: "A",
    recognized_parse: "第一题图片原解析",
    coord: [],
    raw_group_type: "multiple-choice",
    warnings: [],
    crop_asset_id: null,
    crop_image_url: null,
  },
  {
    temporary_id: "draft-2",
    index: 1,
    source_info_index: 0,
    question_number: "2",
    question_type: "unknown" as const,
    question_text: "第二道题题干",
    full_text: "2. 第二道题题干",
    question_elements: [],
    options: [],
    figures: [],
    tables: [],
    recognized_answer: null,
    recognized_parse: null,
    coord: [],
    raw_group_type: null,
    warnings: [],
    crop_asset_id: null,
    crop_image_url: null,
  },
];

const result = {
  provider: "mock",
  api_name: "QuestionSplitOCR" as const,
  request_id: "request-1",
  page_number: 1,
  question_count: 2,
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
  questions,
  is_demo: true,
};

function installUrlStub() {
  const NativeURL = URL;
  vi.stubGlobal("URL", class TestURL extends NativeURL {
    static createObjectURL = vi.fn(() => "blob:question-preview");
    static revokeObjectURL = vi.fn();
  });
}

function installHappyApi() {
  apiFetchMock.mockImplementation(async (path) => {
    if (path === "/ocr/status") return status;
    if (path === "/uploads/questions") return imageUpload;
    if (path === "/ocr") return result;
    throw new Error(`unexpected path: ${path}`);
  });
}

async function uploadAndRecognize(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("演示 OCR（不会调用腾讯云）");
  await user.upload(
    screen.getByLabelText("从相册或文件选择错题"),
    new File(["png-content"], "questions.png", { type: "image/png" }),
  );
  await user.click(screen.getByRole("button", { name: "上传文件" }));
  await user.click(await screen.findByRole("button", { name: "开始识别" }));
}

describe("ImageOcrPanel", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    installUrlStub();
  });

  it("accepts supported image files, exposes camera capture, and rejects unsupported formats", async () => {
    const user = userEvent.setup({ applyAccept: false });
    installHappyApi();
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    expect(await screen.findByText("演示 OCR（不会调用腾讯云）")).toBeVisible();
    expect(screen.getByLabelText("拍摄错题")).toHaveAttribute("capture", "environment");
    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["text"], "question.txt", { type: "text/plain" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("仅支持 JPEG、PNG、BMP 图片或 PDF 文件");

    await user.upload(
      screen.getByLabelText("拍摄错题"),
      new File(["jpeg"], "camera.jpg", { type: "image/jpeg" }),
    );
    expect(screen.getByAltText("待识别错题预览")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/uploads/questions",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
  });

  it("identifies a configured Tencent provider as real cloud OCR", async () => {
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/ocr/status") return { ...status, provider: "tencent_question_split" as const };
      throw new Error(`unexpected path: ${path}`);
    });
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    expect(await screen.findByText("腾讯云真实 OCR")).toBeVisible();
  });

  it("rejects a raw file within 10 MiB when its Base64 payload exceeds 10 MiB", async () => {
    const user = userEvent.setup();
    const maxBase64Bytes = 10 * 1024 * 1024;
    const rawBytes = (maxBase64Bytes / 4) * 3 + 1;
    installHappyApi();
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    expect(rawBytes).toBeLessThanOrEqual(10 * 1024 * 1024);
    expect(4 * Math.ceil(rawBytes / 3)).toBeGreaterThan(maxBase64Bytes);
    await screen.findByText("演示 OCR（不会调用腾讯云）");
    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File([new Uint8Array(rawBytes)], "oversized-base64.png", { type: "image/png" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("文件经 Base64 编码后不能超过 10 MiB（原文件最大 7.5 MiB）");
    expect(screen.queryByAltText("待识别错题预览")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传文件" })).toBeDisabled();
  });

  it("sends the selected PDF page and keeps the original PDF preview visible", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/ocr/status") return status;
      if (path === "/uploads/questions") {
        return { ...imageUpload, original_name: "paper.pdf", mime_type: "application/pdf", file_kind: "pdf", page_count: 5, width: null, height: null, warnings: ["PDF 页面将逐页识别"] };
      }
      if (path === "/ocr") return { ...result, page_number: 3, warnings: ["请核对本页旋转方向"] };
      throw new Error(`unexpected path: ${path}`);
    });
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    await screen.findByText("演示 OCR（不会调用腾讯云）");
    await user.upload(
      screen.getByLabelText("从相册或文件选择错题"),
      new File(["pdf"], "paper.pdf", { type: "application/pdf" }),
    );
    expect(screen.getByLabelText("待识别 PDF 预览")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(await screen.findByText("PDF 页面将逐页识别")).toBeVisible();
    await user.clear(await screen.findByLabelText("PDF 页码"));
    await user.type(screen.getByLabelText("PDF 页码"), "6");
    expect(screen.getByRole("button", { name: "开始识别" })).toBeDisabled();
    await user.clear(screen.getByLabelText("PDF 页码"));
    await user.type(screen.getByLabelText("PDF 页码"), "0");
    expect(screen.getByRole("button", { name: "开始识别" })).toBeDisabled();
    await user.clear(await screen.findByLabelText("PDF 页码"));
    await user.type(screen.getByLabelText("PDF 页码"), "3");
    await user.click(screen.getByRole("button", { name: "开始识别" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        "/ocr",
        expect.objectContaining({ body: JSON.stringify({ upload_id: "upload-1", pdf_page_number: 3 }) }),
      );
    });
    expect(await screen.findByText("识别到 2 道题")).toBeVisible();
    expect(screen.getByText("请核对本页旋转方向")).toBeVisible();
  });

  it("renders multiple editable drafts, supports deletion, and never auto-loads one", async () => {
    const user = userEvent.setup();
    const onLoadQuestion = vi.fn();
    installHappyApi();
    render(<ImageOcrPanel onLoadQuestion={onLoadQuestion} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    await uploadAndRecognize(user);
    expect(await screen.findByText("识别到 2 道题")).toBeVisible();
    expect(screen.getByLabelText("第 1 题题干")).toHaveValue("第一道题题干");
    expect(screen.getByLabelText("第 2 题题干")).toHaveValue("第二道题题干");
    expect(screen.getByText("演示模式识别结果")).toBeVisible();
    expect(onLoadQuestion).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("第 1 题题干"));
    await user.type(screen.getByLabelText("第 1 题题干"), "人工修订题干");
    await user.click(screen.getByRole("button", { name: "删除第 2 题" }));
    expect(screen.getByText("识别到 1 道题")).toBeVisible();
    expect(screen.queryByLabelText("第 2 题题干")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "载入第 1 题到表单" }));
    expect(onLoadQuestion).toHaveBeenCalledWith(
      expect.objectContaining({ question_text: "人工修订题干" }),
      expect.objectContaining({ source: expect.objectContaining({ file_id: "upload-1" }) }),
      "edit",
      expect.any(Function),
    );

    const removeSavedDraft = onLoadQuestion.mock.calls[0]?.[3];
    act(() => removeSavedDraft?.());
    expect(screen.getByText("识别到 0 道题")).toBeVisible();
  });

  it("shows recognizing state, disables duplicate submission, and confirms before replacing edited drafts", async () => {
    const user = userEvent.setup();
    let resolveOcr: ((value: typeof result) => void) | undefined;
    const ocrPromise = new Promise<typeof result>((resolve) => { resolveOcr = resolve; });
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/ocr/status") return status;
      if (path === "/uploads/questions") return imageUpload;
      if (path === "/ocr") return ocrPromise;
      throw new Error(`unexpected path: ${path}`);
    });
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    await screen.findByText("演示 OCR（不会调用腾讯云）");
    await user.upload(screen.getByLabelText("从相册或文件选择错题"), new File(["png"], "q.png", { type: "image/png" }));
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.click(await screen.findByRole("button", { name: "开始识别" }));
    expect(screen.getByRole("button", { name: "正在识别…" })).toBeDisabled();
    expect(screen.getByLabelText("从相册或文件选择错题")).toBeDisabled();
    expect(screen.getByLabelText("拍摄错题")).toBeDisabled();
    resolveOcr?.(result);
    expect(await screen.findByText("识别到 2 道题")).toBeVisible();

    await user.type(screen.getByLabelText("第 1 题题干"), " 已修改");
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    await user.click(screen.getByRole("button", { name: "重新识别" }));
    expect(confirm).toHaveBeenCalledWith("重新识别会覆盖当前已编辑的识别草稿，确定继续吗？");
    expect(apiFetchMock.mock.calls.filter(([path]) => path === "/ocr")).toHaveLength(1);
    expect(screen.getByLabelText("第 1 题题干")).toHaveValue("第一道题题干 已修改");
  });

  it("surfaces OCR failures without discarding the uploaded preview", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/ocr/status") return status;
      if (path === "/uploads/questions") return imageUpload;
      if (path === "/ocr") throw new ApiError(429, { code: "OCR_RATE_LIMITED", message: "识别请求过于频繁，请稍后重试" });
      throw new Error(`unexpected path: ${path}`);
    });
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    await uploadAndRecognize(user);
    expect(await screen.findByText("识别请求过于频繁，请稍后重试")).toBeVisible();
    expect(screen.getByAltText("待识别错题预览")).toBeVisible();
    expect(screen.getByRole("button", { name: "开始识别" })).toBeEnabled();
  });

  it("disables recognition and explains when Tencent OCR is not configured", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/ocr/status") return { ...status, provider: "tencent_question_split", configured: false };
      if (path === "/uploads/questions") return imageUpload;
      throw new Error(`unexpected path: ${path}`);
    });
    render(<ImageOcrPanel onLoadQuestion={vi.fn()} onAdoptAnswer={vi.fn()} onAdoptParse={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("OCR 服务尚未配置");
    await user.upload(screen.getByLabelText("从相册或文件选择错题"), new File(["png"], "q.png", { type: "image/png" }));
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(await screen.findByRole("button", { name: "开始识别" })).toBeDisabled();
    expect(apiFetchMock).not.toHaveBeenCalledWith("/ocr", expect.anything());
  });
});
