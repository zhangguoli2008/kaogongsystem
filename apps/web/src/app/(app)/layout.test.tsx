import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppLayout from "./layout";
import { ApiError } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

const { sessionState, mockReplaceDocument, fetchMock } = vi.hoisted(() => ({
  sessionState: {
    current: {
      data: { id: "u1", email: "learner@example.com" },
      error: null,
      isError: false,
      isPending: false,
    },
  },
  mockReplaceDocument: vi.fn(),
  fetchMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

vi.mock("@/lib/document-navigation", () => ({
  replaceDocument: mockReplaceDocument,
}));

vi.mock("@/hooks/use-session", () => ({
  useSession: () => sessionState.current,
}));

describe("AppLayout", () => {
  beforeEach(() => {
    sessionState.current = {
      data: { id: "u1", email: "learner@example.com" },
      error: null,
      isError: false,
      isPending: false,
    };
    mockReplaceDocument.mockReset();
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders the approved navigation in its visual order", () => {
    renderWithProviders(
      <AppLayout>
        <p>业务页面内容</p>
      </AppLayout>,
    );

    expect(screen.getAllByRole("link").map((link) => link.textContent?.trim())).toEqual([
      "首页",
      "错题录入",
      "错题库",
      "今日复习",
      "数据统计",
    ]);
    expect(screen.getByText("业务页面内容")).toBeInTheDocument();
  });

  it("does not render protected navigation while a 401 redirects to login", () => {
    sessionState.current = {
      data: undefined,
      error: new ApiError(401, { code: "unauthorized", message: "未登录" }),
      isError: true,
      isPending: false,
    };

    renderWithProviders(
      <AppLayout>
        <p>受保护内容</p>
      </AppLayout>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("正在返回登录页…");
    expect(screen.queryByRole("navigation", { name: "主导航" })).not.toBeInTheDocument();
    expect(screen.queryByText("受保护内容")).not.toBeInTheDocument();
  });

  it("logs out from the application header and returns to login", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    queryClient.setQueryData(["session"], { id: "u1", email: "learner@example.com" });
    queryClient.setQueryData(["dashboard"], { recent_questions: [{ id: "private-question" }] });

    render(
      <QueryClientProvider client={queryClient}>
        <AppLayout>
          <p>业务页面内容</p>
        </AppLayout>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(mockReplaceDocument).toHaveBeenCalledWith("/login"));
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/logout",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
    expect(queryClient.getQueryData(["session"])).toBeUndefined();
    expect(queryClient.getQueryData(["dashboard"])).toBeUndefined();
  });

  it("keeps the current account data and shows a retryable error when logout fails", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    queryClient.setQueryData(["session"], { id: "u1", email: "learner@example.com" });
    queryClient.setQueryData(["dashboard"], { recent_questions: [{ id: "private-question" }] });
    fetchMock.mockRejectedValueOnce(new TypeError("network unavailable"));

    render(
      <QueryClientProvider client={queryClient}>
        <AppLayout>
          <p>业务页面内容</p>
        </AppLayout>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("退出失败，请检查网络后重试");
    expect(screen.getByRole("button", { name: "退出登录" })).toBeEnabled();
    expect(mockReplaceDocument).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(["session"])).toEqual({ id: "u1", email: "learner@example.com" });
    expect(queryClient.getQueryData(["dashboard"])).toEqual({ recent_questions: [{ id: "private-question" }] });
  });
});
