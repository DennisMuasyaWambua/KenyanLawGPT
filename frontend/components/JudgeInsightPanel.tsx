// Judge-insight panel (Task 7). Design reference: Plausible Analytics insight
// callout (gummble sc_0f7a32d851df4ece95db2f57b682249f) + the dashboard/KPI
// pattern family — a highlighted panel deliberately set apart from the main
// content. Here that separation is load-bearing: firm-internal historical
// pattern must NEVER read as settled law, so this uses a gold-tinted, left-
// bordered treatment distinct from the white citation cards and answer card,
// with an explicit "Not settled law" label and disclaimer.

export type JudgePattern = {
  judge_name: string;
  tenant_cases: number;
  tenant_favorable: number;
  winning_authorities: [string, number][];
  public?: {
    rulings_count?: number;
    favored_plaintiff?: number;
    favored_defendant?: number;
  } | null;
};

export default function JudgeInsightPanel({ pattern }: { pattern: JudgePattern }) {
  const hasTenant = pattern.tenant_cases > 0;
  const rulings = pattern.public?.rulings_count ?? 0;
  if (!hasTenant && !rulings) return null;

  return (
    <section
      aria-label="Firm-internal historical pattern"
      className="rounded-lg border border-gold/40 border-l-4 border-l-gold bg-gold/5 p-5"
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-gold px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-navy">
          ◑ Firm experience
        </span>
        <span className="text-[10px] font-bold uppercase tracking-wide text-gold-dim">
          Not settled law
        </span>
      </div>

      <h3 className="font-display text-lg font-bold text-navy">
        In this firm&rsquo;s experience before {pattern.judge_name}
      </h3>

      {hasTenant && (
        <p className="mt-2 text-sm text-ink/80">
          <span className="font-bold text-navy">{pattern.tenant_favorable}</span> of{" "}
          <span className="font-bold text-navy">{pattern.tenant_cases}</span> prior
          file{pattern.tenant_cases === 1 ? "" : "s"} before this judge had a favourable outcome.
        </p>
      )}

      {pattern.winning_authorities.length > 0 && (
        <div className="mt-3">
          <p className="label">Authorities most cited in favourable submissions</p>
          <div className="flex flex-wrap gap-2">
            {pattern.winning_authorities.map(([title, count]) => (
              <span
                key={title}
                className="rounded-full bg-navy/10 px-2 py-1 text-xs font-medium text-navy"
              >
                {title} <span className="text-navy/50">· {count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {rulings > 0 && (
        <p className="mt-3 text-xs text-ink/60">
          Public record: {rulings} ruling{rulings === 1 ? "" : "s"} attributed to this judge
          {" ("}
          {pattern.public?.favored_plaintiff ?? 0} favoured the plaintiff/petitioner,{" "}
          {pattern.public?.favored_defendant ?? 0} the defendant/respondent{")"}.
        </p>
      )}

      <p className="mt-4 border-t border-gold/30 pt-3 text-[11px] italic leading-relaxed text-ink/50">
        Firm-internal historical pattern — this summarises your firm&rsquo;s own prior files and
        public case records before this judge. It is <span className="font-semibold">not settled
        law</span> and not a prediction of how the judge will rule. Judicial-analytics use should be
        reviewed against Law Society of Kenya / Judiciary of Kenya guidance before any
        external-facing use.
      </p>
    </section>
  );
}
