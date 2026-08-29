// Single source of truth for product branding. The platform is white-labelled
// as the operating firm; individual tenant firms still see their own name in
// their workspace (rendered from the tenant slug/name, not from BRAND).
export const BRAND = {
  /** Full legal name — used for the browser tab title and the dashboard watermark. */
  name: "C. Karwitha & Co. Advocates",
  /** Compact wordmark for tight spaces (sidebar, headers). */
  short: "C. Karwitha & Co.",
  /** Subtitle under the wordmark. */
  sub: "Advocates",
  /** Public path to the letterhead logo (served from /public). */
  logo: "/logo.jpeg",
  tagline: "Practice management & AI legal research for Kenyan firms",
} as const;
