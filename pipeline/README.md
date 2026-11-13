# model-ratings-pipeline

Collects leaderboard scores into one dated history, matches model names across sources, and tests and computes our own task ratings. Version 1.0, 2026-10-29.

```
browser page ──extractors.js──▶ envelope.json ──normalize.py──▶ observations.csv (append-only history)
                                                                 registry.csv · unmatched.csv · matches_guessed.csv
observations.csv ──scoring.py / analysis.py──▶ composite scores, method tests ──▶ rating workbook (vN.xlsx)
observations.csv + registry.csv + tracked.csv + rating_config.json ──rate.py──▶ ratings/v7/ (workbook, CSV, TRACKED.md)
```

| file | what it does |
|---|---|
| `extractors.js` | One browser snippet for every supported page. It reads data the page already loaded and returns a standard JSON envelope. |
| `normalize.py` | `python3 -I normalize.py RAW_DIR OUT_DIR`. Envelopes → long observations table; matches names to the AA registry. |
| `gdpx_fetch.py` | `python3 -I gdpx_fetch.py OUT_DIR [--raw RAW_DIR]`. Fetches SemiAnalysis GDPx straight from the shell and writes envelopes in the same format. |
| `import_legacy.py` | `uv run python -I import_legacy.py OUT_DIR`. Turns the AA archive workbook and the v6 Raw Data sheet into standard envelopes (same source ids and metrics as the extractors). |
| `web_sources.py` | `python3 -I web_sources.py OUT_DIR [--raw RAW_DIR] [--only id,…]`. Shell fetchers for Terminal-Bench, Scale SEAL, Mercor APEX, WeirdML, MathArena, Lech Mazur writing and SimpleBench. |
| `rate.py` | `uv run python -I rate.py OBS_DIR OUT_DIR`. Rating v7: factor model with ± bands, org cap, six tiers, tracked set. Writes `model_ratings_v7.xlsx`, `ratings_v7.csv`, `TRACKED.md`. |
| `rating_config.json` | Sources, relevance weights per category, org cap, tier rules, how many models each tier shows. |
| `tracked.csv` | Bookkeeping by hand: pins (`track`), `watch` models without data yet, `drop`, and overrides (tier, open weights, params, release date) with a note, an evidence URL and the date checked. A `track` row for a model AA doesn't list creates a registry entry; `aka` (separated by `;`) lists other names sources use for it. |
| `aliases.json` | Manual name fixes: `"source name (without effort)": "AA base name"`. |
| `scoring.py` | Builds the model × source matrix. Methods: `zmean`, `pct`, `shrink`, `linked`, `factor`. |
| `analysis.py` | `python3 -I analysis.py OUT_DIR report.md`. Leave-one-source-out, masking, v5 forward test, open-weights gap, weight bands. |

## Refresh routine (≈ 15 min, agent or human)

1. **Open each page** in the built-in browser (an agent) or a normal browser (a human). Wait until the table has rendered.
2. **Run `extractors.js`.**
   - Agent: run it through the JavaScript tool. Set `window.RATINGS_PAD = 110000` first so the result is saved to a file instead of returned inline.
   - Large pages (AA leaderboard, AA trends, LMArena overall) are over the ~260k-character bridge limit. Fetch them in slices with `window.RATINGS_SLICE = [0, 150]`, then `[150, 300]`, and so on, and merge the `records`.
   - Human: set `window.RATINGS_DOWNLOAD = true`, then paste the file into the console. It saves `<source>_<category>_<date>.json`.
   - Use `window.RATINGS_SUMMARY = true` for a quick check: counts, metric coverage and one sample record.
3. **Put all envelopes in one folder** and run `normalize.py`. The `aa_trends` envelope is required, because it is the model registry.
4. **Review** `matches_guessed.csv` (fuzzy matches; every method is named) and `unmatched.csv` (with registry candidates).
   - A wrong guess or a missed current model → add a line to `aliases.json` and rerun.
   - Most unmatched names are legacy models AA no longer lists. That's expected.
