# Authority ranks

The retrieval reranker uses `authority_rank` as a tier-break signal. Higher
= more authoritative when two sources address the same point.

| `source` | `source_subcorpus` | `authority` | `authority_rank` |
|----------|--------------------|-------------|------------------|
| finlex   | laki, laki_skk     | Finlex      | 100              |
| finlex   | asetus, asetus_skk | Finlex      | 100              |
| finlex   | treaty             | Treaty      | 90               |
| finlex   | kho                | KHO         | 80               |
| vero     | vero_*             | Vero        | 60               |

Rationale:

- **Finlex statute = 100** — primary legislation, binding.
- **Treaty = 90** — international tax treaties (Tuloverosopimukset) have
  direct legal force but cover only a narrow set of cross-border situations,
  so they rank just below domestic statute. Where they do apply they
  override domestic statute, but the typical query is broader than that.
- **KHO = 80** — Supreme Administrative Court precedent is binding on
  similar fact patterns but *interprets* statute; it does not enact it.
  Placed above Vero because it is the highest court of administrative law.
- **Vero = 60** — Verohallinto guidance interprets statute as well, but is
  not binding on courts and can be challenged.

Sign-off on the 20-query hand sample (V3.2) is a follow-up. The numeric
gaps are large (≥10) so any individual rank can move without colliding
with a neighbor.
