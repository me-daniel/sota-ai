#!/usr/bin/env python3
"""model-ratings-pipeline · rate.py — rating v7: tiered model ratings with uncertainty bands.

    uv run python -I pipeline/rate.py OBS_DIR OUT_DIR [--config pipeline/rating_config.json]
                                                      [--tracked pipeline/tracked.csv] [--today YYYY-MM-DD]

OBS_DIR  normalize.py output (observations.csv, registry.csv)
OUT_DIR  receives model_ratings_v7.xlsx, ratings_v7.csv (every rated model) and TRACKED.md (the bookkeeping view)

Method (rating-concept-v7.md, implemented):
  1. Population = registry models released in the last 12 months (not deprecated, superseded builds dropped),
     plus every 'track' row of tracked.csv (and undated models with non-AA data). 50 = population mean, 15 = 1 SD.
  2. One AA column: Intelligence Index v5 if measured, else v4.3.2 linked to the v5 scale (linear fit on the
     overlap), else Progress Index (quadratic fit). Fallbacks are flagged 'AA est.'.
  3. Reliability per source (loading λ, noise ψ) from a one-factor EM fit with missing data. Each category is
     fitted on its own columns when ≥ min_models_for_category_fit models have ≥ 3 of them; otherwise it borrows
     the λ, ψ of the fit over all columns.
  4. Relevance weights r_j per category (rating_config.json), each organisation capped at org_cap of the mass
     (or 1/n_orgs when the cap can't be met).
  5. Score = 50 + 15·m, m = Σ r λ (z − μ)/ψ ÷ (1 + Σ r λ²/ψ); 90 % band = ± 1.645 · 15 / √(1 + Σ r λ²/ψ).
     Missing sources widen the band and pull toward 50.
  6. Tiers: top-sota = the top_sota_n models by overall score, any licence, scored by ≥ 2 organisations. Other closed models → closed-budget.
     Open-weights models → large / mid / small / little / tiny-oss by total parameters (< 4.5B tiny, < 15B little,
     < 40B small, < 150B mid, else large; AA's size class if the count is unknown), also when in top-sota. tracked.csv can override
     tier, open weights and attributes, add models the registry lacks, and list 'watch' models that have no data.
  7. Rank bands within each tier from 4000 draws of N(score, sd); models whose bands overlap are not separable.
Rows are base models at their top measured effort (the effort of the AA value is shown).
"""
import csv, json, math, os, re, sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scoring as sc
from normalize import norm_key

RNG = np.random.default_rng(20261113)


def truthy(x):
    return str(x).strip().lower() in ("true", "yes", "1")


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ registry + tracked overrides
def load_tracked(path):
    if not path or not os.path.exists(path):
        return []
    return [r for r in csv.DictReader(open(path, encoding="utf-8")) if r.get("model")]


def apply_tracked(reg, rows, tracked):
    """Overrides and manual additions. Returns {base_key: tracked row} for 'track' rows and the watch list."""
    pins, watch = {}, []
    for t in tracked:
        k = norm_key(t["model"])
        status = (t.get("status") or "track").strip()
        if status == "watch":
            watch.append(t)
            continue
        if k not in reg:
            reg[k] = {"base_key": k, "base_name": t["model"], "org": t.get("lab") or "", "release_date": "",
                      "params_total_b": "", "params_active_b": "", "open_weights": "", "licence": "",
                      "size_class": "", "deprecated": "", "efforts": "", "top_effort": "", "manual": True}
        names = {k} | {norm_key(x) for x in (t.get("aka") or "").split(";") if x.strip()}
        for r in rows:          # attach observations that normalize.py could not match (name or any 'aka')
            if not r["base_key"] and norm_key(r["base_name"]) in names:
                r["base_key"] = k
        e = reg[k]
        for f, col in (("open_weights", "open_weights"), ("org", "lab"), ("release_date", "release_date"),
                       ("params_total_b", "params_total_b"), ("params_active_b", "params_active_b")):
            if (t.get(col) or "").strip():
                e[f] = t[col].strip()
        if (t.get("params_total_b") or "").strip():
            e["size_class"] = ""          # recompute from the overridden parameter count
        if (t.get("tier") or "").strip():
            e["tier_override"] = t["tier"].strip()
        e["note"] = t.get("note") or ""
        e["evidence"] = t.get("evidence") or ""
        if status == "drop":
            e["dropped"] = True
        else:
            pins[k] = t
    return pins, watch


