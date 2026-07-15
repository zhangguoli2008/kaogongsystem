import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RecentQuestions } from "./recent-questions";

describe("RecentQuestions", () => {
  it("explains the empty state and links to question capture", () => {
    render(<RecentQuestions questions={[]} />);

    expect(screen.getByText("还没有错题记录")).toBeVisible();
    expect(screen.getByRole("link", { name: "录入错题" })).toHaveAttribute(
      "href",
      "/questions/new",
    );
  });
});
