import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RegisterPage from "./page";
import { renderWithProviders } from "@/test/test-utils";

const mockReplace = vi.fn();
const fetchMock = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/register",
  useRouter: () => ({ replace: mockReplace }),
}));

describe("RegisterPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/register?returnTo=%2Fquestions");
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
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("registers a user and redirects to the validated returnTo", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);

    await user.type(screen.getByLabelText("邮箱"), "learner@example.com");
    await user.type(screen.getByLabelText("密码", { exact: true }), "strong-pass-123");
    await user.type(screen.getByLabelText("确认密码"), "strong-pass-123");
    await user.click(screen.getByRole("button", { name: "注册并进入系统" }));

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/questions"));
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/register",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
  });

  it("reports a mismatched confirmation without clearing the password", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);

    await user.type(screen.getByLabelText("密码", { exact: true }), "strong-pass-123");
    await user.type(screen.getByLabelText("确认密码"), "another-pass-123");
    await user.click(screen.getByRole("button", { name: "注册并进入系统" }));

    expect(await screen.findByText("两次输入的密码不一致")).toBeInTheDocument();
    expect(screen.getByLabelText("密码", { exact: true })).toHaveValue("strong-pass-123");
  });

  it("shows a 422 password error inline without clearing the field", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      if (String(input).endsWith("/auth/me")) {
        return new Response(JSON.stringify({ code: "unauthorized", message: "未登录" }), { status: 401 });
      }
      return new Response(
        JSON.stringify({
          code: "validation_error",
          message: "请求参数无效",
          field_errors: { password: ["密码不符合安全要求"] },
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      );
    });
    renderWithProviders(<RegisterPage />);

    await user.type(screen.getByLabelText("邮箱"), "learner@example.com");
    await user.type(screen.getByLabelText("密码", { exact: true }), "strong-pass-123");
    await user.type(screen.getByLabelText("确认密码"), "strong-pass-123");
    await user.click(screen.getByRole("button", { name: "注册并进入系统" }));

    expect(await screen.findByText("密码不符合安全要求")).toBeInTheDocument();
    expect(screen.getByLabelText("密码", { exact: true })).toHaveAttribute("aria-describedby", "password-error");
    expect(screen.getByLabelText("密码", { exact: true })).toHaveValue("strong-pass-123");
  });
});
