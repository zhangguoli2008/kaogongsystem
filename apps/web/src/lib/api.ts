import type { ApiErrorPayload } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const fallbackError: ApiErrorPayload = {
  code: "network_error",
  message: "请求失败，请稍后重试",
};

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorPayload;

  constructor(status: number, body: ApiErrorPayload) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

function isFormData(body: BodyInit | null | undefined): body is FormData {
  return typeof FormData !== "undefined" && body instanceof FormData;
}

function isApiErrorPayload(value: unknown): value is ApiErrorPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    typeof value.code === "string" &&
    "message" in value &&
    typeof value.message === "string"
  );
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);

  if (!isFormData(init.body) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    const parsedBody: unknown = await response.json().catch(() => fallbackError);
    throw new ApiError(
      response.status,
      isApiErrorPayload(parsedBody) ? parsedBody : fallbackError,
    );
  }

  return response.status === 204 ? (undefined as T) : response.json();
}
