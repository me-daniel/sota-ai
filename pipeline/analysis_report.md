# Aggregation method tests

Data: obs_test2 · 393 base models with any of ['aa432', 'epoch', 'vals', 'lmarena', 'agent']; test set = 63 models with ≥3 of them (top effort per model; collisions excluded).

Methods: **zmean** weighted mean of z-scores (sheet v6) · **pct** mean percentile rank · **shrink** zmean with a 1-source prior toward 50 · **linked** zmean after linking each source to a common scale · **factor** one-factor model, EM with missing data (linking + reliability weighting).

## Data-driven reliability (one-factor fit on the test set)

| source | n | loading | noise ψ | reliability λ²/(λ²+ψ) |
|---|---|---|---|---|
| aa432 | 46 | 0.88 | 0.06 | 0.93 |
| epoch | 50 | 0.92 | 0.08 | 0.92 |
| vals | 27 | 1.40 | 0.05 | 0.97 |
| lmarena | 56 | 0.79 | 0.32 | 0.66 |
| agent | 52 | 1.26 | 0.06 | 0.96 |

Pairwise Spearman (all models with both):

| | aa432 | epoch | vals | lmarena | agent |
|---|---|---|---|---|---|
| aa432 | 1.00 | 0.96 | 0.94 | 0.83 | 0.94 |
| epoch | 0.96 | 1.00 | 0.82 | 0.86 | 0.87 |
| vals | 0.94 | 0.82 | 1.00 | 0.75 | 0.92 |
| lmarena | 0.83 | 0.86 | 0.75 | 1.00 | 0.69 |
| agent | 0.94 | 0.87 | 0.92 | 0.69 | 1.00 |

## 1 Leave-one-source-out validity (Spearman, composite of the other sources vs the left-out one)

| left out | n | zmean | pct | shrink | linked | factor |
|---|---|---|---|---|---|---|
| aa432 | 46 | 0.90 | 0.90 | 0.90 | 0.92 | 0.95 |
| epoch | 50 | 0.92 | 0.91 | 0.92 | 0.92 | 0.91 |
| vals | 27 | 0.92 | 0.92 | 0.92 | 0.92 | 0.93 |
| lmarena | 56 | 0.76 | 0.77 | 0.76 | 0.75 | 0.75 |
| agent | 52 | 0.89 | 0.87 | 0.88 | 0.88 | 0.92 |
| **mean** | | 0.88 | 0.87 | 0.88 | 0.88 | 0.89 |

## 2 Masking robustness (hide 30 % of known values, 200 runs)

| method | Spearman vs full | top-10 kept |
|---|---|---|
| zmean | 0.970 | 8.9/10 |
| pct | 0.967 | 8.8/10 |
| shrink | 0.971 | 8.7/10 |
| linked | 0.979 | 9.1/10 |
| factor | 0.981 | 8.9/10 |

## 3 Forward test: predicting AA Index v5 from pre-v5 information

Target: 38 models with a v5 score (19 open-weights; open-weights average -22.9 v5 points vs proprietary). RMSE after leave-one-out quadratic calibration, in v5 points. Gap = mean residual open − proprietary (negative = predictor rates open-weights models higher than v5 does). Excess = gap beyond what the predictor's noise alone would leave; 90 % bootstrap.

| predictor | n (open) | Spearman | LOO RMSE | gap | excess [90 % CI] |
|---|---|---|---|---|---|
| AA v4.3.2 index | 37 (19) | 0.97 | 4.04 | -2.2 | -0.8 [-2.7, 1.1] |
| AA Progress Index | 37 (19) | 0.99 | 5.57 | -2.4 | 0.4 [-1.3, 2.2] |
| independent · zmean | 33 (14) | 0.90 | 6.35 | -2.2 | 1.5 [-2.3, 5.1] |
| all pre-v5 · zmean | 34 (15) | 0.94 | 5.27 | -1.6 | 1.0 [-1.8, 3.8] |
| independent · pct | 33 (14) | 0.90 | 6.57 | -2.9 | 1.1 [-2.6, 4.7] |
| all pre-v5 · pct | 34 (15) | 0.93 | 5.46 | -2.0 | 0.7 [-2.1, 3.5] |
| independent · shrink | 33 (14) | 0.91 | 6.64 | -2.5 | 1.6 [-2.0, 5.2] |
| all pre-v5 · shrink | 34 (15) | 0.93 | 5.70 | -1.7 | 1.3 [-1.7, 4.3] |
| independent · linked | 33 (14) | 0.93 | 4.72 | -2.5 | -0.4 [-2.6, 1.7] |
| all pre-v5 · linked | 34 (15) | 0.96 | 4.05 | -2.2 | -0.7 [-2.5, 1.1] |
| independent · factor | 33 (14) | 0.97 | 3.86 | -2.2 | -0.8 [-2.7, 1.4] |
| all pre-v5 · factor | 34 (15) | 0.97 | 3.54 | -2.2 | -1.1 [-2.8, 0.7] |

