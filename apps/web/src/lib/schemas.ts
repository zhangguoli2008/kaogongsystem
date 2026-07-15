import { z } from "zod";

const emailSchema = z
  .string()
  .trim()
  .min(1, "请输入邮箱地址")
  .email("请输入有效的邮箱地址");

const passwordSchema = z
  .string()
  .min(8, "密码至少需要 8 位")
  .max(128, "密码不能超过 128 位");

export const loginSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
});

export const registerSchema = z
  .object({
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string().min(1, "请再次输入密码"),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "两次输入的密码不一致",
    path: ["confirmPassword"],
  });

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
