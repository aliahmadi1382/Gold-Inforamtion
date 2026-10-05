# Macro relationships to investigate

Research gold jointly with USD, real yields, inflation and policy expectations, while treating sensitivities as regime-dependent hypotheses. Nominal yields minus realized CPI are not equivalent to market-implied real yields. Breakevens include liquidity/risk premia and are not pure expected inflation. A policy-rate observation is not a futures-implied policy probability.

The macro shortlist covers USD exchange rates, a broad trade-weighted dollar index, nominal and TIPS yields, inflation, employment, wages, claims, openings, GDP and retail sales. `DTWEXBGS` is **not ICE DXY**; `PAYEMS` is a payroll level, not the monthly payroll surprise; `GDPC1` is a real output level, not a percentage growth rate. Seasonal adjustment and annualization belong to the unit definitions. ISM/PMI, consumer-confidence and DXY acquisition require separately reviewed sources.

Use changes/returns or economically justified transformations, align actual release times, keep first-release and revised data separate, and distinguish levels from differences. Compare rolling relationships with sample counts and uncertainty, missing-data rules and multiple-testing controls. Never infer a causal gold recommendation from a single correlation. This release imports numeric context and reports ages; a cross-asset statistical model is future work.

## Implemented core history

Release 0.4 acquires DFF, DGS10, DFII10, T10YIE, DTWEXBGS, CPIAUCSL and UNRATE from their earliest returned periods, after checking native units, frequency and seasonal adjustment. `config/macro_core.yaml` defines that subset; the broader shortlist is not a claim that all 22 series were acquired. `gold macro-context` selects eligible periods and revisions at an explicit cutoff and exposes missing or stale values. It produces neither a causal explanation nor a trading signal. The current histories and vintage example lack independently verified release clocks, so historical joins remain retrieval-time bounded. See the [phase-3 findings](../source-methodology/history-acquisition.fa.md) and [Persian education](../education/05-history-macro-and-revisions.fa.md).
