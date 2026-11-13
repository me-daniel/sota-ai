# Rating concept v7: method tests and design (2026-10-29)

These are the test results that drive the next version of our task ratings (v7 after v6.xlsx). Code: `pipeline/` (retrieval, normalizer, scoring, analysis). Full numbers: `pipeline/analysis_report.md`.

## What the tests showed

How the tests were run:
- `analysis.py` on the 28–29 Oct envelopes.
- Test set: 63 models with at least 3 of 5 sources: AA index v4.3.2, Epoch ECI, Vals Index, LMArena creative-writing Elo, Agent Arena work.
- Forward test: predict AA Index v5 (about 60% private, launched 2026-10-28) for the 33–37 models scored there, using only pre-v5 data.

| method | LOSO ρ (mean) | masking ρ / top-10 kept | v5 forward RMSE, all pre-v5 | v5 forward RMSE, independent only |
|---|---|---|---|---|
| zmean (sheet v6) | 0.88 | 0.970 / 8.9 | 5.3 | 6.4 |
| percentile | 0.87 | 0.967 / 8.8 | 5.5 | 6.6 |
| shrink to mean | 0.88 | 0.971 / 8.7 | 5.7 | 6.6 |
| **linked z** | 0.88 | 0.979 / 9.1 | 4.1 | 4.7 |
| **factor model** | 0.89 | 0.981 / 8.9 | **3.5** | **3.9** |
| AA v4.3.2 alone | – | – | 4.0 | – |

1. **v6 has a coverage bias.** Plain z-scores are computed within each source's own model set. Vals and Agent Arena mostly cover frontier models, so they score an average frontier model as "average" and pull it down. Linking every source to one common scale fixes most of it (RMSE 5.3 → 4.1). The factor model adds reliability weighting (→ 3.5).
2. **AA can be replaced.** Without any AA data, the independent sources (Epoch, Vals, LMArena, Agent Arena) predict v5 about as well as AA's own v4.3.2 did: RMSE 3.9 vs 4.0, Spearman 0.97 for both. So a cap on any one organisation's weight costs no accuracy.
3. **No open-weights bias found (correction).** Every predictor, Progress Index included, rates open-weights models 2–3 v5 points higher than v5 does. Most of that is regression to the mean:
   - Open models average 23 points lower on v5, so any imperfect predictor overrates the lower group.
   - Beyond that noise effect the gap is about 0 (from −1.1 to +1.6; every 90% CI includes 0).
   - Per legacy benchmark, only GDPval-AA (dropped from v5) shows a small excess: −2.5 [−4.9, −0.2].
   - Not testable: GPQA, LiveCodeBench, AIME, IFBench and τ². None of the 38 v5 models were run on them.
4. **Data-driven reliability for the general factor:** Vals 0.97, Agent Arena 0.96, AA 0.93, Epoch 0.92, LMArena creative writing 0.66. LMArena measures a different trait (style and preference). Whether that belongs in a category is a relevance decision, not a reliability one. LMArena stays in Writing.
5. **Uncertainty.** Under ±30% weight changes, ranks 1–5 stay fixed and ranks 6–15 move by 2–5 places. Factor-model 90% bands are ±2.6 to ±4.0 points. Treat models within about 3 points as tied, and show bands.

## Design

**1. Retrieval** (`extractors.js` → `normalize.py`)
- Dated, append-only `observations.csv`. The model registry comes from AA trends; `aliases.json` holds manual name fixes.
- Refresh weekly and on major releases. Back-fill missed dates from Wayback.
- Review `matches_guessed.csv` and `unmatched.csv` on every refresh.

**2. Scoring engine** (Python; the workbook becomes output only)
- Rows are model × effort, as in v6.
- **Relevance weights** `r_j` per category and source. These are our construct choice, set by hand and capped per organisation.
- **Reliability** `λ_j, ψ_j` per source. Re-estimated from the data at every refresh by a one-factor EM fit with missing data, per category.
- **Score** = relevance-weighted factor posterior:
  - m = Σ r λ (z − μ)/ψ / (1 + Σ r λ²/ψ)
  - 90% band = ±1.645 · 15/√(1 + Σ r λ²/ψ)
  - Missing sources widen the band and pull the score toward the mean. This replaces v6's ad-hoc confidence and coverage factors.
- **Fallback.** Fewer than about 25 models with ≥ 3 sources in a category → linked z with fixed weights.
- **One AA column.** v5 if present, else v4.3.2 linked to the v5 scale (forward RMSE 4.0), else Progress (5.6, quadratic calibration). Flag the fallbacks as "AA est.". AA's index, Progress and Personality share errors, so they are never separate factor indicators.
- **Organisation cap** ≤ 40% of a category's relevance mass. Today Arena holds 74% of Writing and AA 39% of Reasoning.
- **Efforts.** Keep v6's carry rule (z_carried = z_measured + shift · slope · ΔAA). Carried values get lower precision (ψ / 0.8) instead of weight 0.8.
- **Kept from v6:** slop length adjustment, IF, personality in Writing, the ★ value frontier (score vs cost per task) and the speed column.

**3. Presentation.**
- The workbook is generated from the engine with no heavy formulas.
- Per row: score, ± band, rank band, coverage, "AA est." flag and match flags.
- A bias-check sheet shows residuals by organisation and open-weights status per source. Helper sheets are hidden.

**4. Checks on every refresh** (`analysis.py`). Investigate before publishing if:
- mean LOSO ρ falls by more than 0.05;
- any source's reliability drops below 0.5;
- a 2026 model is unmatched;
- an excess-gap CI excludes 0;
- a model's rank band widens by more than 3.

## Decided 2026-11-13 (implemented in `rate.py`)
- **Tiers:** top-sota (top 10, any licence), closed-budget, and large / mid / small / little / tiny-oss by total parameters (> 150B / 40–150B / 15–40B / 4.5–15B / < 4.5B). little-oss was added the same day.
- **AA source:** one AA column with linked fallbacks (v4.3.2 linear → v5; Progress → v4.3.2 → v5, kept monotone).
- **Organisation cap:** 40%, or 1/n_orgs when a category has too few organisations to meet it.
- **Where the maths lives:** Python. The workbook is output only.
- **Rows:** one per base model at its top measured effort. The effort carry rule is not implemented yet.
- **Category fits:** no category has 25 models with ≥ 3 of its sources yet (20–22), so all of them borrow λ, ψ from the general fit.

## Open decisions for v7 (original list)
- **AA source:** one AA column with linked fallback (recommended above), or the earlier 70/30 v5 + Progress mix.
- **Local-model size cutoff:** ≤ 40B, ≤ 130B, or all open-weights.
- **★ cost basis:** v5 cost, else v4.3.2 cost × 2.0.
- **Organisation cap:** 40%?
- **Where the maths lives:** compute v7 in Python (recommended), or keep the formulas in Excel.
