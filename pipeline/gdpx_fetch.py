#!/usr/bin/env python3
"""model-ratings-pipeline · gdpx_fetch.py

Fetches SemiAnalysis GDPx (gdpx.semianalysis.com) and writes standard envelopes for normalize.py.

    python3 -I gdpx_fetch.py OUT_DIR [--raw RAW_DIR]

GDPx ships its whole dataset inside one Next.js JS chunk (JSON.parse('{"updatedAt":…,"results":[…]}')),
so no browser is needed: the shell can reach the site. Per model × partner the data has the default score,
the partial score, cost and output tokens per task, and task counts. Partners map to 11 domains.

Aggregation copies the site's own code (checked against the rendered page on 2026-11-13):
    domain score    = mean of that domain's partner scores (partners without a score are skipped)
    composite score = mean of the domain scores
    cost / tokens   = mean of the partner values, weighted by tasks with cost / tokens;
                      the composite uses the site's "overall" cost and tokens instead
"Partial" uses the continuous score for binary tasks when one exists; otherwise it equals the default score.

Writes one envelope per category, named gdpx_<category>_<YYYYMMDD>.json:
    composite                   all 11 domains (the site's headline "GDPx" number)
    composite_ex_safety         without biology, cybersecurity and alignment (the site's
                                "without-safety-classifiers" view: domains where safety classifiers can block runs)
    <domain slug>               one per domain, e.g. cybersecurity
    <domain>.<partner>          one per partner, only for domains with several partners
                                (chip-design, materials-science), for finer analysis
Model names carry the reasoning setting GDPx used, e.g. "Claude Opus 5.5 (Max)". GDPx's "Highest"
means the model's top setting, so it is left unlabelled and normalize.py maps it to the top effort.
Every model runs in its own lab's agent harness (Claude Code, Codex, …), recorded in attrs.harness.
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone

BASE = "https://gdpx.semianalysis.com"
PAGE = BASE + "/"
UA = {"User-Agent": "model-ratings-pipeline/1.0"}
SAFETY = ["biology", "cybersecurity", "alignment"]      # the site's own list (variable S in the bundle)
VERSION = "1.0"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8")


def js_string(s):
    """Decode the body of a single-quoted JS string literal."""
    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)",
                  lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] in "ux" and len(m.group(1)) > 1
                  else {"n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), m.group(1)), s)


def fetch(raw_dir=None):
    page = get(PAGE)
    chunks = sorted(set(re.findall(r'/_next/static/[^"\']+?\.js', page)))
    for c in chunks:
        js = get(BASE + c)
        m = re.search(r"JSON\.parse\('((?:[^'\\]|\\.)*\"results\"(?:[^'\\]|\\.)*)'\)", js)
        if not m:
            continue
        data = json.loads(js_string(m.group(1)))
        domains = dict(re.findall(r'\{slug:"([^"]+)",name:"([^"]+)"', js))
        partners = {p: (n, d) for p, n, d in re.findall(r'a\("([^"]+)","([^"]+)","([^"]+)"', js)}
        if not domains or not partners:
            sys.exit(f"found the data in {c} but not the domain/partner lists; the bundle layout changed")
        if raw_dir:
            os.makedirs(raw_dir, exist_ok=True)
            json.dump({"chunk": c, "data": data, "domains": domains, "partners": partners},
                      open(os.path.join(raw_dir, f"gdpx_raw_{data['updatedAt'].replace('-', '')}.json"), "w"), indent=1)
        return data, domains, partners
    sys.exit(f"no GDPx data in {len(chunks)} JS chunks; the site layout changed")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def wmean(rows, val, w):
    rows = [r for r in rows if r[val] is not None and r[w] > 0]
    tot = sum(r[w] for r in rows)
    return sum(r[val] * r[w] for r in rows) / tot if tot else None


def score(r, metric):
    if metric == "partial":
        return r["partialScore"] if r["tasksWithPartial"] else None
    return r["score"] if r["tasksScored"] else None


def r4(x):
    return None if x is None else round(x, 4)


def build(data, domains, partners):
    res = {(r["modelId"], r["partnerId"]): r for r in data["results"]}
    by_domain = {d: [p for p, (_, pd) in partners.items() if pd == d] for d in domains}
    out = {}

    def agg(mid, doms):
        rows = [res[(mid, p)] for d in doms for p in by_domain[d] if (mid, p) in res]
        if not rows:
            return None
        dom = {m: [mean(score(res[(mid, p)], m) for p in by_domain[d] if (mid, p) in res) for d in doms]
               for m in ("score", "partial")}
        return {"score": r4(mean(dom["score"])), "partial_score": r4(mean(dom["partial"])),
                "cost_per_task": r4(wmean(rows, "costPerTask", "tasksWithCost")),
                "tokens_per_task": r4(wmean(rows, "tokensPerTask", "tasksWithTokens")),
                "tasks": sum(r["tasks"] for r in rows), "tasks_scored": sum(r["tasksScored"] for r in rows),
                "domains_scored": sum(v is not None for v in dom["score"])}

    def record(m, metrics, **attrs):
        name = m["name"] if m["reasoning"] in ("Highest", None, "") else f'{m["name"]} ({m["reasoning"]})'
        return {"model": name, "key": m["id"], "org": m["lab"], "metrics": metrics, "ci": {},
                "attrs": {"harness": m["harness"], "reasoning": m["reasoning"], "open_weights": m["openWeights"], **attrs},
                "flags": []}

    views = {"composite": list(domains), "composite_ex_safety": [d for d in domains if d not in SAFETY]}
    views.update({d: [d] for d in domains})
    for cat, doms in views.items():
        recs = []
        for m in data["models"]:
            a = agg(m["id"], doms)
            if a is None:
                continue
            if cat == "composite":           # the site shows its precomputed overall cost/tokens here
                o = data.get("overall", {}).get(m["id"]) or {}
                a["cost_per_task"], a["tokens_per_task"] = o.get("costPerTask"), o.get("tokensPerTask")
            recs.append(record(m, a, domains=doms if cat.startswith("composite") else None))
        out[cat] = recs
    names = {m["id"]: m for m in data["models"]}
    for d, ps in by_domain.items():        # one envelope per partner, only where a domain has several
        if len(ps) < 2:
            continue
        for p in ps:
            out[f"{d}.{p}"] = [record(names[r["modelId"]],
                                      {"score": score(r, "score"), "partial_score": score(r, "partial"),
                                       "cost_per_task": r["costPerTask"], "tokens_per_task": r["tokensPerTask"],
                                       "tasks": r["tasks"], "tasks_scored": r["tasksScored"]},
                                      partner=r["partnerId"], domain=d)
                               for r in data["results"] if r["partnerId"] == p and r["modelId"] in names]
    return out


def main(out_dir, raw_dir=None):
    data, domains, partners = fetch(raw_dir)
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = data["updatedAt"].replace("-", "")
    envs = build(data, domains, partners)
    for cat, recs in envs.items():
        env = {"extractor_version": f"gdpx_fetch {VERSION}", "source": "gdpx", "category": cat, "page": PAGE,
               "wayback_capture": None, "retrieved": now, "n": len(recs),
               "notes": {"updated_at": data["updatedAt"], "data_source": data.get("source"),
                         "domains": domains, "unit": "percent of task credit, mean of 3 attempts"},
               "records": recs}
        json.dump(env, open(os.path.join(out_dir, f"gdpx_{cat}_{stamp}.json"), "w"), indent=1)
    print(f"GDPx {data['updatedAt']}: {len(data['models'])} models, {len(partners)} partners, "
          f"{len(domains)} domains → {len(envs)} envelopes in {out_dir}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    raw = a[a.index("--raw") + 1] if "--raw" in a else None
    main(a[0], raw)
