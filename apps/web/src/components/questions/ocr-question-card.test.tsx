import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OcrQuestionCard } from "./ocr-question-card";
import type { OcrQuestion } from "@/types/api";

const question = {
  temporary_id: "draft-1",
  index: 0,
  source_info_index: 0,
  question_number: "12",
  question_type: "multiple_choice_unknown",
  question_text: "根据图形规律选择答案。",
  full_text: "12. 根据图形规律选择答案。\nA. 甲",
  question_elements: [],
  options: [{
    label: "A",
    text: "甲",
    raw_text: "A. 甲",
    coord: null,
    asset_id: "option-asset",
    image_url: "/uploads/option-asset",
  }],
  figures: [{
    index: 0,
    text: "图形材料",
    coord: null,
    asset_id: "figure-asset",
    image_url: "/uploads/figure-asset",
  }],
  tables: [{
    index: 0,
    text: "统计表",
    coord: null,
    asset_id: "table-asset",
    image_url: "/uploads/table-asset",
  }],
  recognized_answer: "C",
  recognized_parse: "图片中原有解析",
  coord: [],
  raw_group_type: "multiple-choice",
  warnings: ["请人工核对图表数字"],
  crop_asset_id: "crop-asset",
  crop_image_url: "/uploads/crop-asset",
} satisfies OcrQuestion;

function StatefulCard({
  onChange = vi.fn(),
  onDelete = vi.fn(),
  onLoad = vi.fn(),
  onAdoptAnswer = vi.fn(),
  onAdoptParse = vi.fn(),
}: {
  onChange?: (question: OcrQuestion) => void;
  onDelete?: () => void;
  onLoad?: (intent: "edit" | "analyze") => void;
  onAdoptAnswer?: (answer: string) => void;
  onAdoptParse?: (parse: string) => void;
}) {
  const [draft, setDraft] = useState<OcrQuestion>(question);
  return (
    <OcrQuestionCard
      position={0}
      question={draft}
      sourceImageUrl="/uploads/source-asset"
      onChange={(nextQuestion) => {
        setDraft(nextQuestion);
        onChange(nextQuestion);
      }}
      onDelete={onDelete}
      onLoad={onLoad}
      onAdoptAnswer={onAdoptAnswer}
      onAdoptParse={onAdoptParse}
    />
  );
}

describe("OcrQuestionCard", () => {
  it("renders visual context and keeps stem and options editable", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<StatefulCard onChange={onChange} />);

    expect(screen.getByText("第 12 题")).toBeVisible();
    expect(screen.getByText("请人工核对图表数字")).toBeVisible();
    expect(screen.getByAltText("第 12 题裁剪图")).toHaveAttribute(
      "src",
      "http://localhost:8000/api/v1/uploads/crop-asset",
    );
    expect(screen.getByAltText("第 12 题图形 1")).toBeVisible();
    expect(screen.getByAltText("第 12 题表格 1")).toBeVisible();
    expect(screen.getByAltText("第 12 题选项 A 图形")).toBeVisible();

    await user.clear(screen.getByLabelText("第 12 题题干"));
    await user.type(screen.getByLabelText("第 12 题题干"), "用户修改后的题干");
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ question_text: "用户修改后的题干" }),
    );

    await user.clear(screen.getByLabelText("第 12 题选项 A"));
    await user.type(screen.getByLabelText("第 12 题选项 A"), "修改选项");
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        options: [expect.objectContaining({ text: "修改选项" })],
      }),
    );

    await user.clear(screen.getByLabelText("第 12 题图形 1 文字"));
    await user.type(screen.getByLabelText("第 12 题图形 1 文字"), "修订图形文字");
    await user.clear(screen.getByLabelText("第 12 题表格 1 文字"));
    await user.type(screen.getByLabelText("第 12 题表格 1 文字"), "修订表格文字");
    await user.clear(screen.getByLabelText("第 12 题识别答案"));
    await user.type(screen.getByLabelText("第 12 题识别答案"), "D");
    await user.clear(screen.getByLabelText("第 12 题识别解析"));
    await user.type(screen.getByLabelText("第 12 题识别解析"), "修订解析");
    await user.clear(screen.getByLabelText("第 12 题 OCR 完整原文"));
    await user.type(screen.getByLabelText("第 12 题 OCR 完整原文"), "修订完整原文");

    expect(screen.getByLabelText("第 12 题图形 1 文字")).toHaveValue("修订图形文字");
    expect(screen.getByLabelText("第 12 题表格 1 文字")).toHaveValue("修订表格文字");
    expect(screen.getByLabelText("第 12 题识别答案")).toHaveValue("D");
    expect(screen.getByLabelText("第 12 题识别解析")).toHaveValue("修订解析");
    expect(screen.getByLabelText("第 12 题 OCR 完整原文")).toHaveValue("修订完整原文");
  });

  it("requires explicit actions before adopting recognized answer or parse", async () => {
    const user = userEvent.setup();
    const onAdoptAnswer = vi.fn();
    const onAdoptParse = vi.fn();
    render(<StatefulCard onAdoptAnswer={onAdoptAnswer} onAdoptParse={onAdoptParse} />);

    expect(onAdoptAnswer).not.toHaveBeenCalled();
    expect(onAdoptParse).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "采用识别答案 C" }));
    await user.click(screen.getByRole("button", { name: "采用第 12 题识别解析" }));
    expect(onAdoptAnswer).toHaveBeenCalledWith("C");
    expect(onAdoptParse).toHaveBeenCalledWith("图片中原有解析");
  });

  it("supports delete, load, and the existing save-then-analyze flow", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    const onLoad = vi.fn();
    render(<StatefulCard onDelete={onDelete} onLoad={onLoad} />);

    await user.click(screen.getByRole("button", { name: "载入第 12 题到表单" }));
    expect(onLoad).toHaveBeenCalledWith("edit");
    await user.click(screen.getByRole("button", { name: "载入第 12 题并准备 AI 分析" }));
    expect(onLoad).toHaveBeenCalledWith("analyze");
    expect(screen.getByText("需先保存错题，再使用现有 AI 分析按钮")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "删除第 12 题" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
