"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import type { User } from "@/types/api";

interface UseSessionOptions {
  redirectOnUnauthorized?: boolean;
}

export function useSession({ redirectOnUnauthorized = true }: UseSessionOptions = {}): UseQueryResult<User> {
  const router = useRouter();
  const query = useQuery({
    queryKey: ["session"],
    queryFn: () => apiFetch<User>("/auth/me"),
  });

  useEffect(() => {
    if (redirectOnUnauthorized && query.error instanceof ApiError && query.error.status === 401) {
      router.replace("/login");
    }
  }, [query.error, redirectOnUnauthorized, router]);

  return query;
}
