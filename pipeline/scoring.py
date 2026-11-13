#!/usr/bin/env python3
"""model-ratings-pipeline · scoring.py — aggregation methods for our own model ratings.

Library used by analysis.py (method tests) and, later, by the rating build. Input is the long table written by
normalize.py (observations.csv); output is a model × source matrix and composite scores.

Methods (all return a score on the 50 ± 15 scale where 50 = mean model of the analysis set):
    zmean      weighted mean of per-source z-scores over the sources a model has   (rating sheet v6)
    pct        weighted mean of per-source percentile ranks, mapped to the same scale
    shrink     zmean with a prior: missing sources pull the score toward 50 (lam = prior weight in "sources")
    linked     zmean after putting every source on one common scale (fixes the coverage bias of plain z-scores)
    factor     one-factor model fitted by EM with missing data. Loadings/noise are estimated from the data
               (data-driven reliability); optional relevance weights r_j scale each source's precision.
               Gives a posterior SD per model -> honest uncertainty bands that widen when sources are missing.
"""
import csv, math
import numpy as np

EFFORT_RANK = {e: i for i, e in enumerate(["max", "xhigh", "high", "default", "reasoning", "medium", "low",
                                           "minimal", "non-reasoning", "unlabelled"])}
BAD_FLAGS = ("collision",)          # 'collision' and 'collision_dropped': two source names on one variant


