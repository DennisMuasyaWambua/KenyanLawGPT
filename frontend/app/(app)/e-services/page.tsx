"use client";

import { useState } from "react";

// Kenyan government e-services the firm uses. These portals generally send
// X-Frame-Options / frame-ancestors headers that block embedding, so we embed
// in an iframe AND always offer a launch-in-new-tab fallback.
const PORTALS = [
  {
    key: "efiling",
    name: "Judiciary e-Filing",
    url: "https://efiling.court.go.ke",
    desc: "File and track court documents on the Judiciary's e-Filing portal.",
  },
  {
    key: "ardhisasa",
    name: "ArdhiSasa (Lands)",
    url: "https://ardhisasa.lands.go.ke",
    desc: "Land searches, transfers and registration on the Ministry of Lands portal.",
  },
  {
    key: "brs",
    name: "Business Registration (BRS)",
    url: "https://brs.go.ke",
    desc: "Company & business name search and registration (Business Registration Service).",
  },
] as const;

export default function EServicesPage() {
  const [active, setActive] = useState<(typeof PORTALS)[number]["key"]>("efiling");
  const portal = PORTALS.find((p) => p.key === active)!;

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-3xl font-bold text-navy">e-Services</h2>
        <a href={portal.url} target="_blank" rel="noopener noreferrer" className="btn-gold">
          Open {portal.name} in new tab ↗
        </a>
      </div>

      <div className="mt-4 flex gap-2">
        {PORTALS.map((p) => (
          <button
            key={p.key}
            onClick={() => setActive(p.key)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              active === p.key ? "bg-navy text-white" : "bg-white text-navy border border-navy/20 hover:border-gold"
            }`}
          >
            {p.name}
          </button>
        ))}
      </div>

      <p className="mt-2 text-sm text-ink/60">{portal.desc}</p>

      <div className="mt-3 flex-1 overflow-hidden rounded-lg border border-navy/10 bg-white">
        <iframe
          key={portal.key}
          src={portal.url}
          title={portal.name}
          className="h-full w-full"
          referrerPolicy="no-referrer"
          sandbox="allow-forms allow-scripts allow-same-origin allow-popups allow-top-navigation"
        />
      </div>
      <p className="mt-2 text-center text-xs text-ink/40">
        If the portal doesn&rsquo;t load above, it blocks embedding — use the “Open in new tab” button.
      </p>
    </div>
  );
}
