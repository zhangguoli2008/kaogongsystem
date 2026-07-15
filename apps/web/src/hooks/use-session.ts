"use client";

import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { loginPathFor } from "@/lib/return-to";
import type { User } from "@/types/api";

interface UseSessionOptions {
  redirectOnUnauthorized?: boolean;
}

export function useSession({ redirectOnUnauthorized = true }: UseSessionOptions = {}): UseQueryResult<User> {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const isRedirectingRef = useRef(false);
  const query = useQuery({
    queryKey: ["session"],
    queryFn: () => apiFetch<User>("/auth/me"),
  });

  useEffect(() => {
    if (
      redirectOnUnauthorized &&
      !isRedirectingRef.current &&
      query.error instanceof ApiError &&
      query.error.status === 401
    ) {
      isRedirectingRef.current = true;
      queryClient.removeQueries({ queryKey: ["session"], exact: true });
      router.replace(loginPathFor(pathname, window.location.search.slice(1)));
    }
  }, [pathname, query.error, queryClient, redirectOnUnauthorized, router]);

  return query;
}