## 4 Open-weights gap per legacy public AA benchmark (v4.3.2 capture) vs v5

Same measure per benchmark. Benchmarks that are part of v5 are marked; they share items with the target, so their gap is biased toward 0.

| benchmark | n (open) | Spearman with v5 | gap | excess [90 % CI] |
|---|---|---|---|---|
| gdpval-aa-normalized | 37 (19) | 0.87 | -9.0 | -2.5 [-4.9, -0.3] |
| critpt (in v5) | 37 (19) | 0.92 | -5.3 | -2.1 [-4.8, 0.5] |
| humanitys-last-exam (in v5) | 37 (19) | 0.92 | -4.7 | -1.5 [-4.1, 1.3] |
| aa-briefcase (in v5) | 37 (19) | 0.89 | -7.1 | -1.5 [-4.3, 1.3] |
| scicode | 37 (19) | 0.83 | -8.3 | -0.8 [-3.6, 2.2] |
| automationbench-aa (in v5) | 37 (19) | 0.84 | -7.7 | -0.0 [-3.8, 4.4] |
| artificial-analysis-long-context-reasoning | 37 (19) | 0.55 | -18.6 | -0.0 [-2.2, 2.3] |
| terminalbench-4-0 (in v5) | 37 (19) | 0.95 | -2.6 | 0.0 [-2.8, 3.2] |
| frontiercode (in v5) | 35 (18) | 0.87 | -6.1 | 0.2 [-3.1, 3.5] |
| code2video-aa | 22 (9) | 0.89 | -2.8 | 1.0 [-3.3, 5.6] |
| mlcr-aa | 32 (16) | 0.77 | -8.1 | 1.0 [-2.6, 5.3] |
| omniscience-non-hallucination (in v5) | 37 (19) | 0.05 | -22.5 | 1.5 [-1.3, 4.9] |
| terminal-bench-science (in v5) | 36 (18) | 0.97 | -1.3 | 1.6 [-0.9, 4.1] |
| omniscience-accuracy (in v5) | 37 (19) | 0.78 | -6.1 | 2.7 [-2.0, 7.7] |
| gdp-pdf (in v5) | 37 (19) | 0.87 | 0.4 | 5.6 [1.7, 9.5] |
| mmmu-pro | 22 (10) | 0.81 | -2.0 | 6.3 [-1.9, 15.6] |
| aa-analyst-agent | 20 (8) | 0.87 | -2.5 | 7.1 [-0.4, 15.4] |

## 5 Weight sensitivity and uncertainty (test set)

| model | zmean | rank band 5–95 % (weights ±30 %) | factor score ± 90 % | sources |
|---|---|---|---|---|
| Claude Opus 5.5 | 74.2 | 1–1 | 74.5 ± 2.6 | 5 |
| Gemini 4 Carbon | 71.7 | 2–2 | 72.2 ± 3.1 | 3 |
| Claude Fable 5.1 | 69.3 | 3–4 | 70.5 ± 3.4 | 4 |
| Gemini 4 Argon | 68.6 | 3–5 | 68.9 ± 2.6 | 5 |
| Claude Sonnet 5.5 | 68.4 | 4–5 | 70.9 ± 2.6 | 5 |
| Muse Wonder Full | 66.7 | 6–8 | 67.8 ± 2.8 | 3 |
| GPT-6 Astra | 66.0 | 6–8 | 68.3 ± 2.6 | 5 |
| Claude Fable 5 | 65.8 | 6–9 | 65.1 ± 4.0 | 3 |
| GPT-6.1 Sol | 65.5 | 7–9 | 67.5 ± 2.6 | 5 |
| Claude Opus 5 | 63.7 | 10–11 | 64.5 ± 4.0 | 3 |
| Kimi K3.1 Pro | 63.0 | 10–13 | 64.4 ± 2.8 | 3 |
| Muse Wonder | 62.6 | 11–13 | 63.8 ± 2.6 | 5 |
| GPT-6.1 Terra | 61.8 | 11–15 | 63.8 ± 2.8 | 3 |
| GPT-5.6 Sol | 61.0 | 13–15 | 61.1 ± 4.0 | 3 |
| GPT-6 Sol | 60.5 | 13–15 | 63.6 ± 4.0 | 3 |
