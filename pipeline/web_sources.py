#!/usr/bin/env python3
"""model-ratings-pipeline · web_sources.py — shell fetchers for leaderboards that publish their data in the page.

    python3 -I pipeline/web_sources.py OUT_DIR [--raw RAW_DIR] [--only id,id]

Writes standard envelopes (same format as extractors.js) named <source>_<category>_<YYYYMMDD>.json. With --raw,
each downloaded file is also kept under RAW_DIR/<source>/. Downloads are parsed as data only, never executed.

| id          | page                                    | metric                         | CI          |
|-------------|-----------------------------------------|--------------------------------|-------------|
| tbench      | tbench.ai/leaderboard (Terminal-Bench)  | accuracy % (330 trials)        | 95 % ±      |
| scale       | labs.scale.com/leaderboard/<board>      | score (SWE Atlas, RLI, HLE, MultiChallenge) | ± where published |
| apex        | mercor.com/apex/<board>                 | APEX-Agents pass@1, APEX-v1 mean score, APEX-SWE pass@1 | ± |
| weirdml     | htihle.github.io (WeirdML v3)           | score %                        | 95 % interval |
| matharena   | matharena.ai/models                     | expected performance % (IRT)   | 95 % ±      |
| lechmazur   | github.com/lechmazur/writing            | Thurstone rating               | 95 % bootstrap |
| simplebench | simple-bench.com                        | score %                        | none        |

Harness caveat: Terminal-Bench, WeirdML and APEX run each model inside an agent harness (often the lab's own),
so the score is model + harness. Judge caveats: APEX uses LLM judges over expert rubrics; Lech Mazur's judge
panel includes frontier models. Scale and Mercor both sell training data to labs (Meta owns a stake in Scale).
"""
import csv, io, json, os, re, sys, urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (model-ratings-pipeline)"}
EFF = {"max": "Max", "xhigh": "xHigh", "high": "High", "medium": "Medium", "low": "Low", "minimal": "Minimal",
       "none": "Non-reasoning", "non-reasoning": "Non-reasoning"}
CLAUDE = re.compile(r"^(opus|sonnet|haiku|fable|mythos)\b", re.I)
RAW = None


def get(url, name=None, source=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        body = r.read().decode("utf-8", "replace")
    if RAW and source:
        os.makedirs(os.path.join(RAW, source), exist_ok=True)
        open(os.path.join(RAW, source, name or re.sub(r"\W+", "_", url)[-80:]), "w", encoding="utf-8").write(body)
    return body


def next_f(html):
    parts = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html, re.S)
    return "".join(json.loads(p) for p in parts)


def grab(text, key):
    dec, i, out = json.JSONDecoder(), 0, []
    while (i := text.find(key, i)) >= 0:
        try:
            v, i = dec.raw_decode(text, i + len(key))
            out.append(v)
        except ValueError:
            i += 1
    return out


def canon(name, org="", effort=None):
    """Source name → 'Family Model (Effort)' so normalize.py can match it."""
    n = re.sub(r"\s+", " ", (name or "").strip())
    if re.fullmatch(r"[a-z0-9.\-]+", n) and "-" in n:            # slug: claude-fable-5-1-high
        toks = n.split("-")
        if toks[-1] in EFF and effort is None:
            effort = toks.pop()
        out = []
        for t in toks:
            if out and t.isdigit() and re.fullmatch(r"\d+(\.\d+)?", out[-1]) and len(t) <= 2:
                out[-1] += "." + t                               # 5 1 -> 5.1
            else:
                out.append(t)
        n = " ".join(out)
    if CLAUDE.match(n) or (org.lower() in ("anthropic", "claude") and not n.lower().startswith("claude")):
        n = "Claude " + n
    e = EFF.get(str(effort).strip().lower()) if effort else None
    if e and not re.search(r"\([^)]*\)\s*$", n):
        n = f"{n} ({e})"
    return n


def rec(model, metrics, ci=None, org=None, flags=None, **attrs):
    return {"model": model, "key": None, "org": org, "metrics": metrics, "ci": ci or {}, "attrs": attrs, "flags": flags or []}


def env(source, category, records, page, notes=None, data_date=None):
    return {"extractor_version": "web_sources 1.0", "source": source, "category": category, "page": page,
            "wayback_capture": None, "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n": len(records), "notes": {"data_date": data_date, **(notes or {})}, "records": records}


