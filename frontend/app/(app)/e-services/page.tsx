"use client";

// Kenyan government e-services. These portals send X-Frame-Options / require
// their own authenticated session, so they cannot be embedded in an iframe —
// we launch them in a new tab instead.
const PORTALS = [
  {
    name: "Judiciary e-Filing",
    tag: "Courts",
    url: "https://efiling.court.go.ke",
    desc: "File and track court documents, pay court fees and serve pleadings on the Judiciary's e-Filing portal.",
  },
  {
    name: "ArdhiSasa (Lands)",
    tag: "Lands",
    url: "https://ardhisasa.lands.go.ke",
    desc: "Land searches, transfers, subdivisions and registration on the Ministry of Lands portal.",
  },
  {
    name: "Business Registration (BRS)",
    tag: "Companies",
    url: "https://brs.go.ke",
    desc: "Company and business-name search, registration and compliance filings (Business Registration Service).",
  },
] as const;

export default function EServicesPage() {
  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">e-Services</h2>
      <p className="mt-1 max-w-2xl text-sm text-ink/60">
        Quick access to the Kenyan government portals your firm uses. Each requires its own login and
        blocks embedding, so they open securely in a new tab.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        {PORTALS.map((p) => (
          <a
            key={p.url}
            href={p.url}
            target="_blank"
            rel="noopener noreferrer"
            className="card group flex flex-col transition hover:border-gold hover:shadow-md"
          >
            <span className="badge-private w-fit">{p.tag}</span>
            <h3 className="mt-3 font-display text-lg font-bold text-navy">{p.name}</h3>
            <p className="mt-1 flex-1 text-sm text-ink/60">{p.desc}</p>
            <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-gold-dim group-hover:underline">
              Open {p.name} ↗
            </span>
            <span className="mt-1 truncate text-xs text-ink/40">{p.url.replace("https://", "")}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
