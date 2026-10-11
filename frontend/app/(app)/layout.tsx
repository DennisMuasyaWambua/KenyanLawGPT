"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import Shell from "@/components/Shell";
import { api } from "@/lib/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!localStorage.getItem("wakili_access")) {
      router.replace("/login");
      return;
    }
    // Shares the ["me"] cache with usePermissions, so this costs no extra request.
    qc.fetchQuery({ queryKey: ["me"], queryFn: () => api("/api/v1/auth/me") })
      .then((me: any) => {
        if (me?.user?.must_change_password) {
          router.replace("/change-password");
        } else if (me?.tenant && me.tenant.onboarding_completed === false &&
                   (me.permissions || []).includes("firm_settings.edit")) {
          router.replace("/onboarding");
        } else {
          setReady(true);
        }
      })
      .catch(() => setReady(true)); // api() already redirects on auth failures
  }, [router, qc]);
  if (!ready) return null;
  return <Shell>{children}</Shell>;
}
