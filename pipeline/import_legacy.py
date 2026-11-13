#!/usr/bin/env python3
"""model-ratings-pipeline · import_legacy.py

Turns the data already on disk into standard envelopes, so normalize.py and rate.py can run without a new
browser refresh:

    uv run python -I pipeline/import_legacy.py OUT_DIR [--archive aa-archive/aa_archive_2026-10-28.xlsx]
                                                        [--v6 ratings/model_ratings_v6.xlsx]

From the AA archive (built 2026-10-28; attribution: Artificial Analysis):
    aa_trends       registry backbone: 716 variants, release date, total/active params, size class, open weights,
                    Progress Index v1
    aa_leaderboard  live (v5): Intelligence Index v5, cost per task, prices, speed, ~38 benchmarks (bench.*)
    aa_leaderboard  Wayback 2026-10-28 01:03:49 (v4.3.2 final), with the pre-v5 versions of the 4 changed benchmarks
From the v6 workbook's Raw Data sheet (blue cells = values copied from the sources, dated per its Sources sheet):
    lmarena_text    creative-writing and instruction-following Elo ± CI
    arena_agent     code / chat / work net improvement ± CI
    vals            Vals Index v2.2 (+ components) and Science Index
    epoch_eci       ECI
    aa_personality  length-adjusted slop residual and sycophancy Elo (v6 derived values)
These are the same source ids and metric names extractors.js produces, so live refreshes append to the same
columns. Every envelope carries notes.imported_from.
"""
import json, os, re, sys
from datetime import datetime

import openpyxl

V432_CAPTURE = "20261028010349"
V5_RETRIEVED = "2026-10-28T20:26:13Z"
TRENDS_RETRIEVED = "2026-10-28T20:26:57Z"


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def yes(x):
    return str(x).strip().lower() in ("yes", "true", "1")


def env(source, category, records, retrieved, page, src_file, wayback=None, notes=None):
    return {"extractor_version": "import_legacy 1.0", "source": source, "category": category, "page": page,
            "wayback_capture": wayback, "retrieved": retrieved, "n": len(records),
            "notes": {"imported_from": os.path.basename(src_file), **(notes or {})}, "records": records}


def sheet(wb, name):
    rows = list(wb[name].iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:] if r and r[0] is not None]