def size_class(e, cfg):
    """From total parameters (bounds in config); AA's own size class only when the count is unknown.
    AA has no 'little' class, so an AA 'small' without a parameter count stays small."""
    p = fnum(e.get("params_total_b"))
    if p is None:
        return e.get("size_class") or None
    b = cfg["tiers"]["size_bounds_b"]
    return "tiny" if p < b["tiny"] else "little" if p < b["little"] else "small" if p < b["small"] \
        else "medium" if p < b["medium"] else "large"


def family(k):
    return re.sub(r"\d{4}$", "", k)


# ------------------------------------------------------------------ columns
def monotone_fit(x, y, deg):
    """Polynomial fit that must rise over the fitted range (else linear); linear beyond the range."""
    lo, hi = float(np.min(x)), float(np.max(x))
    coef = np.polyfit(x, y, deg)
    grid = np.linspace(lo, hi, 200)
    if deg > 1 and np.any(np.diff(np.polyval(coef, grid)) <= 0):
        coef, deg = np.polyfit(x, y, 1), 1
    d = np.polyder(coef)

    def f(v):
        if v < lo:
            return float(np.polyval(coef, lo) + np.polyval(d, lo) * (v - lo))
        if v > hi:
            return float(np.polyval(coef, hi) + np.polyval(d, hi) * (v - hi))
        return float(np.polyval(coef, v))
    rmse = float(np.sqrt(np.mean([(f(a) - b) ** 2 for a, b in zip(x, y)])))
    return f, {"deg": deg, "n": len(x), "range": [round(lo, 1), round(hi, 1)], "rmse": round(rmse, 2)}


def aa_unified(rows, keys):
    """{key: (value, effort, estimated?)} on the v5 scale, plus the calibration used.
    v4.3.2 → v5 linear on their overlap; Progress → v4.3.2 (quadratic, monotone; the overlap spans small models too)
    and then → v5, so small models are not extrapolated from a frontier-only fit."""
    v5 = sc.pick(rows, "aa_leaderboard", "intelligence_index", wayback=False)
    v4 = sc.pick(rows, "aa_leaderboard", "intelligence_index", wayback=True)
    pr = sc.pick(rows, "aa_trends", "progress_index")
    both = [k for k in v5 if k in v4]
    f45, c45 = monotone_fit(np.array([v4[k][0] for k in both]), np.array([v5[k][0] for k in both]), 1)
    both = [k for k in v4 if k in pr]
    fp4, cp4 = monotone_fit(np.array([pr[k][0] for k in both]), np.array([v4[k][0] for k in both]), 2)
    cal = {"v4.3.2→v5": c45, "progress→v4.3.2": cp4}
    out = {}
    for k in keys:
        if k in v5:
            out[k] = (v5[k][0], v5[k][1], None)
        elif k in v4:
            out[k] = (f45(v4[k][0]), v4[k][1], "v4.3.2")
        elif k in pr:
            out[k] = (f45(fp4(pr[k][0])), pr[k][1], "progress")
    return out, cal


def column(rows, s):
    return sc.pick(rows, s["source"], s["metric"], s.get("category"), s.get("wayback"))


