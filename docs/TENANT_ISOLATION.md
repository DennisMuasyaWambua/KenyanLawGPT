# How Advocatus keeps your firm's data yours

*A plain-language summary for managing partners. No technical background needed.*

Advocatus runs many law firms on one shared platform, the way a well-run chambers
building houses many practices under one roof — shared library downstairs,
locked private offices upstairs. This note explains, without jargon, why another
firm on the platform **cannot** see your pleadings, submissions, client notes,
or matter history — and how we prove it continuously rather than just promising
it.

## What is shared, and what is never shared

- **Shared (public):** Kenyan law itself — Acts, the Constitution, decided
  cases, gazette notices. This is public record. Every firm reads the same
  library, and that is the point.
- **Private (yours only):** everything your firm uploads or creates — documents,
  submissions, the advocates and matters they belong to, outcomes, and your
  firm's "what has worked before this judge" history. None of this is ever
  visible to another firm.

## Four independent locks (defence in depth)

We do not rely on a single safeguard. A leak would require **all** of these to
fail at once:

1. **Separate storage per firm.** Each firm's records live in their own
   partition of the database — a distinct namespace, not co-mingled rows. This
   mirrors how the rest of the platform already separates firms.

2. **One, and only one, code path can read private data.** Every query for
   private information is built by a single, audited component that *always*
   stamps it with your firm's identity. There is no way to hand-write a query
   that "forgets" the filter — the system rejects any query not produced by that
   component. So there is exactly one place to secure, not hundreds.

3. **Your identity comes from your secure login, never from the request.** Which
   firm you are is determined by your authenticated, certificate-secured session
   on our servers — not by anything the app or a browser sends. A tampered or
   buggy client cannot ask for another firm's data by supplying a different id;
   the server cross-checks and refuses on any mismatch.

4. **Connections into the public library are one-way.** Your private submission
   can point *out* to a public Act it cites, but nothing can travel back down
   that link into another firm's private records. Even multi-step "reasoning"
   across the knowledge graph is fenced so it can pass through shared public law
   but never cross into another firm's partition.

## The judge-insight feature, specifically

Advocatus can summarise *"in this firm's past matters before Judge X, submissions
citing Section Y succeeded in M of N cases."* That history is computed **only
from your firm's own records** and the public case record. Another firm asking
about the very same judge sees only *their* own history — never yours. The
feature is also clearly labelled in the interface as your firm's internal
experience, **not settled law**.

## We test the locks on every single change

This is the part most vendors cannot show you. Every time an engineer changes
the software, an automated test suite runs that **deliberately tries to break
in** — it sets up two fictional firms with secret marker data and attempts to
read one firm's documents, graph, and judge-history while logged in as the
other, through every avenue the product exposes. If even one byte leaks, the
change is blocked from shipping. These tests are a release gate, not a one-time
audit.

## Right to be forgotten (Kenya Data Protection Act)

When a client exercises their right to erasure, we cascade the deletion across
both the document store and the knowledge graph for that data subject — and the
same test suite confirms one firm's erasure never touches another firm's data.

## In one sentence

Your firm's confidential work is stored separately, reachable only through a
single identity-stamped code path keyed to your secure login, fenced off from
every other firm even during multi-step reasoning, and that separation is
re-proven automatically on every change we ship.