def archive(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    models = sheet(wb, "Models")
    bench = {r["Slug"]: r for r in sheet(wb, "Benchmarks")}
    changed = {k.replace(" (pre-v5)", "") for r in bench.values() for k in r if "(pre-v5)" in str(k)}
    trends, live, wb432 = [], [], []
    for m in models:
        if not m.get("Model"):
            continue
        base = {"model": m["Model"], "key": m["Slug"], "org": m["Creator"]}
        attrs = {"release_date": str(m["Release date"])[:10] if m["Release date"] else None,
                 "params_total_b": num(m["Total params (B)"]), "params_active_b": num(m["Active params (B)"]),
                 "open_weights": yes(m["Open weights"]), "licence": m["Licence category"],
                 "size_class": m["Size class"], "reasoning": yes(m["Reasoning"]),
                 "context": num(m["Context (tokens)"]), "deprecated": yes(m["Deprecated"])}
        trends.append({**base, "metrics": {"progress_index": num(m["Progress Index v1"])}, "ci": {}, "attrs": attrs,
                       "flags": []})
        b = bench.get(m["Slug"], {})
        cur = {f"bench.{k.replace(' (Elo)', '')}": num(v) for k, v in b.items()
               if k not in ("Slug", "Model") and "(pre-v5)" not in str(k)}
        speed = {"price_in": num(m["Price input ($/1M)"]), "price_out": num(m["Price output ($/1M)"]),
                 "cache_hit_price": num(m["Cache hit ($/1M)"]), "tokens_per_s": num(m["Output tokens / s"]),
                 "ttft_s": num(m["Time to first token (s)"]), "e2e_s": num(m["End-to-end response (s)"]),
                 "reasoning_s": num(m["Reasoning time (s)"])}
        if num(m["Intelligence Index v5"]) is not None:
            live.append({**base, "metrics": {"intelligence_index": num(m["Intelligence Index v5"]),
                                             "cost_per_task": num(m["v5 cost / index task ($)"]), **speed, **cur},
                         "ci": {}, "attrs": attrs, "flags": ["index_estimated"] if yes(m["v5 estimated by AA?"]) else []})
        if num(m["Intelligence Index v4.3.2 (final)"]) is not None:
            old = {k: v for k, v in cur.items() if k[6:] not in changed}
            old.update({f"bench.{k.replace(' (pre-v5)', '').replace(' (Elo)', '')}": num(v) for k, v in b.items()
                        if "(pre-v5)" in str(k)})
            wb432.append({**base, "metrics": {"intelligence_index": num(m["Intelligence Index v4.3.2 (final)"]),
                                              "cost_per_task": num(m["v4.3.2 cost / index task ($)"]), **old},
                          "ci": {}, "attrs": attrs,
                          "flags": ["index_estimated"] if yes(m["v4.3.2 estimated by AA?"]) else []})
    lb = "https://artificialanalysis.ai/leaderboards/models"
    return [env("aa_trends", "progress", trends, TRENDS_RETRIEVED, "https://artificialanalysis.ai/trends", path),
            env("aa_leaderboard", "llm", live, V5_RETRIEVED, lb, path, notes={"index_version": "v5"}),
            env("aa_leaderboard", "llm", wb432, f"{V432_CAPTURE[:4]}-{V432_CAPTURE[4:6]}-{V432_CAPTURE[6:8]}T01:03:49Z",
                f"https://web.archive.org/web/{V432_CAPTURE}/{lb}", path, wayback=V432_CAPTURE,
                notes={"index_version": "v4.3.2"})]


V6_SOURCES = {   # (source, category, metric, value column, ± column or None, data date, page)
    "cw": ("lmarena_text", "creative-writing", "elo", "LMArena Creative Writing Elo", "CW ±", "2026-10-23",
           "https://arena.ai/leaderboard/chat/text/creative-writing"),
    "if": ("lmarena_text", "instruction-following", "elo", "LMArena Instruction Following Elo", "IF ±", "2026-10-23",
           "https://arena.ai/leaderboard/chat/text/instruction-following"),
    "code": ("arena_agent", "code", "net_improvement", "Arena Agent Code %", "Code ±", "2026-10-23",
             "https://arena.ai/leaderboard/agent/code"),
    "chat": ("arena_agent", "chat", "net_improvement", "Arena Agent Chat %", "Chat ±", "2026-10-23",
             "https://arena.ai/leaderboard/agent/chat"),
    "work": ("arena_agent", "work", "net_improvement", "Arena Agent Work %", "Work ±", "2026-10-23",
             "https://arena.ai/leaderboard/agent/work"),
    "vals": ("vals", "vals_index", "accuracy", "Vals Index v2.2", None, "2026-10-24",
             "https://www.vals.ai/benchmarks/vals_index"),
    "sci": ("vals", "science_index", "accuracy", "Vals Science Index", None, "2026-10-21",
            "https://www.vals.ai/benchmarks/science_index"),
    "eci": ("epoch_eci", "eci", "eci", "Epoch ECI", None, "2026-10-25", "https://epoch.ai/eci"),
    "slop": ("aa_personality", "personality", "slop_residual", "Slop residual (Elo)", "Slop ±", "2026-10-26",
             "https://artificialanalysis.ai/evaluations/aa-personalitybench"),
    "syc": ("aa_personality", "personality", "trait.sycophancy", "Sycophancy Elo", "Syc ±", "2026-10-26",
            "https://artificialanalysis.ai/evaluations/aa-personalitybench"),
}
VALS_COMPONENTS = ["Vals Finance Agent", "Vals EMB", "Vals Terminal-Bench 4", "Vals Vibe Code", "Vals Code Migration",
                   "Vals Legal Research", "Vals HLAB", "Vals Tax"]


def v6(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [r for r in sheet(wb, "Raw Data") if r.get("Base model")]
    groups = {}
    for r in rows:
        name = r["Model"]
        if r["Model"] == r["Base model"] and r.get("Effort"):
            name = f'{r["Base model"]} ({r["Effort"]})'
        for key, (src, cat, metric, col, pm, date, page) in V6_SOURCES.items():
            v = num(r.get(col))
            if v is None:
                continue
            rec = {"model": name, "key": None, "org": r.get("Lab"), "metrics": {metric: v}, "ci": {},
                   "attrs": {"licence": r.get("Licence")}, "flags": []}
            if pm and num(r.get(pm)) is not None:
                rec["ci"][metric] = [v - r[pm], v + r[pm]]
            if src == "arena_agent" and str(r.get("Arena Agent Preliminary") or "").strip().lower() in ("yes", "true", "1"):
                rec["flags"].append("preliminary")
            if key == "vals":
                rec["metrics"].update({f"component.{c[5:]}": num(r.get(c)) for c in VALS_COMPONENTS
                                       if num(r.get(c)) is not None})
            recs = groups.setdefault((src, cat, date, page), {})
            if name in recs:                 # one record per model: merge metrics of the same envelope
                for k in ("metrics", "ci"):
                    recs[name][k].update(rec[k])
                recs[name]["flags"] = sorted(set(recs[name]["flags"]) | set(rec["flags"]))
            else:
                recs[name] = rec
    groups = {k: list(v.values()) for k, v in groups.items()}
    return [env(src, cat, recs, f"{date}T00:00:00Z", page, path) for (src, cat, date, page), recs in groups.items()]


def main(out_dir, archive_path, v6_path):
    os.makedirs(out_dir, exist_ok=True)
    envs = archive(archive_path) + (v6(v6_path) if v6_path else [])
    for e in envs:
        tag = re.sub(r"\D", "", e["wayback_capture"] or e["retrieved"])[:8]
        name = f'{e["source"]}_{e["category"]}_{tag}{"_wayback" if e["wayback_capture"] else ""}.json'
        json.dump(e, open(os.path.join(out_dir, name), "w"), indent=1)
        print(f"  {name:<55} {e['n']:>4} records")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    main(a[0], opt("--archive", "aa-archive/aa_archive_2026-10-28.xlsx"), opt("--v6", "ratings/model_ratings_v6.xlsx"))
