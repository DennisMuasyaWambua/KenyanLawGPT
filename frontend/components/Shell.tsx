"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, currentUser } from "@/lib/api";
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
  { href: "/research", label: "AI Research", icon: "🔍", perm: "research.query" },
  { href: "/drafting", label: "Drafts", icon: "✎", perm: "drafting.create" },
  { href: "/inbox", label: "Communications", icon: "✉" },
  { href: "/e-services", label: "e-Services", icon: "🏛" },
  { href: "/billing", label: "Billing", icon: "₿", perm: "billing.view" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

const CLIENT_NAV = [{ href: "/portal", label: "My Portal", icon: "▦" }];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const user = currentUser();
  const { can, permissions } = usePermissions();
  // Mobile: sidebar is an off-canvas drawer; static from `md` up.
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Desktop: sidebar can collapse to an icon rail that expands on hover; the
  // pinned state persists across sessions.
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    setCollapsed(localStorage.getItem("wakili_nav_collapsed") === "1");
  }, []);
  function toggleCollapsed() {
    setCollapsed((v) => {
      const next = !v;
      localStorage.setItem("wakili_nav_collapsed", next ? "1" : "0");
      return next;
    });
  }
  // Close the drawer whenever we navigate to a new route.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);
  // Collapsed-only helpers: hide labels/brand on the rail, reveal on hover.
  const railWidth = collapsed ? "md:w-16 md:hover:w-60" : "md:w-60";
  const hideOnRail = collapsed ? "md:hidden md:group-hover:block" : "";
  const hideLabelOnRail = collapsed ? "md:hidden md:group-hover:inline" : "";
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
      {/* Backdrop — only rendered on mobile while the drawer is open. */}
      {drawerOpen && (
        <div
          aria-hidden
          onClick={() => setDrawerOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
        />
      )}
      <aside
        className={`group fixed inset-y-0 left-0 z-40 flex w-60 flex-col overflow-hidden bg-navy text-white transition-all duration-200 md:static md:z-auto md:translate-x-0 ${railWidth} ${
          drawerOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="border-b border-white/10 px-3 py-4">
          <div className="flex items-center gap-3">
            <img
              src={BRAND.logo}
              alt={BRAND.name}
              className="h-10 w-10 shrink-0 rounded-md bg-white object-cover object-left ring-1 ring-white/20"
            />
            <div className={`min-w-0 ${hideOnRail}`}>
              <h1 className="font-display text-lg font-bold leading-tight">{BRAND.short}</h1>
              <p className="text-[11px] uppercase tracking-wide text-gold">{BRAND.sub}</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                collapsed ? "md:justify-center md:group-hover:justify-start" : ""
              } ${
                pathname.startsWith(item.href)
                  ? "bg-gold text-navy font-semibold"
                  : "text-white/80 hover:bg-white/10"
              }`}
            >
              <span className="w-4 shrink-0 text-center">{item.icon}</span>
              <span className={`truncate ${hideLabelOnRail}`}>{item.label}</span>
            </Link>
          ))}
        </nav>
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden items-center gap-3 border-t border-white/10 px-3 py-2 text-xs text-white/50 transition hover:text-white md:flex"
        >
          <span className="w-4 shrink-0 text-center text-base leading-none">{collapsed ? "»" : "«"}</span>
          <span className={hideLabelOnRail}>Collapse</span>
        </button>
        <div className="border-t border-white/10 p-4">
          <div className={hideOnRail}>
            <p className="truncate text-sm font-medium">{user?.full_name}</p>
            <p className="text-xs capitalize text-gold">{user?.role}</p>
            <button onClick={logout} className="mt-2 text-xs text-white/60 hover:text-white">
              Sign out →
            </button>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar with hamburger — hidden from `md` up. */}
        <header className="flex items-center gap-3 border-b border-navy/10 bg-white px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open menu"
            className="text-2xl leading-none text-navy"
          >
            ☰
          </button>
          <img
            src={BRAND.logo}
            alt=""
            className="h-8 w-8 shrink-0 rounded bg-white object-cover object-left ring-1 ring-navy/10"
          />
          <span className="truncate font-display text-base font-bold text-navy">{BRAND.short}</span>
        </header>
        <main className="flex-1 overflow-x-hidden p-4 sm:p-6 md:p-8">{children}</main>
      </div>
    </div>
  );
}