# ---------------------------------------------------------------- data
def load_observations(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for r in rows:
        try:
            r["value"] = float(r["value"])
        except (TypeError, ValueError):
            r["value"] = None
    return rows


def load_registry(path):
    return {r["base_key"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def pick(rows, source, metric, category=None, wayback=None, level="top"):
    """{base_key: (value, effort)} for one source column.
    wayback: None = any, True = only archived captures, False = only live retrievals.
    level 'top' = the highest effort variant the source reports for that model (labelled before unlabelled);
    'all' = {(base_key, effort): value}."""
    best = {}
    for r in rows:
        if r["source"] != source or r["metric"] != metric or r["value"] is None or not r["base_key"]:
            continue
        if category is not None and r["category"] != category:
            continue
        if wayback is not None and bool(r.get("wayback_capture")) != wayback:
            continue
        if any(f in (r.get("flags") or "") for f in BAD_FLAGS):
            continue
        eff = r["effort"] or "unlabelled"
        key = r["base_key"] if level == "top" else (r["base_key"], eff)
        rank = (EFFORT_RANK.get(eff.split(":")[0], 99), r["date"])
        cur = best.get(key)
        if cur is None or rank[0] < cur[1][0] or (rank[0] == cur[1][0] and rank[1] > cur[1][1]):
            best[key] = (r["value"], rank, eff)
    return {k: (v[0], v[2]) for k, v in best.items()}


def matrix(rows, spec, models=None):
    """spec: list of dicts {id, source, metric, category?, wayback?, sign? (+1/-1), log? (bool)}.
    Returns (keys, ids, X) with X[i, j] = value or nan."""
    cols = {s["id"]: pick(rows, s["source"], s["metric"], s.get("category"), s.get("wayback")) for s in spec}
    keys = sorted(set().union(*[set(c) for c in cols.values()]) if models is None else models)
    X = np.full((len(keys), len(spec)), np.nan)
    for j, s in enumerate(spec):
        for i, k in enumerate(keys):
            if k in cols[s["id"]]:
                v = cols[s["id"]][k][0]
                if s.get("log"):
                    v = math.log(v) if v > 0 else np.nan
                X[i, j] = s.get("sign", 1) * v
    return keys, [s["id"] for s in spec], X


# ---------------------------------------------------------------- methods
def zcols(X):
    mu, sd = np.nanmean(X, 0), np.nanstd(X, 0, ddof=1)
    return (X - mu) / np.where(sd > 0, sd, 1)


def zmean(X, w=None, **_):
    Z, w = zcols(X), np.ones(X.shape[1]) if w is None else np.asarray(w, float)
    W = np.where(np.isnan(Z), 0, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.nansum(np.nan_to_num(Z) * W, 1) / W.sum(1)
    return 50 + 15 * s


def pct(X, w=None, **_):
    from scipy.stats import rankdata, norm
    P = np.full_like(X, np.nan)
    for j in range(X.shape[1]):
        m = ~np.isnan(X[:, j])
        P[m, j] = (rankdata(X[m, j]) - 0.5) / m.sum()
    w = np.ones(X.shape[1]) if w is None else np.asarray(w, float)
    W = np.where(np.isnan(P), 0, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = np.nansum(np.nan_to_num(P) * W, 1) / W.sum(1)
    return 50 + 15 * norm.ppf(np.clip(p, 0.005, 0.995))


def shrink(X, w=None, lam=1.0, **_):
    """lam = prior weight measured in average sources: a model with one source sits halfway to 50 when lam = 1."""
    Z, w = zcols(X), np.ones(X.shape[1]) if w is None else np.asarray(w, float)
    W = np.where(np.isnan(Z), 0, w)
    s = np.nansum(np.nan_to_num(Z) * W, 1) / (W.sum(1) + lam * w.mean())
    return 50 + 15 * s


def factor_fit(X, iters=500, tol=1e-7, min_psi=0.05):
    """One-factor model x_ij = mu_j + l_j f_i + e_ij, f ~ N(0,1), e ~ N(0, psi_j), fitted by EM on observed cells.
    Columns are z-scored first, so l_j^2 / (l_j^2 + psi_j) is source j's reliability for the common factor."""
    Z = zcols(X)
    O = ~np.isnan(Z)
    n, p = Z.shape
    mu, lam, psi = np.zeros(p), np.full(p, 0.7), np.full(p, 0.5)
    prev = None
    for _ in range(iters):
        prec = 1 + (O * (lam ** 2 / psi)).sum(1)                       # E-step
        V = 1 / prec
        m = V * (O * (lam / psi) * np.nan_to_num(Z - mu)).sum(1)
        for j in range(p):                                              # M-step
            o = O[:, j]
            if o.sum() < 3:
                continue
            x, mm, vv = Z[o, j], m[o], V[o]
            A = np.array([[o.sum(), mm.sum()], [mm.sum(), (mm ** 2 + vv).sum()]])
            b = np.array([x.sum(), (x * mm).sum()])
            mu[j], lam[j] = np.linalg.solve(A, b)
            psi[j] = max(min_psi, np.mean((x - mu[j] - lam[j] * mm) ** 2 + lam[j] ** 2 * vv))
        if lam.sum() < 0:
            lam = -lam
        ll = np.concatenate([mu, lam, psi])
        if prev is not None and np.max(np.abs(ll - prev)) < tol:
            break
        prev = ll
    return {"mu": mu, "lam": lam, "psi": psi, "reliability": lam ** 2 / (lam ** 2 + psi)}


def factor(X, w=None, fit=None, **_):
    """Posterior mean of the common factor; w = optional relevance weights (scale each source's precision).
    Returns scores; factor.sd holds the posterior SD in the same 15-points-per-SD units."""
    fit = fit or factor_fit(X)
    Z = zcols(X)
    O = ~np.isnan(Z)
    r = np.ones(X.shape[1]) if w is None else np.asarray(w, float) / np.mean(w)
    prec = 1 + (O * (r * fit["lam"] ** 2 / fit["psi"])).sum(1)
    m = (O * (r * fit["lam"] / fit["psi"]) * np.nan_to_num(Z - fit["mu"])).sum(1) / prec
    factor.sd = 15 / np.sqrt(prec)
    factor.fit = fit
    return 50 + 15 * m


def linked(X, w=None, fit=None, **_):
    """zmean after linking every source to one common scale (intercept and slope from the factor fit), so a source
    that only covers frontier models no longer calls the average frontier model 'average'. Same weights as zmean,
    no precision weighting: isolates the linking effect from the factor model's reliability weighting."""
    fit = fit or factor_fit(X)
    S = (zcols(X) - fit["mu"]) / np.where(np.abs(fit["lam"]) > 1e-6, fit["lam"], 1)
    w = np.ones(X.shape[1]) if w is None else np.asarray(w, float)
    W = np.where(np.isnan(S), 0, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        return 50 + 15 * np.nansum(np.nan_to_num(S) * W, 1) / W.sum(1)


METHODS = {"zmean": zmean, "pct": pct, "shrink": shrink, "linked": linked, "factor": factor}
