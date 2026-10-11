import type { Metadata } from "next";
import Link from "next/link";
import ProductMark from "@/components/ProductMark";
import SignedInRedirect from "@/components/SignedInRedirect";
import { PRODUCT } from "@/lib/brand";

export const metadata: Metadata = {
  title: `${PRODUCT.name} — ${PRODUCT.tagline}`,
  description:
    "Files, clients, AI legal research over Kenyan law, drafting, speaker-labelled meeting notes, M-Pesa billing and KDPA compliance in one secure workspace for your firm.",
};

// Simple line icons (24x24, stroke = currentColor).
const ICONS: Record<string, string> = {
  research: "M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Zm5.3-2.2L21 21",
  draft: "M4 20h4L19 9l-4-4L4 16v4Zm9-13 4 4",
  files: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  clients: "M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm11.5 9v-1a4 4 0 0 0-3-3.9M15.5 4.1a3 3 0 0 1 0 5.8",
  mic: "M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm-6-3a6 6 0 0 0 12 0M12 18v3",
  billing: "M6 3h12v18l-3-2-3 2-3-2-3 2V3Zm3 5h6M9 12h6",
  calendar: "M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Zm0 4h16M8 3v4m8-4v4",
  team: "M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6l-8-3Zm-3 9 2 2 4-4",
};

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round"
      strokeLinejoin="round" className="h-6 w-6" aria-hidden>
      <path d={ICONS[name]} />
    </svg>
  );
}

const FEATURES = [
  {
    icon: "research", title: "AI legal research on Kenyan law",
    body: "Ask in plain language and get answers grounded in the Constitution, statutes and case law — dissents included — with every citation shown. Amended or overturned authority is flagged, and your firm's own precedents stay private to your firm.",
  },
  {
    icon: "draft", title: "Drafting from your file",
    body: "Give instructions and watch pleadings and demand letters draft themselves from the matter's facts, with supporting authorities attached. Export to Word or Google Docs.",
  },
  {
    icon: "mic", title: "Meeting notes that know who said what",
    body: "Record a client meeting with consent and get a transcript labelled by speaker — English, Swahili or both — plus a summary, decisions and the action points everyone agreed, ready to turn into tasks.",
  },
  {
    icon: "files", title: "Files, deadlines & court dates",
    body: "Every matter on a board or list with its timeline, court dates, deadlines, tasks and archived documents, plus quick launchers for Judiciary e-Filing, ArdhiSasa and Business Registration (BRS).",
  },
  {
    icon: "clients", title: "Client intake done properly",
    body: "Take clients from lead to active through conflict check, signed retainer and KYC/AML gates — then give them a portal to follow their matters and invoices.",
  },
  {
    icon: "billing", title: "Billing & M-Pesa",
    body: "Log time, raise invoices with VAT, get fee suggestions from the Advocates Remuneration Order, and collect payment by M-Pesa STK push with automatic reconciliation.",
  },
  {
    icon: "calendar", title: "Calendar & reminders",
    body: "Personal and shared firm calendars, with reminders to the people who need them by WhatsApp, SMS or email.",
  },
  {
    icon: "team", title: "Your rules for who sees what",
    body: "Roles for Partners, Associates, Secretaries, Clerks and Interns out of the box — each a set of granular permissions you control — with every change recorded in an audit log.",
  },
];

const STEPS = [
  { title: "Create your firm account", body: "Two minutes: your firm's name and your details. You become its Managing Partner." },
  { title: "Set roles & permissions", body: "Start from the standard designations and decide exactly what each role can see and do." },
  { title: "Add your team", body: "Each member gets an emailed temporary password and picks their own the first time they sign in." },
];

const TRUST = [
  ["Your firm's data is walled off", "Every firm's records live in their own isolated database schema, and every request is checked against the firm it belongs to."],
  ["Built for the Data Protection Act, 2019", "Consent records, subject-access exports, and a right-to-erasure that removes a person's data from every store we keep it in."],
  ["Meeting audio stays on our servers", "Recordings are transcribed and speakers identified on our own infrastructure — only with the client's recorded consent."],
  ["Accountable by default", "An audit trail of who did what and when, and permissions enforced on the server for every single request."],
];

