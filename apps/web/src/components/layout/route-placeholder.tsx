import Link from "next/link";

import { ArrowRight } from "lucide-react";

interface RoutePlaceholderProps {
  title: string;
  description: string;
  action: {
    href: string;
    label: string;
  };
}

export function RoutePlaceholder({ title, description, action }: RoutePlaceholderProps) {
  return (
    <section className="max-w-3xl rounded-xl border border-[#E4E8F2] bg-white px-6 py-10 sm:px-9" aria-labelledby="placeholder-title">
      <p className="text-sm font-medium text-[#4F46E5]">学习空间</p>
      <h1 id="placeholder-title" className="mt-3 text-2xl font-semibold tracking-tight text-[#0D1B4C]">
        {title}
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-[#6A7893]">{description}</p>
      <Link
        href={action.href}
        className="mt-7 inline-flex h-11 items-center gap-2 rounded-lg bg-[#4F46E5] px-4 text-sm font-medium text-white transition-colors hover:bg-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2"
      >
        {action.label}
        <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </section>
  );
}