# ------------------------------------------------------------------ weights + posterior
def capped_weights(cfg, cat):
    src = cfg["sources"]
    w = np.array([float(s["w"].get(cat, 0)) for s in src])
    orgs = sorted({s["org"] for s, x in zip(src, w) if x > 0})
    cap = max(cfg["org_cap"], 1 / len(orgs)) if orgs else 1
    for _ in range(50):
        tot = w.sum()
        mass = {o: sum(x for s, x in zip(src, w) if s["org"] == o) / tot for o in orgs}
        over = [o for o, m in mass.items() if m > cap + 1e-9]
        if not over:
            break
        for o in over:   # scale the org down to the cap, keeping the others' absolute weight
            others = tot * (1 - mass[o])
            target = cap / (1 - cap) * others
            f = target / (mass[o] * tot)
            w = np.array([x * f if s["org"] == o else x for s, x in zip(src, w)])
    nz = w > 0
    if nz.any():
        w = w / w[nz].mean()       # mean relevance over the category's sources = 1
    return w, {o: round(sum(x for s, x in zip(src, w) if s["org"] == o) / w.sum(), 3) for o in orgs}


def posterior(Z, O, fit, r):
    lam, psi, mu = fit["lam"], fit["psi"], fit["mu"]
    prec = 1 + (O * (r * lam ** 2 / psi)).sum(1)
    m = (O * (r * lam / psi) * np.nan_to_num(Z - mu)).sum(1) / prec
    return 50 + 15 * m, 15 / np.sqrt(prec)


def rank_bands(scores, sds, reps=4000):
    n = len(scores)
    if n == 0:
        return []
    draws = scores[None, :] + sds[None, :] * RNG.standard_normal((reps, n))
    ranks = (-draws).argsort(1).argsort(1) + 1
    lo, hi = np.percentile(ranks, 5, 0), np.percentile(ranks, 95, 0)
    return [(int(round(a)), int(round(b))) for a, b in zip(lo, hi)]


