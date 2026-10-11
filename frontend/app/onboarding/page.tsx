"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import ProductMark from "@/components/ProductMark";
import RolesManager, { type Role } from "@/components/RolesManager";
import AddMemberForm from "@/components/AddMemberForm";

const STEPS = ["Firm details", "Roles & permissions", "Your team", "Done"];

// Post-signup setup for the firm owner. Every step can be revisited later in
// Settings; finishing (or skipping) stops this page opening on sign-in.
export default function OnboardingPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [authed, setAuthed] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!localStorage.getItem("wakili_access")) router.replace("/login");
    else setAuthed(true);
  }, [router]);

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api("/api/v1/auth/me"), enabled: authed });
  const perms: string[] = me?.permissions || [];
  const allowed = perms.includes("firm_settings.edit");
  const { data: rolesData } = useQuery({ queryKey: ["roles"], queryFn: () => api("/api/v1/roles"), enabled: allowed });
  const { data: usersData } = useQuery({ queryKey: ["users"], queryFn: () => api("/api/v1/users"), enabled: allowed });
  const roles: Role[] = rolesData?.roles || [];

  useEffect(() => {
    if (me && !allowed) router.replace("/dashboard"); // only the firm's administrators set it up
  }, [me, allowed, router]);

  const complete = useMutation({
    mutationFn: () => api("/api/v1/firm/onboarding/complete", { method: "POST" }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["me"] });
      router.push("/dashboard");
    },
  });

  if (!me || !allowed) return null;
  const tenant = me.tenant;
  const team = (usersData?.users || []).filter((u: any) => u.role !== "client");

  return (
    <main className="min-h-screen bg-paper">
      <header className="border-b border-navy/10 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <ProductMark href="/dashboard" />
          <button className="text-sm text-ink/60 hover:text-navy hover:underline" disabled={complete.isPending}
            onClick={() => complete.mutate()}>
            Skip setup for now
          </button>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <p className="text-sm text-ink/60">Setting up</p>
        <h1 className="font-display text-3xl font-bold text-navy">{tenant.name}</h1>

        <ol className="mt-6 grid grid-cols-4 gap-2" aria-label="Setup progress">
          {STEPS.map((label, i) => (
            <li key={label}>
              <button className="w-full text-left" onClick={() => setStep(i)} aria-current={i === step ? "step" : undefined}>
                <span className={`block h-1.5 rounded-full ${i <= step ? "bg-gold" : "bg-navy/10"}`} />
                <span className={`mt-2 hidden text-xs font-semibold sm:block ${i === step ? "text-navy" : "text-ink/50"}`}>
                  {i + 1}. {label}
                </span>
              </button>
            </li>
          ))}
        </ol>
        <p className="mt-2 text-xs font-semibold text-navy sm:hidden">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>

        <section className="mt-8">
          {step === 0 && <FirmStep tenant={tenant} onNext={() => setStep(1)} />}

          {step === 1 && (
            <div className="space-y-4">
              <StepIntro title="Who can do what">
                Each person has one role, and a role is a set of permissions — for example, whether they can see
                every file or only their own, run AI research, manage clients, take payments or add staff. We&apos;ve
                created the usual Kenyan firm designations to start from; edit them, delete ones you don&apos;t use, or
                add your own. Your Managing Partner role always keeps full access.
              </StepIntro>
              <RolesManager roles={roles} embedded />
              <StepNav onBack={() => setStep(0)} onNext={() => setStep(2)} />
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <StepIntro title="Add your team">
                Give each person a role. They&apos;re emailed a temporary password and asked to choose their own the
                first time they sign in. You can add more people any time from Settings.
              </StepIntro>
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <div className="card"><AddMemberForm roles={roles} /></div>
                <div className="card">
                  <p className="label">Team so far ({team.length})</p>
                  <ul className="divide-y divide-navy/5 text-sm">
                    {team.map((u: any) => (
                      <li key={u.id} className="flex items-center justify-between gap-2 py-2">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{u.full_name}</span>
                          <span className="block truncate text-xs text-ink/50">{u.email}</span>
                        </span>
                        <span className="shrink-0 rounded bg-navy/5 px-2 py-0.5 text-xs text-navy">{u.role}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <StepNav onBack={() => setStep(1)} onNext={() => setStep(3)} />
            </div>
          )}

          {step === 3 && (
            <div className="card max-w-2xl space-y-4">
              <h2 className="font-display text-2xl font-bold text-navy">You&apos;re ready</h2>
              <p className="text-sm text-ink/70">
                {tenant.name} has {roles.length} roles and {team.length} member{team.length === 1 ? "" : "s"}. Your team signs in
                with the Firm ID <code className="rounded bg-navy/5 px-1.5 py-0.5 font-mono text-navy">{tenant.slug}</code>.
              </p>
              <ul className="list-disc space-y-1 pl-5 text-sm text-ink/70">
                <li>Open a file and add your first client under <b>Files</b> and <b>Clients</b>.</li>
                <li>Ask a question of Kenyan law under <b>AI Research</b>.</li>
                <li>Record a client meeting under <b>Recordings</b> to get a speaker-labelled transcript and agreed action points.</li>
              </ul>
              {complete.isError && <p className="text-sm text-red-600">{(complete.error as Error).message}</p>}
              <button className="btn-gold" disabled={complete.isPending} onClick={() => complete.mutate()}>
                {complete.isPending ? "Finishing…" : "Go to dashboard"}
              </button>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function StepIntro({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="max-w-3xl">
      <h2 className="font-display text-2xl font-bold text-navy">{title}</h2>
      <p className="mt-1 text-sm text-ink/70">{children}</p>
    </div>
  );
}

function StepNav({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  return (
    <div className="flex justify-between gap-3 pt-2">
      <button className="btn-outline" onClick={onBack}>Back</button>
      <button className="btn-gold" onClick={onNext}>Continue</button>
    </div>
  );
}

function FirmStep({ tenant, onNext }: { tenant: any; onNext: () => void }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (body: Record<string, string>) => api("/api/v1/firm", { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); onNext(); },
  });
  return (
    <form className="card max-w-2xl space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        save.mutate({ name: String(fd.get("name")), reg_number: String(fd.get("reg_number")), phone: String(fd.get("phone")) });
      }}>
      <StepIntro title="Confirm your firm's details">These appear across your workspace.</StepIntro>
      <div>
        <label className="label" htmlFor="ob-name">Firm name</label>
        <input id="ob-name" name="name" className="input" defaultValue={tenant.name} required />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="ob-reg">LSK / registration no.</label>
          <input id="ob-reg" name="reg_number" className="input" defaultValue={tenant.reg_number} />
        </div>
        <div>
          <label className="label" htmlFor="ob-phone">Firm phone</label>
          <input id="ob-phone" name="phone" type="tel" className="input" defaultValue={tenant.phone} />
        </div>
      </div>
      <p className="text-xs text-ink/50">Firm ID (used to sign in): <code className="font-mono text-navy">{tenant.slug}</code></p>
      {save.isError && <p className="text-sm text-red-600">{(save.error as Error).message}</p>}
      <div className="flex justify-end">
        <button className="btn-gold" disabled={save.isPending}>{save.isPending ? "Saving…" : "Continue"}</button>
      </div>
    </form>
  );
}
