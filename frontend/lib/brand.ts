// Branding. Inside the app every firm sees ITS OWN name (from /auth/me), never
// another firm's; the product name appears only on the public pages and the
// platform admin console.

// The product, as marketed to law firms on the landing / signup pages.
export const PRODUCT = {
  name: "Advocatus",
  tagline: "The practice platform for Kenyan law firms",
} as const;

// Letterhead logos for firms that have one, by firm ID (served from /public).
// Firms without one get a monogram of their initials (see FirmMark).
export const FIRM_LOGOS: Record<string, string> = {
  ckarwitha: "/logo.jpeg",
};

/** "Mwangi & Co. Advocates" -> "MC" (skips connectives and "Advocates"/"LLP"). */
export function firmInitials(name: string): string {
  const skip = new Set(["and", "&", "of", "the", "co", "advocates", "advocate", "llp", "associates"]);
  const words = name.split(/[\s.,&]+/).filter((w) => w && !skip.has(w.toLowerCase()));
  const letters = (words.length ? words : name.split(/\s+/)).slice(0, 2).map((w) => w[0]?.toUpperCase() || "");
  return letters.join("") || "•";
}
