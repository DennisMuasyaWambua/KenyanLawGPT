"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { adminApi, clearAdminSession, currentAdmin } from "@/lib/admin";
import { BRAND } from "@/lib/brand";

const NAV = [
  { href: "/admin", label: "Overview", icon: "▦" },
  { href: "/admin/audit", label: "Audit log", icon: "🗐" },
  { href: "/admin/admins", label: "Admins", icon: "⚿" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/admin/login";
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isLogin) {
      setReady(true);
      return;
    }
    if (!localStorage.getItem("wakili_admin_at")) {
      router.replace("/admin/login");
      return;
    }
    setReady(true);
  }, [isLogin, router]);

  if (!ready) return null;
  if (isLogin) return <>{children}</>;

  const admin = currentAdmin();
  async function logout() {
    try {
      await adminApi("/logout", { method: "POST" });
    } catch {
      /* best effort */
    }
    clearAdminSession();
    router.push("/admin/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col bg-navy text-white">
        <div className="border-b border-white/10 p-5">
          <div className="flex items-center gap-3">
            <img src={BRAND.logo} alt={BRAND.name} className="h-10 w-10 shrink-0 rounded-md bg-white object-cover object-left ring-1 ring-white/20" />
            <div className="min-w-0">
              <h1 className="font-display text-lg font-bold leading-tight">Control Center</h1>
              <p className="text-[11px] uppercase tracking-wide text-gold">Platform admin</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                pathname === item.href ? "bg-gold text-navy font-semibold" : "text-white/80 hover:bg-white/10"
              }`}
            >
              <span className="w-4 text-center">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-white/10 p-4">
          <p className="truncate text-sm font-medium">{admin?.full_name || admin?.email}</p>
          <p className="text-xs text-gold">Super admin</p>
          <button onClick={logout} className="mt-2 text-xs text-white/60 hover:text-white">
            Sign out →
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden p-8">{children}</main>
    </div>
  );
}
