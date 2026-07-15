import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "@/lib/api";

function fieldMessage(error: ApiError, field: string): string | undefined {
  return error.body.field_errors?.[field]?.[0] ?? error.body.field_errors?.[`body.${field}`]?.[0];
}

export function applyApiFormErrors<TValues extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<TValues>,
  fields: readonly Path<TValues>[],
) {
  if (!(error instanceof ApiError)) {
    setError("root", { type: "server", message: "网络连接失败，请稍后重试" });
    return;
  }

  let mappedFieldError = false;
  for (const field of fields) {
    const message = fieldMessage(error, field);
    if (message) {
      setError(field, { type: "server", message });
      mappedFieldError = true;
    }
  }

  if (!mappedFieldError) {
    setError("root", { type: "server", message: error.body.message });
  }
}
