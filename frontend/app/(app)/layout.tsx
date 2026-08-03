"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Shell from "@/components/Shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!localStorage.getItem("wakili_access")) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);
  if (!ready) return null;
  return <Shell>{children}</Shell>;
}
