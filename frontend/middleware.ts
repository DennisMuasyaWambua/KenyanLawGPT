import { NextRequest, NextResponse } from "next/server";

// Multi-tenant routing: `{firm-slug}.wakili.ai` resolves the tenant from the
// subdomain and injects it as a header + cookie for the API client. On plain
// localhost (no subdomain) the login screen collects the firm slug instead.
const BASE_DOMAIN = process.env.NEXT_PUBLIC_BASE_DOMAIN || "localhost";

export function middleware(req: NextRequest) {
  const host = (req.headers.get("host") || "").split(":")[0];
  let slug = "";
  if (host.endsWith("." + BASE_DOMAIN)) {
    slug = host.slice(0, -1 * ("." + BASE_DOMAIN).length);
  }
  const headers = new Headers(req.headers);
  if (slug) headers.set("x-tenant-slug", slug);
  const res = NextResponse.next({ request: { headers } });
  if (slug) {
    res.cookies.set("wakili_tenant", slug, { path: "/", sameSite: "lax" });
  }
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