export default function Home() {
  return (
    <div className="bg-paper text-ink">
      <SignedInRedirect />

      <header className="sticky top-0 z-30 border-b border-navy/10 bg-paper/90 backdrop-blur">
        <nav className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <ProductMark />
          <div className="hidden items-center gap-6 text-sm text-ink/70 md:flex">
            <a href="#features" className="hover:text-navy">Features</a>
            <a href="#how" className="hover:text-navy">How it works</a>
            <a href="#security" className="hover:text-navy">Security</a>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/login" className="px-2 py-2 text-sm font-medium text-navy hover:underline">Sign in</Link>
            <Link href="/signup" className="btn-gold whitespace-nowrap">Get started</Link>
          </div>
        </nav>
      </header>

      <main>
        {/* Hero */}
        <section className="bg-navy text-white">
          <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-24">
            <div>
              <p className="text-sm font-semibold uppercase tracking-widest text-gold">{PRODUCT.tagline}</p>
              <h1 className="mt-4 font-display text-4xl font-bold leading-tight sm:text-5xl">
                Run your practice and research Kenyan law in one secure workspace.
              </h1>
              <p className="mt-5 max-w-xl text-lg text-white/75">
                {PRODUCT.name} brings your files, clients, court dates, drafting, meeting notes and M-Pesa billing
                together with an AI researcher that cites Kenyan authority — so your team spends its time on the law,
                not the admin.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link href="/signup" className="btn-gold !px-6 !py-3 text-center text-base">Create your firm account</Link>
                <Link href="/login" className="rounded-md border border-white/30 px-6 py-3 text-center text-base font-medium text-white transition hover:border-gold hover:text-gold">
                  Sign in to your firm
                </Link>
              </div>
            </div>
            <HeroPreview />
          </div>
        </section>

        {/* Features */}
        <section id="features" className="scroll-mt-16">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
            <h2 className="max-w-2xl font-display text-3xl font-bold text-navy sm:text-4xl">
              What {PRODUCT.name} delivers to your firm
            </h2>
            <p className="mt-3 max-w-2xl text-ink/70">
              Everything a Kenyan practice runs on, designed around how advocates, secretaries and clerks actually work.
            </p>
            <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {FEATURES.map((f) => (
                <article key={f.title} className="card flex flex-col">
                  <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-navy text-gold">
                    <Icon name={f.icon} />
                  </span>
                  <h3 className="mt-4 font-display text-lg font-bold text-navy">{f.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink/70">{f.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="scroll-mt-16 border-y border-navy/10 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-20">
            <h2 className="font-display text-3xl font-bold text-navy sm:text-4xl">Up and running this afternoon</h2>
            <ol className="mt-10 grid grid-cols-1 gap-8 md:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title} className="relative">
                  <span className="font-display text-5xl font-bold text-gold/70">{i + 1}</span>
                  <h3 className="mt-2 text-lg font-semibold text-navy">{s.title}</h3>
                  <p className="mt-1 text-sm text-ink/70">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Security */}
        <section id="security" className="scroll-mt-16">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:py-24">
            <div>
              <h2 className="font-display text-3xl font-bold text-navy sm:text-4xl">Confidentiality is the whole point</h2>
              <p className="mt-3 text-ink/70">
                Advocate–client privilege doesn&apos;t bend for software. {PRODUCT.name} is built so your firm&apos;s work
                stays your firm&apos;s.
              </p>
            </div>
            <dl className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              {TRUST.map(([title, body]) => (
                <div key={title} className="border-l-2 border-gold pl-4">
                  <dt className="font-semibold text-navy">{title}</dt>
                  <dd className="mt-1 text-sm text-ink/70">{body}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* CTA */}
        <section className="bg-navy">
          <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-4 py-14 sm:px-6 md:flex-row md:items-center">
            <div>
              <h2 className="font-display text-3xl font-bold text-white">Bring your firm onto {PRODUCT.name}</h2>
              <p className="mt-2 text-white/70">Create the account, set your roles, add your team.</p>
            </div>
            <Link href="/signup" className="btn-gold !px-6 !py-3 text-base">Create your firm account</Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-navy/10">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-4 py-8 text-sm text-ink/60 sm:flex-row sm:items-center sm:px-6">
          <ProductMark />
          <div className="flex gap-5">
            <Link href="/login" className="hover:text-navy">Sign in</Link>
            <Link href="/signup" className="hover:text-navy">Create a firm account</Link>
          </div>
          <p>© {new Date().getFullYear()} {PRODUCT.name}</p>
        </div>
      </footer>
    </div>
  );
}

/** Illustrative, static preview of two product surfaces (not live data). */
function HeroPreview() {
  return (
    <div className="relative" aria-hidden>
      <div className="rounded-xl bg-white p-5 text-ink shadow-2xl">
        <p className="text-xs font-semibold uppercase tracking-wide text-navy/50">AI Research</p>
        <p className="mt-2 font-medium text-navy">Can an employer dismiss without a hearing?</p>
        <p className="mt-2 text-sm leading-relaxed text-ink/75">
          No. Before terminating for misconduct or poor performance, the employer must explain the reason to the
          employee and hear any representations they make…
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="badge-public">Public law</span>
          <span className="rounded border border-navy/15 px-2 py-0.5 text-xs text-navy">Employment Act, s.41</span>
          <span className="rounded border border-navy/15 px-2 py-0.5 text-xs text-navy">Constitution, art.47</span>
        </div>
      </div>
      <div className="relative -mt-4 ml-6 rounded-xl border border-gold/40 bg-paper p-5 text-ink shadow-2xl sm:ml-16">
        <p className="text-xs font-semibold uppercase tracking-wide text-navy/50">Meeting notes · 2 speakers</p>
        <p className="mt-2 text-sm"><b className="text-navy">Advocate:</b> We&apos;ll file the plaint at Milimani by Friday.</p>
        <p className="mt-1 text-sm"><b className="text-gold-dim">Client:</b> Sawa — I&apos;ll bring the title deed tomorrow.</p>
        <p className="mt-3 text-xs font-bold uppercase tracking-wide text-navy/50">Agreed action points</p>
        <ul className="mt-1 space-y-1 text-sm text-ink/80">
          <li>☐ Advocate — file plaint at Milimani <span className="text-ink/50">· by Friday</span></li>
          <li>☐ Client — deliver original title deed <span className="text-ink/50">· tomorrow</span></li>
        </ul>
      </div>
    </div>
  );
}
