#!/usr/bin/env python3
"""model-ratings-pipeline · analysis.py — tests which aggregation method to trust.

    python3 -I analysis.py OBS_DIR [REPORT.md]

OBS_DIR is normalize.py's output (observations.csv, registry.csv). Needs these columns in the data:
AA index archived (Wayback, v4.3.2) and live (v5), AA Progress Index, Epoch ECI, Vals Index, LMArena text
(any category; the creative-writing board in the reference run), Agent Arena (work board).

Tests
 1 LOSO validity      leave one source out; how well does the composite of the rest rank that source's models?
 2 masking            hide 30 % of a model's known values; how stable are the ranks?
 3 forward test       predict AA Intelligence Index v5 (60 % private, launched 2026-10-28) from pre-v5 data;
                      leave-one-out calibration; open-weights gap = how much each predictor overrates
                      open-weights models relative to v5
 4 benchmark gap      the same open-weights gap per legacy public AA benchmark (contamination/benchmaxxing proxy)
 5 weight sensitivity rank bands under ±30 % random weight changes; factor-model posterior bands
"""
import os, sys
import warnings
import numpy as np
from scipy.stats import spearmanr

warnings.simplefilter("ignore", np.exceptions.RankWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scoring as sc

GENERAL = [dict(id="aa432", source="aa_leaderboard", metric="intelligence_index", wayback=True),
           dict(id="epoch", source="epoch_eci", metric="eci"),
           dict(id="vals", source="vals", metric="accuracy"),
           dict(id="lmarena", source="lmarena_text", metric="elo"),
           dict(id="agent", source="arena_agent", metric="net_improvement")]
INDEPENDENT = ["epoch", "vals", "lmarena", "agent"]
V5 = dict(id="aa5", source="aa_leaderboard", metric="intelligence_index", wayback=False)
PROGRESS = dict(id="progress", source="aa_trends", metric="progress_index")
METHODS = ["zmean", "pct", "shrink", "linked", "factor"]
V5_COMPONENTS = {"aa-briefcase", "automationbench-aa", "gdp-pdf", "frontiercode", "frontiercode-2-0", "terminalbench-4-0",
                 "terminal-bench-science", "critpt", "critpt-v2-hard", "omniscience-accuracy",
                 "omniscience-non-hallucination", "hle-diamond", "humanitys-last-exam"}
RNG = np.random.default_rng(20261029)


def rho(a, b):
    m = ~(np.isnan(a) | np.isnan(b))
    return (spearmanr(a[m], b[m])[0], int(m.sum())) if m.sum() >= 5 else (np.nan, int(m.sum()))


def run(method, X, w=None):
    return sc.METHODS[method](X, w)


def loso(X, ids):
    out = {}
    for j, s in enumerate(ids):
        rest = [k for k in range(len(ids)) if k != j]
        keep = (~np.isnan(X[:, rest])).sum(1) >= 2
        for mth in METHODS:
            comp = np.full(len(X), np.nan)
            comp[keep] = run(mth, X[keep][:, rest])
            out[(s, mth)] = rho(comp, X[:, j])
    return out


def masking(X, reps=200, p=0.3):
    res = {m: [] for m in METHODS}
    top = {m: [] for m in METHODS}
    for mth in METHODS:
        full = run(mth, X)
        t10 = set(np.argsort(-full)[:10])
        for _ in range(reps):
            M = X.copy()
            for i in range(len(M)):
                obs = np.where(~np.isnan(M[i]))[0]
                hide = obs[RNG.random(len(obs)) < p]
                if len(hide) == len(obs):
                    hide = hide[1:]
                M[i, hide] = np.nan
            s = run(mth, M)
            res[mth].append(spearmanr(full, s)[0])
            top[mth].append(len(t10 & set(np.argsort(-s)[:10])))
    return {m: (np.mean(res[m]), np.mean(top[m])) for m in METHODS}


def loo_calibrate(pred, y, deg=2):
    """Leave-one-out polynomial calibration y ~ poly(pred) (degree 2: the Progress Index is an IRT scale, not
    linear in v5 points). Returns residuals (nan where pred missing)."""
    m = ~(np.isnan(pred) | np.isnan(y))
    res = np.full(len(y), np.nan)
    idx = np.where(m)[0]
    if len(idx) < 8:
        return res
    mu, sd = pred[idx].mean(), pred[idx].std() or 1
    deg = deg if len(idx) >= 25 else 1                 # small samples: straight line only
    for i in idx:
        tr = idx[idx != i]
        c = np.polyfit((pred[tr] - mu) / sd, y[tr], deg)
        res[i] = y[i] - np.polyval(c, (pred[i] - mu) / sd)
    return res


def gap(res, y, open_w, reps=2000):
    """Open-weights gap in v5 points: mean calibrated residual (open − proprietary). Negative = the predictor rates
    open-weights models higher than v5 does. A noisy but unbiased predictor also leaves a gap, because it only
    explains R² of v5's own open/closed difference: expected = Δv5 · (1 − R²). Excess = gap − expected isolates
    bias from noise. Returns gap, excess, 90 % bootstrap interval of the excess, n_open."""
    m = ~np.isnan(res)
    o, c = np.where(m & open_w)[0], np.where(m & ~open_w)[0]
    if len(o) < 3 or len(c) < 3:
        return np.nan, np.nan, (np.nan, np.nan), len(o)

    def stat(oi, ci):
        r2 = 1 - np.var(np.r_[res[oi], res[ci]]) / np.var(np.r_[y[oi], y[ci]])
        g = res[oi].mean() - res[ci].mean()
        return g, g - (y[oi].mean() - y[ci].mean()) * (1 - r2)
    g, ex = stat(o, c)
    bs = [stat(RNG.choice(o, len(o)), RNG.choice(c, len(c)))[1] for _ in range(reps)]
    return g, ex, tuple(np.percentile(bs, [5, 95])), len(o)


def fmt(x, d=2):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def main(obs_dir, report=None):
    rows = sc.load_observations(os.path.join(obs_dir, "observations.csv"))
    reg = sc.load_registry(os.path.join(obs_dir, "registry.csv"))
    keys, ids, X = sc.matrix(rows, GENERAL)
    cnt = (~np.isnan(X)).sum(1)
    sel = cnt >= 3
    Xs, ks = X[sel], [k for k, s in zip(keys, sel) if s]
    L = [f"# Aggregation method tests\n",
         f"Data: {os.path.basename(os.path.normpath(obs_dir))} · {len(keys)} base models with any of {ids}; test set = {sel.sum()} models with ≥3 of them "
         f"(top effort per model; collisions excluded).\n",
         "Methods: **zmean** weighted mean of z-scores (sheet v6) · **pct** mean percentile rank · "
         "**shrink** zmean with a 1-source prior toward 50 · **linked** zmean after linking each source to a common "
         "scale · **factor** one-factor model, EM with missing data (linking + reliability weighting).\n"]

    fit = sc.factor_fit(Xs)
    L.append("## Data-driven reliability (one-factor fit on the test set)\n")
    L.append("| source | n | loading | noise ψ | reliability λ²/(λ²+ψ) |\n|---|---|---|---|---|")
    for j, s in enumerate(ids):
        L.append(f"| {s} | {int((~np.isnan(Xs[:, j])).sum())} | {fmt(fit['lam'][j])} | {fmt(fit['psi'][j])} | {fmt(fit['reliability'][j])} |")
    C = np.full((len(ids), len(ids)), np.nan)
    for a in range(len(ids)):
        for b in range(len(ids)):
            C[a, b] = rho(X[:, a], X[:, b])[0]
    L.append("\nPairwise Spearman (all models with both):\n")
    L.append("| | " + " | ".join(ids) + " |\n|---" * 1 + "|---" * len(ids) + "|")
    for a, s in enumerate(ids):
        L.append(f"| {s} | " + " | ".join(fmt(C[a, b]) for b in range(len(ids))) + " |")

    L.append("\n## 1 Leave-one-source-out validity (Spearman, composite of the other sources vs the left-out one)\n")
    lo = loso(Xs, ids)
    L.append("| left out | n | " + " | ".join(METHODS) + " |\n|---|---" + "|---" * len(METHODS) + "|")
    for s in ids:
        L.append(f"| {s} | {lo[(s, METHODS[0])][1]} | " + " | ".join(fmt(lo[(s, m)][0]) for m in METHODS) + " |")
    L.append("| **mean** | | " + " | ".join(fmt(np.nanmean([lo[(s, m)][0] for s in ids])) for m in METHODS) + " |")

    L.append("\n## 2 Masking robustness (hide 30 % of known values, 200 runs)\n")
    mk = masking(Xs)
    L.append("| method | Spearman vs full | top-10 kept |\n|---|---|---|")
    for m in METHODS:
        L.append(f"| {m} | {fmt(mk[m][0], 3)} | {fmt(mk[m][1], 1)}/10 |")

    L.append("\n## 3 Forward test: predicting AA Index v5 from pre-v5 information\n")
    allk = sorted(set(keys) | set(sc.pick(rows, **{k: V5[k] for k in ("source", "metric", "wayback")})))
    _, _, XA = sc.matrix(rows, GENERAL + [V5, PROGRESS], models=allk)
    y = XA[:, len(GENERAL)]
    prog = XA[:, len(GENERAL) + 1]
    G = XA[:, :len(GENERAL)]
    open_w = np.array([str(reg.get(k, {}).get("open_weights")) == "True" for k in allk])
    has = ~np.isnan(y)
    preds = {"AA v4.3.2 index": G[:, 0], "AA Progress Index": prog}
    ind = [ids.index(s) for s in INDEPENDENT]
    for m in METHODS:
        P = G[:, ind]
        k2 = (~np.isnan(P)).sum(1) >= 2
        v = np.full(len(allk), np.nan); v[k2] = run(m, P[k2]); preds[f"independent · {m}"] = v
        k3 = (~np.isnan(G)).sum(1) >= 2
        v = np.full(len(allk), np.nan); v[k3] = run(m, G[k3]); preds[f"all pre-v5 · {m}"] = v
    dv5 = np.nanmean(y[has & open_w]) - np.nanmean(y[has & ~open_w])
    L.append(f"Target: {int(has.sum())} models with a v5 score ({int((has & open_w).sum())} open-weights; open-weights "
             f"average {fmt(dv5, 1)} v5 points vs proprietary). RMSE after leave-one-out quadratic calibration, in "
             "v5 points. Gap = mean residual open − proprietary (negative = predictor rates open-weights models "
             "higher than v5 does). Excess = gap beyond what the predictor's noise alone would leave; 90 % bootstrap.\n")
    L.append("| predictor | n (open) | Spearman | LOO RMSE | gap | excess [90 % CI] |\n|---|---|---|---|---|---|")
    for name, p in preds.items():
        r, n = rho(p, y)
        res = loo_calibrate(p, y)
        g, ex, ci, no = gap(res, y, open_w)
        L.append(f"| {name} | {n} ({no}) | {fmt(r)} | {fmt(np.sqrt(np.nanmean(res ** 2)))} | {fmt(g, 1)} | "
                 f"{fmt(ex, 1)} [{fmt(ci[0], 1)}, {fmt(ci[1], 1)}] |")

    L.append("\n## 4 Open-weights gap per legacy public AA benchmark (v4.3.2 capture) vs v5\n")
    benches = sorted({r["metric"] for r in rows if r["source"] == "aa_leaderboard" and r["metric"].startswith("bench.")
                      and r.get("wayback_capture")})
    out = []
    for b in benches:
        bm = sc.pick(rows, "aa_leaderboard", b, wayback=True)
        xb = np.array([bm[k][0] if k in bm else np.nan for k in allk])
        res = loo_calibrate(xb, y)
        n = int((~np.isnan(res)).sum())
        if n < 20:
            continue
        g, ex, ci, no = gap(res, y, open_w)
        if no < 4:
            continue
        inv5 = b[6:] in V5_COMPONENTS
        out.append((ex, b[6:] + (" (in v5)" if inv5 else ""), n, rho(xb, y)[0], g, ci, no))
    L.append("Same measure per benchmark. Benchmarks that are part of v5 are marked; they share items with the "
             "target, so their gap is biased toward 0.\n")
    L.append("| benchmark | n (open) | Spearman with v5 | gap | excess [90 % CI] |\n|---|---|---|---|---|")
    for ex, b, n, r, g, ci, no in sorted(out, key=lambda t: np.nan_to_num(t[0], nan=99)):
        L.append(f"| {b} | {n} ({no}) | {fmt(r)} | {fmt(g, 1)} | {fmt(ex, 1)} [{fmt(ci[0], 1)}, {fmt(ci[1], 1)}] |")

    L.append("\n## 5 Weight sensitivity and uncertainty (test set)\n")
    base = sc.zmean(Xs)
    ranks = []
    for _ in range(500):
        w = RNG.gamma(11, 1, len(ids))           # gamma(11) ≈ ±30 % per weight
        s = sc.zmean(Xs, w)
        ranks.append(np.argsort(np.argsort(-s)) + 1)
    ranks = np.array(ranks)
    fsc = sc.factor(Xs, fit=fit)
    fsd = sc.factor.sd
    order = np.argsort(-base)[:15]
    L.append("| model | zmean | rank band 5–95 % (weights ±30 %) | factor score ± 90 % | sources |\n|---|---|---|---|---|")
    for i in order:
        name = reg.get(ks[i], {}).get("base_name", ks[i])
        lo5, hi95 = np.percentile(ranks[:, i], [5, 95]).astype(int)
        L.append(f"| {name} | {fmt(base[i], 1)} | {lo5}–{hi95} | {fmt(fsc[i], 1)} ± {fmt(1.645 * fsd[i], 1)} | {int(cnt[sel][i])} |")

    text = "\n".join(L) + "\n"
    if report:
        open(report, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
