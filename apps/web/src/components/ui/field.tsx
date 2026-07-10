import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

interface FieldProps {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}

export function Field({ label, htmlFor, error, hint, children }: FieldProps) {
  const message = error ?? hint;

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-[#0D1B4C]" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {message ? (
        <p
          className={cn("text-xs leading-5", error ? "text-[#D84755]" : "text-[#6A7893]")}
          id={error ? `${htmlFor}-error` : undefined}
        >
          {message}
        </p>
      ) : null}
    </div>
  );
}