# ------------------------------------------------------------------ main
def main(obs_dir, out_dir, cfg_path, tracked_path, today):
    cfg = json.load(open(cfg_path))
    rows = sc.load_observations(os.path.join(obs_dir, "observations.csv"))
    reg = sc.load_registry(os.path.join(obs_dir, "registry.csv"))
    pins, watch = apply_tracked(reg, rows, load_tracked(tracked_path))

    srcs = cfg["sources"]
    plain = [s for s in srcs if s.get("special") != "aa_unified"]
    cols = {s["id"]: column(rows, s) for s in plain}
    non_aa = set().union(*[set(c) for c in cols.values()])
    cutoff = (today - timedelta(days=round(30.4 * cfg["scale"]["population_months"]))).isoformat()
    pop = {k for k, e in reg.items()
           if not e.get("dropped") and not truthy(e.get("deprecated"))
           and ((e.get("release_date") or "") >= cutoff or k in pins
                or (not e.get("release_date") and k in non_aa))}
    newest = {}
    for k in sorted(pop, key=lambda k: reg[k].get("release_date") or ""):
        newest[family(k)] = k            # later release of the same family wins
    superseded = {k for k in pop if newest[family(k)] != k and k not in pins}
    pop = sorted(pop - superseded)

    aa, cal = aa_unified(rows, pop)
    pop = [k for k in pop if k in aa or any(k in c for c in cols.values())]   # needs at least one value
    ids = [s["id"] for s in srcs]
    X = np.full((len(pop), len(srcs)), np.nan)
    for i, k in enumerate(pop):
        for j, s in enumerate(srcs):
            if s.get("special") == "aa_unified":
                v = aa.get(k, (None,))[0]
            else:
                v = cols[s["id"]].get(k, (None,))[0]
            if v is not None:
                X[i, j] = s.get("sign", 1) * v
    Z, O = sc.zcols(X), ~np.isnan(X)
    general = sc.factor_fit(X)

    res, method = {}, {}
    for cat in cfg["categories"]:
        r, mass = capped_weights(cfg, cat)
        use = r > 0
        enough = int(((O[:, use]).sum(1) >= 3).sum())
        if cat != "overall" and enough >= cfg["min_models_for_category_fit"]:
            f = sc.factor_fit(X[:, use])
            fit = {k: general[k].copy() for k in ("mu", "lam", "psi")}
            for k in fit:
                fit[k][use] = f[k]
            how = f"own fit ({enough} models with ≥3 sources)"
        else:
            fit = general
            how = f"general fit ({enough} models with ≥3 of its sources < {cfg['min_models_for_category_fit']})" \
                if cat != "overall" else "general fit"
        s, sd = posterior(Z, O, fit, np.where(use, r, 0))
        cov = (O * np.where(use, r, 0)).sum(1) / max(r[use].sum(), 1e-9)
        res[cat] = (s, sd, cov)
        method[cat] = {"how": how, "weights": {ids[j]: round(float(r[j]), 3) for j in range(len(ids)) if use[j]},
                       "org_mass": mass, "reliability": {ids[j]: round(float(fit["lam"][j] ** 2 / (fit["lam"][j] ** 2 + fit["psi"][j])), 3)
                                                          for j in range(len(ids)) if use[j]}}

    # cost and speed
    c5 = sc.pick(rows, "aa_leaderboard", "cost_per_task", wayback=False)
    c4 = sc.pick(rows, "aa_leaderboard", "cost_per_task", wayback=True)
    e2e = sc.pick(rows, "aa_leaderboard", "e2e_s")

    ov = res["overall"][0]
    order = np.argsort(-ov)
    orgs_of = lambda i: len({srcs[j]["org"] for j in range(len(srcs)) if O[i, j]})
    eligible = [i for i in order if orgs_of(i) >= cfg["tiers"].get("top_sota_min_orgs", 2)]
    top = {pop[i] for i in eligible[:cfg["tiers"]["top_sota_n"]]}      # frontier claims need ≥ 2 organisations
    models = []
    for i, k in enumerate(pop):
        e = reg[k]
        open_w = truthy(e.get("open_weights"))
        sz = size_class(e, cfg)
        home = e.get("tier_override") or (cfg["tiers"]["size_class_to_tier"].get(sz, "oss-unknown-size") if open_w else "closed-budget")
        tiers = [home] + (["top-sota"] if k in top and home != "top-sota" else [])
        if k in top and not open_w and "closed-budget" in tiers:
            tiers.remove("closed-budget")
        flags = []
        if k in aa and aa[k][2]:
            flags.append(f"AA est. ({aa[k][2]})")
        if e.get("tier_override"):
            flags.append("tier override")
        if e.get("manual"):
            flags.append("manual registry entry")
        if O[i].sum() == 1:
            flags.append("single source")
        n_orgs = len({srcs[j]["org"] for j in range(len(srcs)) if O[i, j]})
        cost = c5.get(k, (None,))[0]
        if cost is None and k in c4:
            cost = c4[k][0] * cfg["aa_cost_v432_to_v5"]
            flags.append("cost est. (v4.3.2 × 2)")
        m = {"key": k, "model": e["base_name"], "lab": e.get("org") or "", "open_weights": open_w, "size_class": sz or "",
             "params_total_b": fnum(e.get("params_total_b")), "params_active_b": fnum(e.get("params_active_b")),
             "release_date": e.get("release_date") or "", "tiers": tiers, "effort": aa.get(k, (None, ""))[1] or "",
             "n_sources": int(O[i].sum()), "n_orgs": n_orgs, "sources": [ids[j] for j in range(len(ids)) if O[i, j]],
             "cost_per_task": cost, "e2e_s": e2e.get(k, (None,))[0], "flags": flags, "note": e.get("note", ""),
             "evidence": e.get("evidence", ""), "pinned": k in pins}
        for cat in cfg["categories"]:
            s, sd, cov = res[cat]
            m[cat] = round(float(s[i]), 1) if cov[i] > 0 else None     # no source for this category: blank
            m[cat + "_band"] = round(float(1.645 * sd[i]), 1) if cov[i] > 0 else None
            m[cat + "_sd"] = float(sd[i])
            m[cat + "_cov"] = round(float(cov[i]), 2)
        models.append(m)

    # tier tables
    tiers = {t: [] for t in cfg["tiers"]["order"] + ["oss-unknown-size"]}
    for m in models:
        for t in m["tiers"]:
            tiers.setdefault(t, []).append(m)
    # superseded: a newer model from the same lab (same licence; for open models the same size tier) that is either
    # the same product line at about the same size (name without version numbers, e.g. GPT-6 Sol -> GPT-6.1 Sol,
    # Qwen3.5 35B A3B -> Qwen3.6 35B A3B; replaces it even if it scores lower: we track the current release),
    # or scores higher and is not dearer
    line = lambda m: re.sub(r"[\d.]+", "", m["model"].lower()).strip()
    for m in models:
        if m["pinned"] or not m["lab"]:
            continue
        for o in models:
            if o is m or o["lab"] != m["lab"] or o["open_weights"] != m["open_weights"] \
                    or o["release_date"] <= m["release_date"]:
                continue
            if m["open_weights"] and o["tiers"][0] != m["tiers"][0]:
                continue
            cheaper = m["cost_per_task"] is not None and o["cost_per_task"] is not None \
                and o["cost_per_task"] <= m["cost_per_task"] * 1.1
            pm, po = m["params_total_b"], o["params_total_b"]
            same_size = pm is None or po is None or abs(pm - po) <= 0.25 * max(pm, po)
            if (line(o) == line(m) and same_size) or (cheaper and o["overall"] > m["overall"]):
                m["superseded_by"] = o["model"]
                break
    tables = {}
    moe = lambda m: m["params_active_b"] and m["params_total_b"] and \
        m["params_active_b"] <= cfg["tiers"]["moe_active_ratio"] * m["params_total_b"]
    for t, ms in tiers.items():
        ms = sorted(ms, key=lambda m: -m["overall"])
        live = [m for m in ms if t == "top-sota" or not m.get("superseded_by")]
        old = [m for m in ms if m not in live]
        bands = rank_bands(np.array([m["overall"] for m in live]), np.array([m["overall_sd"] for m in live]))
        rows_t = [{**m, "rank": i, "rank_band": f"{b[0]}–{b[1]}" if b[0] != b[1] else str(b[0])}
                  for i, (m, b) in enumerate(zip(live, bands), 1)]
        rows_t += [{**m, "rank": None, "rank_band": "", "flags": m["flags"] + [f"superseded by {m['superseded_by']}"]}
                   for m in old]
        n_show = cfg["tiers"]["show_per_tier"].get(t, 8)
        shown = [x for x in rows_t if x["rank"] and (x["rank"] <= n_show or x["pinned"])]
        extra = [x for x in rows_t if x["rank"] and x not in shown and moe(x)][:cfg["tiers"].get("moe_extra", {}).get(t, 0)]
        for x in extra:
            x["flags"] = x["flags"] + ["shown as best fast MoE"]
        tables[t] = sorted(shown + extra, key=lambda x: x["rank"])
        tables[t + ":all"] = rows_t

    os.makedirs(out_dir, exist_ok=True)
    write_csv(os.path.join(out_dir, "ratings_v7.csv"), models, cfg)
    meta = {"today": today.isoformat(), "population": len(pop), "superseded": len(superseded), "cutoff": cutoff,
            "calibration": cal,
            "method": method, "data_dates": data_dates(rows),
            "fit_sources": {ids[j]: int(O[:, j].sum()) for j in range(len(ids))}}
    seen = {}
    for r in rows:                       # names no source could match to the registry: new releases show up here
        if not r["base_key"] and r["source"] not in ("aa_trends",):
            seen.setdefault(norm_key(r["base_name"]), {"name": r["base_name"], "sources": set()})["sources"].add(r["source"])
    meta["unregistered"] = sorted(([v["name"], sorted(v["sources"])] for v in seen.values() if len(v["sources"]) >= 2),
                                  key=lambda x: -len(x[1]))
    write_md(os.path.join(out_dir, "TRACKED.md"), tables, watch, meta, cfg)
    write_xlsx(os.path.join(out_dir, "model_ratings_v7.xlsx"), tables, watch, meta, cfg)
    json.dump(meta, open(os.path.join(out_dir, "rating_meta_v7.json"), "w"), indent=1, default=str)
    print(f"rated {len(pop)} models ({len(superseded)} superseded builds hidden) · "
          + " · ".join(f"{t} {len(tables[t + ':all'])}" for t in cfg["tiers"]["order"]))
    for cat, mm in method.items():
        print(f"  {cat:<13} {mm['how']}")
    return tables, meta


