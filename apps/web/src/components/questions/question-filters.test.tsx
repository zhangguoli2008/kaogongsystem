import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionFilters } from "./question-filters";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/questions",
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

describe("QuestionFilters", () => {
  beforeEach(() => {
    replace.mockReset();
    window.history.replaceState({}, "", "/questions?mastery_status=%E6%9C%AA%E6%8E%8C%E6%8F%A1");
  });

  it("writes changed filters to URL search params while preserving active filters", async () => {
    const user = userEvent.setup();
    render(<QuestionFilters />);

    await user.selectOptions(screen.getByLabelText("考试模块"), "资料分析");

    expect(replace).toHaveBeenCalledWith(
      "/questions?mastery_status=%E6%9C%AA%E6%8E%8C%E6%8F%A1&module=%E8%B5%84%E6%96%99%E5%88%86%E6%9E%90",
    );
  });
});
