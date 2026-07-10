import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "h-11 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#0D1B4C] outline-none",
          "placeholder:text-[#94A0B8] focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15",
          "disabled:cursor-not-allowed disabled:bg-[#F7F8FC] disabled:text-[#94A0B8]",
          className,
        )}
        {...props}
      />
    );
  },
);
