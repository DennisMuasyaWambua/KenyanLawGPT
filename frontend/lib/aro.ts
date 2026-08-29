// Advocates Remuneration Order, 2014 (Kenya) — advocate fee scales.
//
// ⚠️ VERIFY BEFORE USE: these bracket figures are a representative encoding of
// the ARO 2014 scales for auto-suggesting fees. Confirm against the current
// gazette and edit the brackets/minimums below to match your firm's reading.
// Fees are computed marginally (progressively) across the brackets.

export type Bracket = { upTo: number | null; rate: number };
export type Scale = {
  key: string;
  name: string;
  note: string;
  minFee: number;
  brackets: Bracket[];
};

export const ARO_SCALES: Scale[] = [
  {
    key: "sale",
    name: "Sale / Conveyancing (Schedule I)",
    note: "On the consideration or value of the property (sale, purchase or transfer).",
    minFee: 35_000,
    brackets: [
      { upTo: 1_000_000, rate: 0.015 },
      { upTo: 5_000_000, rate: 0.0125 },
      { upTo: 20_000_000, rate: 0.01 },
      { upTo: null, rate: 0.0075 },
    ],
  },
  {
    key: "charge",
    name: "Charge / Mortgage (Schedule I)",
    note: "On the amount secured by the charge or mortgage.",
    minFee: 35_000,
    brackets: [
      { upTo: 1_000_000, rate: 0.015 },
      { upTo: 5_000_000, rate: 0.0125 },
      { upTo: 20_000_000, rate: 0.01 },
      { upTo: null, rate: 0.0075 },
    ],
  },
  {
    key: "court",
    name: "Court instruction fee (Schedule VI — higher courts)",
    note: "Instruction fee to sue or defend, on the value of the subject matter.",
    minFee: 45_000,
    brackets: [
      { upTo: 1_000_000, rate: 0.03 },
      { upTo: 5_000_000, rate: 0.02 },
      { upTo: 20_000_000, rate: 0.015 },
      { upTo: null, rate: 0.01 },
    ],
  },
];

export type QuoteLine = { label: string; portion: number; rate: number; amount: number };
export type Quote = { fee: number; minApplied: boolean; lines: QuoteLine[]; scale: Scale };

const fmt = (n: number) => n.toLocaleString("en-KE");

// aroQuote computes the ARO fee for a subject value under the given scale,
// returning the marginal breakdown. Returns null for invalid input.
export function aroQuote(scaleKey: string, value: number): Quote | null {
  const scale = ARO_SCALES.find((s) => s.key === scaleKey);
  if (!scale || !(value > 0)) return null;
  let prev = 0;
  let fee = 0;
  const lines: QuoteLine[] = [];
  for (const b of scale.brackets) {
    const cap = b.upTo ?? Infinity;
    const span = Math.max(0, Math.min(value, cap) - prev);
    if (span > 0) {
      const amount = span * b.rate;
      fee += amount;
      lines.push({
        label: `${fmt(prev)} – ${b.upTo ? fmt(b.upTo) : "above"}`,
        portion: span,
        rate: b.rate,
        amount,
      });
    }
    prev = cap;
    if (value <= cap) break;
  }
  const minApplied = fee < scale.minFee;
  if (minApplied) fee = scale.minFee;
  return { fee: Math.round(fee), minApplied, lines, scale };
}