# ------------------------------------------------------------------ sources
def tbench():
    page = "https://www.tbench.ai/leaderboard"
    rows = [r for v in grab(next_f(get(page, "leaderboard.html", "tbench")), '"rows":') if isinstance(v, list)
            for r in v if isinstance(r, dict) and "metrics" in r]
    seen, out = set(), []
    for r in rows:
        md, m = r["metadata"], r["metrics"]
        name = canon(md["model_display"]["label"], md.get("model_org", {}).get("label", ""), md.get("reasoning_effort"))
        harness = md.get("agent_display", {}).get("label")
        if (name, harness) in seen:
            continue
        seen.add((name, harness))
        hw = m.get("accuracy_ci95_half_width")
        out.append(rec(name, {"accuracy": m["accuracy"], "total_cost_usd": m.get("total_cost_usd")},
                       {"accuracy": [m["accuracy"] - hw, m["accuracy"] + hw]} if hw is not None else {},
                       md.get("model_org", {}).get("label"), harness=harness, n_trials=m.get("n_trials")))
    best = {}
    for x in out:   # one row per model × effort: keep the best harness, record the others in attrs
        k = x["model"]
        if k not in best or x["metrics"]["accuracy"] > best[k]["metrics"]["accuracy"]:
            best[k] = x
    date = max((r.get("updated_at", "") for r in rows), default="")[:10]
    return [env("tbench", "terminal-bench", list(best.values()), page, {"note": "best harness per model kept"}, date)]


SCALE = {"swe-atlas": ("overall", "coding"), "rli": ("main", "professional"), "hle-diamond": ("main", "reasoning"),
         "multichallenge": ("large", "writing")}


def scale():
    envs = []
    for board, (variant, _) in SCALE.items():
        page = f"https://labs.scale.com/leaderboard/{board}"
        t = next_f(get(page, f"{board}.html", "scale"))
        vs = [x for v in grab(t, '"variants":') if isinstance(v, list) for x in v if isinstance(x, dict)]
        if not vs:
            ents = [e for e in grab(t, '"entries":') if e and isinstance(e, list) and isinstance(e[0], dict) and "model" in e[0]]
            vs = [{"key": "main", "entries": ents[0]}] if ents else []
        v = next((x for x in vs if x.get("key") == variant), vs[0] if vs else None)
        if not v:
            print(f"  scale/{board}: no data found", file=sys.stderr)
            continue
        recs = []
        for e in v["entries"]:
            if e.get("deprecated"):
                continue
            s, hw = e.get("score"), e.get("confidenceInterval_upper")
            flags = ["contamination_warning"] if e.get("contaminationMessage") else []
            recs.append(rec(canon(e["model"], e.get("company", "")), {"score": s},
                            {"score": [s - hw, s + hw]} if hw else {}, e.get("company"), flags, created=e.get("createdAt")))
        date = max((e.get("createdAt") or "" for e in v["entries"]), default="")[:10]
        envs.append(env("scale_seal", board, recs, page, {"variant": v.get("key")}, date))
    return envs


APEX = {"apex-agents": ("pass-1", "professional"), "apex-v1": ("mean-score", "professional"),
        "apex-swe": ("pass-1", "coding")}


def apex():
    envs = []
    for board, (metric, _) in APEX.items():
        page = f"https://www.mercor.com/apex/{board}-leaderboard/"
        h = get(page, f"{board}.html", "apex")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        rows = json.loads(m.group(1))["props"]["pageProps"]["leaderboardData"]
        recs = []
        for r in rows:
            sc, er = r["score"].get(metric) or {}, r.get("error", {}).get(metric) or {}
            if not sc:
                continue
            harness, v = next(iter(sc.items()))
            hw = er.get(harness)
            recs.append(rec(canon(r["model_name"], r.get("company", ""), r.get("effort")), {"score": v},
                            {"score": [v - hw, v + hw]} if hw is not None else {}, r.get("providerName"),
                            harness=harness, release_date=r.get("release_date")))
        envs.append(env("mercor_apex", board, recs, page, {"metric": metric}))
    return envs


