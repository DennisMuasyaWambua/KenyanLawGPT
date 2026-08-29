"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, currentUser, getTenant } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";
import { BRAND } from "@/lib/brand";

// `perm` (optional) hides a nav item unless the caller holds that permission.
const STAFF_NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "▦" },
  { href: "/cases", label: "Case status", icon: "▤", perm: "matters.view_all" },
  { href: "/files", label: "Files", icon: "⚖" },
  { href: "/clients", label: "Clients", icon: "👤", perm: "clients.view" },
  { href: "/tasks", label: "Tasks", icon: "✔", perm: "tasks.view_own" },
  { href: "/calendar", label: "Calendar", icon: "🗓" },
  { href: "/recordings", label: "Recordings", icon: "🎙", perm: "recordings.view_own" },
  { href: "/archives", label: "Archives", icon: "🗎" },
  { href: "/research", label: "AI Research", icon: "🔍" },
  { href: "/drafting", label: "Drafting", icon: "✎" },
  { href: "/inbox", label: "Communications", icon: "✉" },
  { href: "/billing", label: "Billing", icon: "₿" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

const CLIENT_NAV = [{ href: "/portal", label: "My Portal", icon: "▦" }];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const user = currentUser();
  const { can, permissions } = usePermissions();
  // Until permissions load, show ungated items; hide gated ones the user lacks.
  const nav =
    user?.role === "client"
      ? CLIENT_NAV
      : STAFF_NAV.filter((i) => !i.perm || permissions.length === 0 || can(i.perm));

  async function logout() {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* best effort */
    }
    clearSession();
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col bg-navy text-white">
        <div className="border-b border-white/10 p-5">
          <div className="flex items-center gap-3">
            <img
              src={BRAND.logo}
              alt={BRAND.name}
              className="h-10 w-10 shrink-0 rounded-md bg-white object-cover object-left ring-1 ring-white/20"
            />
            <div className="min-w-0">
              <h1 className="font-display text-lg font-bold leading-tight">{BRAND.short}</h1>
              <p className="text-[11px] uppercase tracking-wide text-gold">{BRAND.sub}</p>
            </div>
          </div>
          <p className="mt-2 truncate text-xs text-white/50">{getTenant()}</p>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                pathname.startsWith(item.href)
                  ? "bg-gold text-navy font-semibold"
                  : "text-white/80 hover:bg-white/10"
              }`}
            >
              <span className="w-4 text-center">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-white/10 p-4">
          <p className="truncate text-sm font-medium">{user?.full_name}</p>
          <p className="text-xs capitalize text-gold">{user?.role}</p>
          <button onClick={logout} className="mt-2 text-xs text-white/60 hover:text-white">
            Sign out →
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden p-8">{children}</main>
    </div>
  );
}
