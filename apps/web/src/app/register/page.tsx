"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { applyApiFormErrors } from "@/lib/form-errors";
import { resolveReturnTo } from "@/lib/return-to";
import { registerSchema, type RegisterValues } from "@/lib/schemas";
import type { User } from "@/types/api";

function currentReturnTo() {
  return resolveReturnTo(new URLSearchParams(window.location.search).get("returnTo"));
}

export default function RegisterPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSession({ redirectOnUnauthorized: false });
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: "", password: "", confirmPassword: "" },
  });

  useEffect(() => {
    if (session.data) {
      router.replace(currentReturnTo());
    }
  }, [router, session.data]);

  const registerUser = useMutation({
    mutationFn: (values: RegisterValues) =>
      apiFetch<User>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email: values.email, password: values.password }),
      }),
    onSuccess: (user) => {
      queryClient.setQueryData(["session"], user);
      router.replace(currentReturnTo());
    },
    onError: (error) => {
      applyApiFormErrors(error, setError, ["email", "password", "confirmPassword"]);
    },
  });

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="register-title">
        <div className="auth-brand">
          <span className="flex size-11 items-center justify-center rounded-xl bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
            <BrainCircuit className="size-7" />
          </span>
          <span className="font-semibold text-[#0D1B4C]">公考错题诊断系统</span>
        </div>
        <div className="mt-10">
          <p className="text-sm font-medium text-[#4F46E5]">开始建立复习闭环</p>
          <h1 id="register-title" className="mt-3 text-3xl font-semibold tracking-tight text-[#0D1B4C]">
            创建你的学习账号
          </h1>
          <p className="mt-3 text-sm leading-6 text-[#6A7893]">从整理错题开始，让每一次复盘都有收获。</p>
        </div>
        <form className="mt-8 space-y-4" noValidate onSubmit={handleSubmit((values) => registerUser.mutate(values))}>
          <Field label="邮箱" htmlFor="email" error={errors.email?.message}>
            <Input id="email" type="email" autoComplete="email" aria-invalid={Boolean(errors.email)} aria-describedby={errors.email ? "email-error" : undefined} {...register("email")} />
          </Field>
          <Field label="密码" htmlFor="password" hint="至少 8 位字符" error={errors.password?.message}>
            <Input id="password" type="password" autoComplete="new-password" aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? "password-error" : undefined} {...register("password")} />
          </Field>
          <Field label="确认密码" htmlFor="confirmPassword" error={errors.confirmPassword?.message}>
            <Input id="confirmPassword" type="password" autoComplete="new-password" aria-invalid={Boolean(errors.confirmPassword)} aria-describedby={errors.confirmPassword ? "confirmPassword-error" : undefined} {...register("confirmPassword")} />
          </Field>
          {errors.root?.message ? <p className="text-sm text-[#D84755]" role="alert">{errors.root.message}</p> : null}
          <Button className="mt-2 w-full" type="submit" disabled={registerUser.isPending}>
            <UserPlus className="size-4" aria-hidden="true" />
            {registerUser.isPending ? "正在创建…" : "注册并进入系统"}
          </Button>
        </form>
        <p className="mt-7 text-center text-sm text-[#6A7893]">
          已有账号？{" "}
          <Link className="font-medium text-[#4F46E5] hover:text-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]" href="/login">
            返回登录
          </Link>
        </p>
      </section>
    </main>
  );
}
