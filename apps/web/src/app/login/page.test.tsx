import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";
import { renderWithProviders } from "@/test/test-utils";

const mockReplace = vi.fn();
const fetchMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    mockReplace.mockReset();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) {
        return new Response(JSON.stringify({ code: "unauthorized", message: "未登录" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      return new Response(JSON.stringify({ id: "u1", email: "learner@example.com" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("submits credentials and redirects to dashboard", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />);

    await user.type(screen.getByLabelText("邮箱"), "learner@example.com");
    await user.type(screen.getByLabelText("密码"), "strong-pass-123");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/dashboard"));
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/login",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
  });

  it("keeps the entered email when client validation fails", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />);

    await user.type(screen.getByLabelText("邮箱"), "not-an-email");
    await user.type(screen.getByLabelText("密码"), "short");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("请输入有效的邮箱地址")).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toHaveValue("not-an-email");
  });
});