def weirdml():
    page = "https://htihle.github.io/weirdml.html"
    d = json.loads(get("https://htihle.github.io/assets/data/weirdml_v3.json", "weirdml_v3.json", "weirdml"))
    best = {}
    for m in d["models"]:
        if m.get("synthetic"):
            continue
        name = re.sub(r",\s*[A-Z][A-Za-z]+\)$", ")", m["name"])      # 'Kimi K3 (high, Fireworks)' -> 'Kimi K3 (high)'
        r = rec(name, {"score": 100 * m["score"], "mean_api_cost_usd": m.get("mean_api_cost_usd")},
                {"score": [100 * m["interval"][0], 100 * m["interval"][1]]} if m.get("interval") else {},
                None, harness=m.get("agent"), open_weights=m.get("open_weights"), provider_name=m["name"])
        if name not in best or r["metrics"]["score"] > best[name]["metrics"]["score"]:
            best[name] = r                                              # best inference provider per model
    recs = list(best.values())
    return [env("weirdml", "v3", recs, page, {"task_count": d.get("task_count")}, (d.get("generated") or "")[:10])]


def matharena():
    page = "https://matharena.ai/models"
    h = re.sub(r"\s+", " ", get(page, "models.html", "matharena"))
    recs = []
    for row in re.findall(r'<tr class="model-row".*?</tr>', h):
        name = re.search(r'class="model-link"[^>]*>([^<]+)</a>', row)
        acc = re.search(r'metric-bar-cell--accuracy.*?metric-bar-value">\s*([\d.]+)%\s*(?:<span[^>]*>±([\d.]+)%)?', row)
        org = re.search(r'data-creator-display="([^"]*)"', row)
        if not (name and acc):
            continue
        v, hw = float(acc.group(1)), float(acc.group(2)) if acc.group(2) else None
        nm = name.group(1).strip()
        nm = re.sub(r"\(([a-z]+)\)$", lambda m: f"({EFF.get(m.group(1), m.group(1))})", nm)
        recs.append(rec(canon(nm, org.group(1) if org else ""), {"expected_performance": v},
                        {"expected_performance": [v - hw, v + hw]} if hw else {}, org.group(1) if org else None))
    return [env("matharena", "models", recs, page)]


LECH = "https://raw.githubusercontent.com/lechmazur/writing/main/data/writing_kimi_k31_depth50_20261024/ratings.csv"


def lechmazur():
    rows = list(csv.DictReader(io.StringIO(get(LECH, "ratings.csv", "lechmazur"))))
    recs = [rec(canon(r["llm"]), {"thurstone": float(r["thurstone_rating"])},
                {"thurstone": [float(r["thurstone_ci95_low"]), float(r["thurstone_ci95_high"])]}) for r in rows]
    return [env("lechmazur_writing", "creative", recs, "https://github.com/lechmazur/writing",
                {"file": LECH.split("/main/")[1]}, "2026-10-24")]


def simplebench():
    page = "https://simple-bench.com"
    js = get("https://simple-bench.com/static/js/leaderboard-data.js", "leaderboard-data.js", "simplebench")
    recs, dates = [], []
    for m in re.finditer(r'model:\s*"([^"]+)",\s*score:\s*"([\d.]+)%",\s*organization:\s*"([^"]*)",\s*dateAdded:\s*(null|"[^"]*")', js):
        if not m.group(3):
            continue                                   # human baseline rows
        recs.append(rec(canon(m.group(1), m.group(3)), {"score": float(m.group(2))}, org=m.group(3)))
        if m.group(4) != "null":
            dates.append(m.group(4).strip('"'))
    return [env("simplebench", "main", recs, page, data_date=max(dates, default=None))]


SOURCES = {"tbench": tbench, "scale": scale, "apex": apex, "weirdml": weirdml, "matharena": matharena,
           "lechmazur": lechmazur, "simplebench": simplebench}


def main(out_dir, only=None):
    os.makedirs(out_dir, exist_ok=True)
    for sid, fn in SOURCES.items():
        if only and sid not in only:
            continue
        try:
            envs = fn()
        except Exception as e:                           # one broken site must not stop the others
            print(f"  {sid}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
            continue
        for e in envs:
            tag = (e["notes"].get("data_date") or e["retrieved"])[:10].replace("-", "")
            name = f'{e["source"]}_{e["category"]}_{tag}.json'
            json.dump(e, open(os.path.join(out_dir, name), "w"), indent=1)
            print(f"  {name:<48} {e['n']:>4} records")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    if "--raw" in a:
        RAW = a[a.index("--raw") + 1]
    main(a[0], set(a[a.index("--only") + 1].split(",")) if "--only" in a else None)
