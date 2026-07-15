import { beforeEach, describe, expect, it, vi } from "vitest";

const { redirectMock } = vi.hoisted(() => ({ redirectMock: vi.fn() }));

vi.mock("next/navigation", () => ({ redirect: redirectMock }));

import Home from "./page";

describe("root page", () => {
  beforeEach(() => redirectMock.mockReset());

  it("enters the authenticated app and lets the session guard route guests", () => {
    Home();

    expect(redirectMock).toHaveBeenCalledWith("/dashboard");
  });
});
