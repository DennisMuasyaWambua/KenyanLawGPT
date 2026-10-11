"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { setSession } from "@/lib/api";
import GoogleButton from "@/components/GoogleButton";
import ProductMark from "@/components/ProductMark";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

// Mirrors the gateway's SlugFromName; the server validates again.
const slugify = (s: string) =>
  s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/, "");

const NEXT_STEPS = [
  ["Create your firm", "You become the Managing Partner, with full control of the workspace."],
  ["Set roles & permissions", "Start from Partner, Associate, Secretary, Clerk and Intern, then adjust what each can do."],
  ["Add your team", "Each member is emailed a temporary password and picks their own at first sign-in."],
];

export default function SignupPage() {
  const router = useRouter();
  const [firmName, setFirmName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [regNumber, setRegNumber] = useState("");
  const [phone, setPhone] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [residency, setResidency] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const firmId = slugTouched ? slug : slugify(firmName);
  const firm = { firm_name: firmName, slug: firmId, reg_number: regNumber, phone, data_residency_ke: residency };

  async function finish(res: Response) {
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not create your firm");
    if (!data.access_token) {
      // Created, but the automatic sign-in didn't happen: sign in normally.
      router.push(`/login?firm=${encodeURIComponent(data.tenant.slug)}`);
      return;
    }
    setSession(data.tenant.slug, data.access_token, data.refresh_token, data.user);
    router.push("/onboarding");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await finish(await fetch(`${API}/api/v1/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...firm, owner_name: ownerName, owner_email: email, owner_password: password }),
      }));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function googleSignup(credential: string) {
    setError("");
    if (!firmName.trim()) {
      setError("Enter your firm's name first, then continue with Google.");
      return;
    }
    setBusy(true);
    try {
      await finish(await fetch(`${API}/api/v1/signup/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...firm, credential }),
      }));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-paper lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <aside className="bg-navy px-6 py-8 text-white sm:px-10 lg:min-h-screen lg:py-12">
        <ProductMark light />
        <h1 className="mt-10 font-display text-3xl font-bold leading-tight sm:text-4xl">
          Set up your firm&apos;s workspace
        </h1>
        <p className="mt-3 max-w-md text-white/70">
          Files, clients, AI legal research over Kenyan law, drafting, meeting notes and billing — one
          secure workspace for your whole team.
        </p>
        <ol className="mt-10 hidden space-y-6 lg:block">
          {NEXT_STEPS.map(([title, body], i) => (
            <li key={title} className="flex gap-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-gold/60 font-semibold text-gold">
                {i + 1}
              </span>
              <div>
                <p className="font-semibold">{title}</p>
                <p className="text-sm text-white/60">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </aside>

      <section className="px-4 py-8 sm:px-10 lg:py-12">
        <form onSubmit={submit} className="mx-auto max-w-xl space-y-8">
          <fieldset className="space-y-4">
            <legend className="font-display text-xl font-bold text-navy">Your firm</legend>
            <div>
              <label className="label" htmlFor="firm">Firm name</label>
              <input id="firm" className="input" value={firmName} onChange={(e) => setFirmName(e.target.value)}
                placeholder="Mwangi & Co. Advocates" required autoComplete="organization" />
            </div>
            <div>
              <label className="label" htmlFor="slug">Firm ID</label>
              <input id="slug" className="input" value={firmId} required minLength={3} maxLength={40}
                onChange={(e) => { setSlugTouched(true); setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")); }}
                placeholder="mwangi-co-advocates" />
              <p className="mt-1 text-xs text-ink/50">Your team enters this to sign in. Lowercase letters, numbers and hyphens.</p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="reg">LSK / firm registration no. <span className="normal-case text-ink/40">(optional)</span></label>
                <input id="reg" className="input" value={regNumber} onChange={(e) => setRegNumber(e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="phone">Firm phone <span className="normal-case text-ink/40">(optional)</span></label>
                <input id="phone" className="input" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
                  placeholder="+254 7XX XXX XXX" autoComplete="tel" />
              </div>
            </div>
            <label className="flex items-start gap-2 text-sm text-ink/70">
              <input type="checkbox" className="mt-1" checked={residency} onChange={(e) => setResidency(e.target.checked)} />
              Our firm requires Kenya data residency (Data Protection Act, 2019)
            </label>
          </fieldset>

          <fieldset className="space-y-4">
            <legend className="font-display text-xl font-bold text-navy">Your account</legend>
            <p className="-mt-2 text-xs text-ink/50">You&apos;ll be the firm&apos;s Managing Partner and can add everyone else.</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="name">Full name</label>
                <input id="name" className="input" value={ownerName} onChange={(e) => setOwnerName(e.target.value)}
                  required autoComplete="name" />
              </div>
              <div>
                <label className="label" htmlFor="email">Work email</label>
                <input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@firm.co.ke" required autoComplete="email" />
              </div>
              <div>
                <label className="label" htmlFor="pw">Password</label>
                <input id="pw" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                  minLength={8} required autoComplete="new-password" placeholder="At least 8 characters" />
              </div>
              <div>
                <label className="label" htmlFor="pw2">Confirm password</label>
                <input id="pw2" className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                  minLength={8} required autoComplete="new-password" />
              </div>
            </div>
          </fieldset>

          {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{error}</p>}
          <div className="space-y-4">
            <button className="btn-gold w-full !py-3 text-base" disabled={busy}>
              {busy ? "Creating your firm…" : "Create firm account"}
            </button>
            <div className="flex items-center gap-3 text-xs text-ink/40">
              <span className="h-px flex-1 bg-ink/10" /> or sign up with Google <span className="h-px flex-1 bg-ink/10" />
            </div>
            <GoogleButton text="signup_with" onCredential={googleSignup} />
            <p className="text-center text-sm text-ink/60">
              Already have an account? <Link href="/login" className="font-semibold text-navy hover:underline">Sign in</Link>
            </p>
          </div>
        </form>
      </section>
    </main>
  );
}
