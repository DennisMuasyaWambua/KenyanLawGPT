"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Sends a visitor who is already signed in straight to their workspace. */
export default function SignedInRedirect() {
  const router = useRouter();
  useEffect(() => {
    try {
      if (localStorage.getItem("wakili_access")) router.replace("/dashboard");
    } catch {
      /* storage blocked: just show the page */
    }
  }, [router]);
  return null;
}
