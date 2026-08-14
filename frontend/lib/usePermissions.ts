"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// usePermissions reads the caller's granted permissions from /auth/me (the
// firm-scoped RBAC source of truth) so the UI can hide actions the user can't
// perform. The server still enforces every permission independently — this is
// purely cosmetic gating. Shares the ["me"] query cache with other callers.
export function usePermissions() {
  const { data } = useQuery({ queryKey: ["me"], queryFn: () => api("/api/v1/auth/me") });
  const permissions: string[] = data?.permissions || [];
  const set = new Set(permissions);
  return {
    me: data,
    permissions,
    can: (perm: string) => set.has(perm),
  };
}
