export interface User {
  id: string;
  email: string;
  created_at?: string;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  field_errors?: Record<string, string[]> | null;
  request_id?: string;
}
