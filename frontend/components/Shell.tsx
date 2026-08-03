"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, currentUser, getTenant } from "@/lib/api";

const STAFF_NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "▦" },
  { href: "/matters", label: "Matters", icon: "⚖" },
  { href: "/documents", label: "Documents", icon: "🗎" },
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
  const nav = user?.role === "client" ? CLIENT_NAV : STAFF_NAV;

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
          <h1 className="font-display text-2xl font-bold">
            Wakili<span className="text-gold">AI</span>
          </h1>
          <p className="mt-1 truncate text-xs text-white/50">{getTenant()}</p>
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