5. **Score.** Run `analysis.py` after big source changes. Then `rate.py data/obs ratings/v7` builds the workbook.
6. **Check the bookkeeping.** Read `ratings/v7/TRACKED.md`. For every new model near the top of a tier, check its licence and parameter count. AA lags on open-weight releases: Kimi K3.1 Pro and MiniMax-M3.1-Flash published weights after AA had listed them as proprietary. Fix these in `tracked.csv`, with the evidence URL. Move `watch` rows to `track` once a source scores them, and delete overrides once AA catches up.

## Tiers (rating v7)

| tier | rule |
|---|---|
| top-sota | the 10 best models by overall score, any licence, scored by ≥ 2 organisations |
| closed-budget | every other closed model |
| large-oss / mid-oss / small-oss / little-oss / tiny-oss | open weights by total parameters: > 150B / 40–150B / 15–40B / 4.5–15B / < 4.5B (AA's size class when the count is unknown) |

- An open model in top-sota also keeps its row in its size tier.
- Each tier shows its top N (`show_per_tier`), plus pinned models, plus the best fast MoE models (active ≤ ⅓ of total; `moe_extra`).
- A model is *superseded*, and leaves the tracked set, when a newer model from the same lab with the same licence (and, for open models, the same size tier) either belongs to the same product line (name without version numbers, parameter count within 25%), even if it scores lower, or scores higher and is not dearer. We track the current release, so Qwen3.6 35B A3B replaces Qwen3.5 35B A3B.
- Small and tiny models mostly have AA data only. Their category columns are then just the overall score, and they carry a "single source" flag.

## Source playbook

| source | URL | extractor | notes |
|---|---|---|---|
| AA leaderboard | artificialanalysis.ai/leaderboards/models | `aa_leaderboard` | Index (v5 since 2026-10-28), cost per task, speed, about 35 benchmarks. Big, so use slices. Official alternative: the free AA data API, which needs the user's own key and runs on the user's machine. Never put a key into the chat. |
| AA trends | artificialanalysis.ai/trends | `aa_trends` | Progress Index (IRT, public benchmarks), release dates, parameters. **The registry backbone.** About 700 variants; use slices. |
| AA personality | artificialanalysis.ai/evaluations/aa-personalitybench | `aa_personality` | Slop and sycophancy plus 27 more traits, with CIs. The judge is GPT-6 Luna (medium), which is a known self-preference risk. |
| LMArena text | arena.ai/leaderboard/text, `/creative-writing`, `/instruction-following`, … | `lmarena_text` | Elo, CI and votes. If the pane was hidden, React data is missing and the extractor falls back to the table (still exact CIs). |
| Agent Arena | arena.ai/leaderboard/agent, `/code`, `/chat`, `/work` | `arena_agent` | Net improvement % ± CI, with signs read from the icon. The other signals (steerability, tool hallucination, …) come along. |
| Vals | vals.ai/benchmarks/vals_index (and other benchmarks) | `vals` | Index accuracy and cost for all models. The component table only covers the first 15 models; "View N more" does not expand it. |
| Epoch ECI | epoch.ai/eci | `epoch_eci` | Fetches `/data/eci_scores.csv` from inside the page (a direct navigation to the CSV is blocked as a download). Exact ECI + CI. |
| SemiAnalysis GDPx | gdpx.semianalysis.com | `gdpx_fetch.py` (shell, no browser) | 206 expert tasks from 14 data partners across 11 domains (chip design, cybersecurity, biology, finance, legal, quant trading, RSI, hardware, materials, alignment, SWE). Each model runs in its own lab's agent harness (Claude Code, Codex, …) at the reasoning setting the site names. Per model × domain: score, partial score, $/task, output tokens/task. No CIs; mean of 3 attempts, 6–27 tasks per partner, so single domains are noisy. Envelopes: `composite`, `composite_ex_safety` (without biology/cyber/alignment), one per domain, and `<domain>.<partner>` for chip design and materials. Only 21 models. |
| Terminal-Bench 4.1 | tbench.ai/leaderboard | `web_sources.py tbench` | Accuracy ± 95% CI over 330 trials. Model + harness (Claude Code, Codex, …); the best harness per model is kept. Coding. |
| Scale SEAL | labs.scale.com/leaderboard/<board> | `web_sources.py scale` | SWE Atlas (coding), Remote Labor Index (professional, no CI), HLE (reasoning, contamination flags kept), MultiChallenge (writing). Scale sells data to labs and Meta owns a stake in it, so watch Muse rows. |
| Mercor APEX | mercor.com/apex/<board>-leaderboard/ | `web_sources.py apex` | APEX-Agents pass@1, APEX-v1 mean score (professional), APEX-SWE pass@1 (coding), with ±. LLM judges over expert rubrics (Gemini on several boards). Mercor is a data vendor too. |
| WeirdML v3 | htihle.github.io/weirdml.html | `web_sources.py weirdml` | Agentic ML coding, 95% interval, best provider per model. Only 11 tasks. |
| MathArena | matharena.ai/models | `web_sources.py matharena` | IRT expected performance on fresh competition maths ± CI. Low contamination. Reasoning. |
| Lech Mazur writing | github.com/lechmazur/writing | `web_sources.py lechmazur` | Thurstone rating ± 95% bootstrap. The judge panel includes frontier models. The ratings path is dated; update `LECH` when a new run lands (`data/leaderboard.csv` is stale). Writing. |
| SimpleBench | simple-bench.com | `web_sources.py simplebench` | Trick and common-sense reasoning, no CI, near the human ceiling (95.4). |
| Wayback | web.archive.org/web/<ts>/<url> | same as live | Every extractor works on captures, and `wayback_capture` is recorded. The built-in browser needs one approval per action. |
| not covered yet | OpenRouter rankings (tokens: paid + 0.3 × free), FrontierCS 2.0 | — | Enter these manually for now. FrontierCS configs are on GitHub, which the workspace shell can reach. |

As of 2026-11-13 the shell reaches the open web: GDPx and every source fetched by `web_sources.py` download from the shell. AA, arena.ai, Vals and Epoch still use the browser extractors. Re-test them before the next refresh, since a shell fetch would bring Fable 5.2 into the AA registry.

Considered and not added (2026-11-13): SWE-bench, SWE-rebench, LiveBench, τ²-bench, METR and Context Arena are stale; ARC-AGI-2/3, SWE-Bench Pro Full and NYT Connections are saturated; the Vectara hallucination board is anti-correlated with capability and could be its own factor later; EuroEval and SEA-HELM lack Opus 5.5 and Gemini 4; EQ-Bench uses old judges.

## Matching rules (normalize.py)

- **Effort.** Names are split into base and effort: `Claude Opus 5.5 (Max, Default Fallback)` → `Claude Opus 5.5` + `max`.
  - Thinking/Reasoning → the top reasoning effort.
  - Instant and Non-Thinking → `non-reasoning`.
  - Token budgets (`32K`) and quantisation tags (`NVFP4`) are dropped.
- **Registry.** The AA trends envelope defines the canonical base models and their effort variants.
- **Fallbacks, in order.** Each is flagged `match:<method>` on every observation:
  - `token_order`: same words in a different order.
  - `noise_tokens`: Instruct/IT/Preview/Beta/Latest/Thinking/NVIDIA dropped.
  - `build_match`: same build code.
  - `build_by_month`: build date or month-year agrees with the AA entry's name or release month.
  - `param_suffix` / `params_ignored`: parameter-size words only on one side.
  - `build_dropped`: the source names a build; AA lists one undated entry.
  - `build_assumed_earliest`: no build named; AA only lists dated builds.
- **Unlabelled effort.**
  - Vals and Epoch → the model's top effort, since they publish one row per model.
  - Other sources → AA's `default` variant if there is one, else `unlabelled` (flagged).
- **Collisions.** Two source names on one model × effort: the better match wins and the other is flagged `collision_dropped`. A tie flags both `collision`. The scorer skips both flags.

Reference run, 2026-10-28/29 envelopes: 13.8k observations, registry 517 base models. Unmatched names are mostly legacy models: Epoch 73/270, LMArena creative writing 149/417, Agent Arena 1/57, Vals 2/29 (Hy4 Preview and Mercury 3 aren't on AA). Of the AA models released in 2026, LMArena covers 99 and Epoch 81.

## Attribution

The data belongs to Artificial Analysis, LMArena/Arena, Vals AI, Epoch AI, SemiAnalysis (GDPx), the Laude Institute (Terminal-Bench), Scale AI, Mercor, htihle (WeirdML), MathArena (ETH SRI / INSAIT), Lech Mazur and SimpleBench. Cite them whenever you reuse it.
