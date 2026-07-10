"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { BrainCircuit, LogIn } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiFetch } from "@/lib/api";
import { loginSchema, type LoginValues } from "@/lib/schemas";
import type { User } from "@/types/api";

export default function LoginPage() {
  const router = useRouter();
  const session = useSession({ redirectOnUnauthorized: false });
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  useEffect(() => {
    if (session.data) {
      router.replace("/dashboard");
    }
  }, [router, session.data]);

  const login = useMutation({
    mutationFn: (values: LoginValues) =>
      apiFetch<User>("/auth/login", {
        method: "POST",
        body: JSON.stringify(values),
      }),
    onSuccess: () => router.replace("/dashboard"),
    onError: (error) => {
      const message = error instanceof ApiError ? error.body.message : "网络连接失败，请稍后重试";
      setError("root", { message });
    },
  });

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="login-title">
        <div className="auth-brand">
          <span className="flex size-11 items-center justify-center rounded-xl bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
            <BrainCircuit className="size-7" />
          </span>
          <span className="font-semibold text-[#0D1B4C]">公考错题诊断系统</span>
        </div>
        <div className="mt-12">
          <p className="text-sm font-medium text-[#4F46E5]">欢迎回来</p>
          <h1 id="login-title" className="mt-3 text-3xl font-semibold tracking-tight text-[#0D1B4C]">
            登录后继续你的复习
          </h1>
          <p className="mt-3 text-sm leading-6 text-[#6A7893]">把每一道错题，变成下一次进步的线索。</p>
        </div>
        <form className="mt-9 space-y-5" noValidate onSubmit={handleSubmit((values) => login.mutate(values))}>
          <Field label="邮箱" htmlFor="email" error={errors.email?.message}>
            <Input id="email" type="email" autoComplete="email" aria-invalid={Boolean(errors.email)} {...register("email")} />
          </Field>
          <Field label="密码" htmlFor="password" error={errors.password?.message}>
            <Input id="password" type="password" autoComplete="current-password" aria-invalid={Boolean(errors.password)} {...register("password")} />
          </Field>
          {errors.root?.message ? <p className="text-sm text-[#D84755]" role="alert">{errors.root.message}</p> : null}
          <Button className="w-full" type="submit" disabled={login.isPending}>
            <LogIn className="size-4" aria-hidden="true" />
            {login.isPending ? "正在登录…" : "登录"}
          </Button>
        </form>
        <p className="mt-8 text-center text-sm text-[#6A7893]">
          还没有账号？{" "}
          <Link className="font-medium text-[#4F46E5] hover:text-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]" href="/register">
            前往注册
          </Link>
        </p>
      </section>
    </main>
  );
}