def data_dates(rows):
    d = {}
    for r in rows:
        k = r["source"] + ("/wayback" if r.get("wayback_capture") else "")
        d[k] = max(d.get(k, ""), r["date"])
    return dict(sorted(d.items()))


# ------------------------------------------------------------------ outputs
CATS = [("overall", "Overall"), ("coding", "Coding"), ("writing", "Writing"), ("reasoning", "Reasoning"),
        ("professional", "Professional")]


def fmt_params(m):
    t, a = m["params_total_b"], m["params_active_b"]
    if t is None:
        return ""
    s = f"{t:g}B"
    return s + (f" A{a:g}B" if a else "")


def write_csv(path, models, cfg):
    keys = ["model", "lab", "tiers", "open_weights", "size_class", "params_total_b", "params_active_b", "release_date",
            "effort"] + [x for c in cfg["categories"] for x in (c, c + "_band", c + "_cov")] + \
           ["n_sources", "n_orgs", "sources", "cost_per_task", "e2e_s", "flags", "note"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore")
        w.writeheader()
        for m in sorted(models, key=lambda m: -m["overall"]):
            w.writerow({**m, "tiers": "|".join(m["tiers"]), "sources": "|".join(m["sources"]), "flags": "; ".join(m["flags"])})


TIER_TITLE = {"top-sota": "Top SOTA (any licence)", "closed-budget": "Closed budget", "large-oss": "Large open (> 150B)",
              "mid-oss": "Mid open (40–150B)", "small-oss": "Small open (15–40B)", "little-oss": "Little open (4.5–15B)",
              "tiny-oss": "Tiny open (< 4.5B)",
              "oss-unknown-size": "Open, size unknown"}


def write_md(path, tables, watch, meta, cfg):
    L = [f"# Tracked models · rating v7 · {meta['today']}", "",
         "Generated by `pipeline/rate.py`; edit `pipeline/tracked.csv` (pins, overrides, watch list), not this file.",
         "Scores: 50 = average model released in the last 12 months, 15 = one SD. ± is the 90 % band; models whose "
         "rank bands overlap are not separable. Data: Artificial Analysis, Epoch AI, Vals AI, LMArena/Arena, "
         "SemiAnalysis GDPx (see the workbook's Sources sheet).", ""]
    L.append("## Leaders\n\n| tier | #1 | #2 | #3 |\n|---|---|---|---|")
    for t in cfg["tiers"]["order"]:
        ms = tables.get(t, [])[:3]
        L.append(f"| {TIER_TITLE[t]} | " + " | ".join(f"{m['model']} {m['overall']:.0f}±{m['overall_band']:.0f}" for m in ms)
                 + " |" * (3 - len(ms) + 1))
    for t in cfg["tiers"]["order"] + ["oss-unknown-size"]:
        ms = tables.get(t, [])
        if not ms:
            continue
        L += ["", f"## {TIER_TITLE[t]}", "",
              "| # | rank band | model | lab | released | params | overall | coding | writing | reasoning | professional | sources | $/task | flags |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for m in ms:
            cost = "" if m["cost_per_task"] is None else f"{m['cost_per_task']:.2f}"
            L.append(f"| {m['rank'] or '–'} | {m['rank_band']} | {m['model']}{' 📌' if m['pinned'] else ''} | {m['lab']} | {m['release_date']} | "
                     f"{fmt_params(m)} | **{m['overall']:.0f}** ±{m['overall_band']:.0f} | "
                     + " | ".join("–" if m[c] is None else f"{m[c]:.0f}" for c, _ in CATS[1:])
                     + f" | {m['n_sources']} ({m['n_orgs']} orgs) | {cost} | " + "; ".join(m["flags"]) + " |")
    if watch:
        L += ["", "## Watch list (no usable data yet)", "", "| model | tier | lab | released | note | evidence |", "|---|---|---|---|---|---|"]
        for w in watch:
            L.append(f"| {w['model']} | {w.get('tier', '')} | {w.get('lab', '')} | {w.get('release_date', '')} | {w.get('note', '')} | {w.get('evidence', '')} |")
    if meta.get("unregistered"):
        L += ["", "## Seen in ≥ 2 sources but not in the registry", "",
              "New releases AA doesn't list yet, or name variants. Add an alias, or a `track` row in tracked.csv with lab, licence and size.", "",
              "| name | sources |", "|---|---|"]
        L += [f"| {n} | {', '.join(s)} |" for n, s in meta["unregistered"]]
    L += ["", "## Method notes", ""]
    for cat, mm in meta["method"].items():
        L.append(f"- **{cat}**: {mm['how']}. Org share: " + ", ".join(f"{o} {v:.0%}" for o, v in mm["org_mass"].items()))
    L.append("- AA fallbacks onto the v5 scale: " + "; ".join(f"{k} degree {v['deg']}, n={v['n']}, range {v['range']}, RMSE {v['rmse']}"
                                                              for k, v in meta["calibration"].items()) + ".")
    L.append(f"- Population: {meta['population']} models (released since {meta['cutoff']}, or pinned); "
             f"{meta['superseded']} superseded builds hidden.")
    L.append("- Data dates: " + ", ".join(f"{k} {v}" for k, v in meta["data_dates"].items()))
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def write_xlsx(path, tables, watch, meta, cfg):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    bold, head_fill = Font(bold=True), PatternFill("solid", fgColor="DDE4EE")
    ws = wb.active
    ws.title = "Overview"
    ws.append([f"Model ratings v7 · {meta['today']}"]); ws["A1"].font = Font(bold=True, size=14)
    ws.append(["50 = average model released in the last 12 months, 15 = 1 SD. ± = 90 % band. Overlapping rank bands = not separable. "
               "Generated by pipeline/rate.py; edit pipeline/tracked.csv and rating_config.json, not this file."])
    ws.append([])
    ws.append(["Tier", "#1", "", "#2", "", "#3", ""])
    for c in ws[4]:
        c.font, c.fill = bold, head_fill
    for t in cfg["tiers"]["order"]:
        row = [TIER_TITLE[t]]
        for m in tables.get(t, [])[:3]:
            row += [m["model"], f"{m['overall']:.0f} ±{m['overall_band']:.0f}"]
        ws.append(row)
    widths = {"A": 26, "B": 26, "C": 10, "D": 26, "E": 10, "F": 26, "G": 10}
    for k, v in widths.items():
        ws.column_dimensions[k].width = v

    hdr = ["#", "Rank band", "Model", "Lab", "Released", "Params", "Effort", "Overall", "±"] + \
          [n for _, n in CATS[1:]] + ["Sources", "Orgs", "$/task", "E2E (s)", "Flags", "Note"]
    for t in cfg["tiers"]["order"] + ["oss-unknown-size"]:
        ms = tables.get(t + ":all", [])
        if not ms:
            continue
        ws = wb.create_sheet(t)
        ws.append([TIER_TITLE[t]]); ws["A1"].font = Font(bold=True, size=13)
        ws.append([f"Showing every rated model in this tier; the first {cfg['tiers']['show_per_tier'].get(t, 8)} (+ pinned) are the tracked set."])
        ws.append(hdr)
        for c in ws[3]:
            c.font, c.fill = bold, head_fill
        shown = {m["key"] for m in tables.get(t, [])}
        for m in ms:
            ws.append([m["rank"], m["rank_band"], m["model"], m["lab"], m["release_date"], fmt_params(m), m["effort"],
                       m["overall"], m["overall_band"]] + [m[c] for c, _ in CATS[1:]] +
                      [m["n_sources"], m["n_orgs"], None if m["cost_per_task"] is None else round(m["cost_per_task"], 3),
                       m["e2e_s"], "; ".join(m["flags"]), m["note"]])
            if m["key"] not in shown:
                for c in ws[ws.max_row]:
                    c.font = Font(color="888888")
        for i, wdt in enumerate([4, 9, 30, 16, 11, 13, 9, 8, 6, 8, 8, 9, 11, 8, 6, 8, 8, 40, 50], 1):
            ws.column_dimensions[get_column_letter(i)].width = wdt
        ws.freeze_panes = "D4"

    ws = wb.create_sheet("Watch")
    ws.append(["model", "status", "tier", "lab", "release_date", "note", "evidence", "checked"])
    for c in ws[1]:
        c.font, c.fill = bold, head_fill
    for w in watch:
        ws.append([w.get(k) for k in ["model", "status", "tier", "lab", "release_date", "note", "evidence", "checked"]])
    ws.column_dimensions["A"].width, ws.column_dimensions["F"].width, ws.column_dimensions["G"].width = 22, 70, 50

    ws = wb.create_sheet("Method")
    ws.append(["Category", "Fit", "Source", "Relevance (after org cap)", "Reliability λ²/(λ²+ψ)"])
    for c in ws[1]:
        c.font, c.fill = bold, head_fill
    for cat, mm in meta["method"].items():
        for sid, wgt in mm["weights"].items():
            ws.append([cat, mm["how"], sid, wgt, mm["reliability"][sid]])
        ws.append([cat, "org share", ", ".join(f"{o} {v:.0%}" for o, v in mm["org_mass"].items())])
    ws.append([])
    ws.append(["AA fallback calibration (onto v5)", json.dumps(meta["calibration"])])
    ws.append(["Models with a value per source (population)", json.dumps(meta["fit_sources"])])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width, ws.column_dimensions["C"].width = 14, 46, 60

    ws = wb.create_sheet("Sources")
    ws.append(["Source", "Latest data date", "Owner / attribution"])
    for c in ws[1]:
        c.font, c.fill = bold, head_fill
    owner = {"aa_": "Artificial Analysis — artificialanalysis.ai", "epoch": "Epoch AI — epoch.ai", "vals": "Vals AI — vals.ai",
             "lmarena": "LMArena / Arena — arena.ai", "arena": "LMArena / Arena — arena.ai", "gdpx": "SemiAnalysis GDPx — gdpx.semianalysis.com"}
    for k, v in meta["data_dates"].items():
        ws.append([k, v, next((o for p, o in owner.items() if k.startswith(p)), "")])
    ws.column_dimensions["A"].width, ws.column_dimensions["C"].width = 30, 50
    for s in wb.worksheets:
        for row in s.iter_rows():
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=isinstance(c.value, str) and len(c.value) > 60)
    wb.save(path)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2 or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    main(a[0], a[1], opt("--config", os.path.join(HERE, "rating_config.json")),
         opt("--tracked", os.path.join(HERE, "tracked.csv")), date.fromisoformat(opt("--today", date.today().isoformat())))
