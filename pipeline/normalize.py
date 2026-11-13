#!/usr/bin/env python3
"""model-ratings-pipeline · normalize.py

Turns raw extractor envelopes (extractors.js output) into one long, append-only observations table.

    python3 -I normalize.py RAW_DIR OUT_DIR

RAW_DIR  folder of envelope files (searched recursively, e.g. data/envelopes/ with dated subfolders). Accepted forms: the plain JSON envelope (browser
         download) or an agent tool-result file ([{"type":"text","text": "<json string>"}]).
         AA trends envelope (Progress Index) is required: it is the model registry backbone.
OUT_DIR  receives
         observations.csv   one row per (source, category, metric, model variant) — appended, never overwritten
         registry.csv       canonical models: base, effort variants, org, release, params, open weights
         unmatched.csv      source names that could not be mapped (add them to aliases.json)
         snapshot_<date>.csv the rows added in this run

Matching: model names are split into a base name and an effort level, then the base is matched to the
registry by a normalised key (lowercase alphanumerics, 8-digit build dates shortened to MMDD), with
aliases.json for the rest. Sources without effort labels (Vals, Epoch) map to the model's top effort.
"""
import csv, json, os, re, sys
from datetime import datetime, timezone

EFFORTS = ["max", "xhigh", "high", "default", "reasoning", "medium", "low", "minimal", "non-reasoning"]   # top first
EFFORT_RE = {"max": "max", "xhigh": "xhigh", "x-high": "xhigh", "extra high": "xhigh", "high": "high",
             "medium": "medium", "low": "low", "minimal": "minimal",
             "non-reasoning": "non-reasoning", "nonreasoning": "non-reasoning", "non-thinking": "non-reasoning",
             "instant": "non-reasoning", "reasoning": "reasoning", "thinking": "reasoning",
             "default": "default"}
DROP_PART = re.compile(r"^(default fallback|with fallback|.*\bfallback|\d+k|nvfp4|mxfp4|fp8|fp4|bf16|int[48]|awq|gguf"
                       r"|novita|inferencenet|deepinfra|together|fireworks|openrouter|groq|cerebras|baseten|dsh)$", re.I)
                       # quantisation tags, token budgets, inference providers and harness tags inside (...)
TOP_EFFORT_SOURCES = {"vals", "epoch_eci", "gdpx"}   # publish one unlabelled row per model, run at the top setting
                                                     # (gdpx: only its "Highest" rows are unlabelled)
HERE = os.path.dirname(os.path.abspath(__file__))


def load_envelope(path):
    raw = open(path, encoding="utf-8").read()
    data = json.loads(raw) if raw.lstrip().startswith(("{", "[")) else None
    if isinstance(data, list) and data and isinstance(data[0], dict) and "text" in data[0]:  # agent tool-result file
        text = data[0]["text"]
        obj, _ = json.JSONDecoder().raw_decode(text)
        data = json.loads(obj) if isinstance(obj, str) else obj
    if not isinstance(data, dict) or "records" not in data:
        raise ValueError(f"{path}: not an extractor envelope")
    data.pop("_pad", None)
    return data


def split_effort(name):
    """'Claude Opus 5.5 (Max, Default Fallback)' -> ('Claude Opus 5.5', 'max');
    'Claude 3.7 Sonnet (Thinking 32K, 20250219)' -> ('Claude 3.7 Sonnet 20250219', 'reasoning').
    'reasoning' means: the model's reasoning mode, effort unspecified (resolved to its top reasoning effort)."""
    effort, kept = None, []
    for grp in re.findall(r"\(([^)]*)\)", name or ""):
        rest = []
        for p in (x.strip() for x in grp.split(",")):
            pl = re.sub(r"\s+\d+k$", "", p.lower())            # 'thinking 32k' -> 'thinking'
            if pl in EFFORT_RE:
                v = EFFORT_RE[pl]
                if effort == "non-reasoning" and v not in ("reasoning", "non-reasoning"):
                    effort = f"non-reasoning:{v}"                  # AA 'Claude Sonnet 4.6 (Non-reasoning, High)'
                elif effort is None or v != "reasoning":
                    effort = v
            elif not DROP_PART.match(pl):
                rest.append(p)
        if rest:
            kept.append(" ".join(rest))
    base = re.sub(r"\([^)]*\)", "", name or "").strip()
    if kept:
        base = f"{base} {' '.join(kept)}"
    return base.strip(), effort


def norm_key(s):
    s = (s or "").lower().replace("+", "plus")
    s = re.sub(r"\b20\d{2}(\d{4})\b", r"\1", s)          # DeepSeek-...-20261017 -> 1017
    s = re.sub(r"[-_ ](vertex|bedrock|azure)$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


NOISE_SRC = {"instruct", "it", "preview", "latest", "beta", "thinking", "nvidia"}  # dropped from source names
NOISE_REG = NOISE_SRC | {"chat"}                             # registry-side extras ('Llama 2 Chat 13B')
BUILD_TOK = re.compile(r"^(\d{4}|ym\d{4})$")               # build codes: 0528 / 2505, month tokens ym2605
PARAM_TOK = re.compile(r"^(\d+(\.\d+)?[bmt]|a\d+(\.\d+)?b)$")  # size tokens: 550b, a55b, 2.4t
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
MON_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*'?(?:20)?(\d{2})\b")


def tokens(name):
    s = (name or "").lower()
    s = s.replace("+", " plus ")
    s = re.sub(r"\b20(\d{2})-(\d{2})-(\d{2})\b", r"20\1\2\3", s)                   # 2025-09-23 -> 20250923
    s = MON_RE.sub(lambda m: f" ym{m.group(2)}{MONTHS[m.group(1)]:02d} ", s)        # "Jul '24", "July 2024" -> ym2407
    s = re.sub(r"\b(0[1-9]|1[0-2])-20(\d{2})\b", r" ym\2\1 ", s)                  # "(03-2025)" -> ym2503
    s = re.sub(r"\b20(2\d)(0[1-9]|1[0-2])\b", r" ym\1\2 ", s)                    # "(202506)" -> ym2506
    s = re.sub(r"\b20\d{2}(\d{4})\b", r"\1", s)                                  # 20260910 -> 0910
    s = re.sub(r"[-_ ](vertex|bedrock|azure)$", "", s)
    s = re.sub(r"\b([a-z]{2,})(\d)", r"\1 \2", s)          # 'qwen3.6' -> 'qwen 3.6' (keeps a22b, e4b, v4, ym2407)
    s = re.sub(r"\bym (\d{4})", r"ym\1", s)
    return [t.strip(".") for t in re.findall(r"[a-z0-9.]+", s) if t.strip(".")]


def months(name, release_date=None):
    """Year-month hints (YYMM) a name carries: month tokens, YYYYMMDD dates, YYMM-looking build codes,
    plus the release month for registry entries."""
    raw, out = re.sub(r"\b(20\d{2})-(\d{2})-(\d{2})\b", r"\1\2\3", (name or "").lower()), set()
    out |= {t[2:] for t in tokens(name) if t.startswith("ym")}
    out |= {m.group(1)[2:] + m.group(2) for m in re.finditer(r"\b(20\d{2})(\d{2})\d{2}\b", raw)}
    out |= {c for c in re.findall(r"\b(2[3-9](?:0[1-9]|1[0-2]))\b", raw)}
    if release_date:
        out.add(release_date[2:4] + release_date[5:7])
    return out


def bag(toks, drop=()):
    return " ".join(sorted(t for t in toks if t not in drop))


def build_registry(trends, aliases):
    reg, by_key = {}, {}
    for r in trends["records"]:
        base, effort = split_effort(r["model"])
        k = norm_key(base)
        a = r.get("attrs", {})
        e = reg.setdefault(k, {"base_key": k, "base_name": base, "org": r.get("org"), "release_date": a.get("release_date"),
                               "params_total_b": a.get("params_total_b"), "params_active_b": a.get("params_active_b"),
                               "open_weights": a.get("open_weights"), "licence": a.get("licence"),
                               "size_class": a.get("size_class") or a.get("param_class"), "deprecated": a.get("deprecated"),
                               "variants": {}})
        e["variants"][effort or "default"] = r.get("key")
        by_key[k] = e
    for alias, target in aliases.items():
        if norm_key(target) in by_key:
            by_key[norm_key(alias)] = by_key[norm_key(target)]
    return reg, by_key


def top_effort(variants):
    for e in EFFORTS:
        if e in variants:
            return e
    return next(iter(variants), "default")


_IDX = {}


def _builds(t):
    b = {x for x in t if BUILD_TOK.match(x)}
    return b | {x[2:] for x in b if x.startswith("ym")} | {"ym" + x for x in b if re.fullmatch(r"2[3-9](0[1-9]|1[0-2])", x)}


def _pick(es, src_noise):
    """Unique entry, else break ties by matching noise words ('Instruct', 'Chat'): equal set first, then subset."""
    keys = {x["e"]["base_key"] for x in es}
    if len(keys) == 1:
        return es[0]["e"]
    for test in (lambda x: x["noise"] == src_noise, lambda x: x["noise"] <= src_noise):
        sub = [x for x in es if test(x)]
        if len({x["e"]["base_key"] for x in sub}) == 1:
            return sub[0]["e"]
    return None


def _index(by_key):
    if id(by_key) not in _IDX:
        idx = {"bag": {}, "loose": {}, "ents": []}
        for k, e in {e["base_key"]: e for e in by_key.values()}.items():
            t = tokens(e["base_name"])
            core = [x for x in t if x not in NOISE_REG and not BUILD_TOK.match(x)]
            idx["bag"].setdefault(bag(t), {})[k] = e
            idx["loose"].setdefault(bag(t, NOISE_REG), {})[k] = e
            idx["ents"].append({"e": e, "t": t, "core": bag(core), "noparam": bag(x for x in core if not PARAM_TOK.match(x)),
                                "hasparam": any(PARAM_TOK.match(x) for x in core),
                                "builds": _builds(t), "noise": {x for x in t if x in NOISE_REG},
                                "months": months(e["base_name"], e.get("release_date"))})
        _IDX[id(by_key)] = idx
    return _IDX[id(by_key)]


def find(base, by_key):
    """Exact key, then fallbacks. Every fallback is returned as a flag ('match:<method>') so guesses stay
    visible in observations.csv and matches_guessed.csv. Returns (entry, method) or (None, candidates)."""
    k = norm_key(base)
    if k in by_key:
        return by_key[k], None
    idx, t = _index(by_key), tokens(base)
    src_noise = {x for x in t if x in NOISE_REG}
    uniq = lambda es: _pick(es, src_noise)
    one = lambda d: next(iter(d.values())) if d and len(d) == 1 else None
    if (e := one(idx["bag"].get(bag(t)))):
        return e, "match:token_order"
    if (e := one(idx["loose"].get(bag(t, NOISE_SRC)))):
        return e, "match:noise_tokens"
    builds = _builds(t)
    core = [x for x in t if x not in NOISE_SRC and not BUILD_TOK.match(x)]
    mon = months(base)
    views = [("", lambda x: x["core"] == bag(core))]
    if any(PARAM_TOK.match(x) for x in core):          # 'Mistral Small 3.1 24B' vs AA 'Mistral Small 3.1'
        views.append(("params_ignored;", lambda x: not x["hasparam"] and x["noparam"] == bag(y for y in core if not PARAM_TOK.match(y))))
    else:                                              # 'Nemotron 3 Ultra' vs AA 'Nemotron 3 Ultra 550B A55B'
        views.append(("param_suffix;", lambda x: x["hasparam"] and x["noparam"] == bag(core)))
    for tag, same in views:
        fam = [x for x in idx["ents"] if same(x)]
        if not fam:
            continue
        if builds:
            hit = [x for x in fam if x["builds"] & builds]
            if hit and (e := uniq(hit)):
                return e, f"match:{tag}build_match"
            hit = [x for x in fam if mon and x["months"] & mon]
            if hit and (e := uniq(hit)):
                return e, f"match:{tag}build_by_month"
            plain = [x for x in fam if not x["builds"]]
            if plain and (e := uniq(plain)):           # AA lists one undated entry: assume it is this build
                return e, f"match:{tag}build_dropped"
            continue
        plain = [x for x in fam if not x["builds"]]
        if plain and (e := uniq(plain)):
            return e, f"match:{tag.rstrip(';') or 'core'}"
        # no build named, AA only lists dated builds: assume the first release
        first = min(fam, key=lambda x: x["e"].get("release_date") or "9999")
        return first["e"], f"match:{tag}build_assumed_earliest"
    ts = set(t)
    cands = sorted(((len(ts & set(x["t"])) / max(len(ts), 1), x["e"]["base_name"]) for x in idx["ents"]
                    if t and x["t"] and x["t"][0] == t[0]), reverse=True)
    return None, " | ".join(n for sc, n in cands[:5] if sc >= 0.5)


MATCH_ORDER = ["token_order", "noise_tokens", "build_match", "core", "build_by_month", "param_suffix",
               "params_ignored", "build_dropped", "build_assumed_earliest"]


def match_rank(how):
    """0 = exact name match; higher = weaker guess. Used to settle two source names that land on one variant."""
    if not how:
        return 0
    parts = how.replace("match:", "").split(";")
    return 1 + max(MATCH_ORDER.index(p) if p in MATCH_ORDER else len(MATCH_ORDER) for p in parts)


def resolve(name, by_key, source):
    base, effort = split_effort(name)
    if effort is None and re.search(r"\bthinking\b", base, re.I):
        effort = "reasoning"
    e, how = find(base, by_key)
    if not e:
        return None, None, base, effort, how
    vs = e["variants"]
    if effort is None:
        if source in TOP_EFFORT_SOURCES:
            eff = top_effort(vs)            # Vals / Epoch run the top setting
        elif "default" in vs:
            eff = "default"                 # AA's own unlabelled variant (e.g. 'o3-mini' next to 'o3-mini (High)')
        else:
            eff = "unlabelled"              # e.g. LMArena 'Claude Opus 4.8' next to '(High)': effort unknown
    elif effort == "reasoning":             # 'Thinking' / 'Reasoning' without effort: top reasoning effort
        eff = top_effort({v: 1 for v in vs if v != "non-reasoning"} or vs)
    elif effort in vs:
        eff = effort
    elif len(vs) == 1:                      # one known variant, source labels it (e.g. Kimi K3.1 Pro (Max))
        eff = next(iter(vs))
    else:
        eff = effort                        # effort AA doesn't list: keep it, flagged
    return e, eff, base, effort, how


def main(raw_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    aliases = json.load(open(os.path.join(HERE, "aliases.json"))) if os.path.exists(os.path.join(HERE, "aliases.json")) else {}
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(raw_dir) for f in fs if f.endswith((".json", ".txt")))
    envs = [load_envelope(f) for f in files]           # RAW_DIR may hold dated subfolders (data/envelopes/<date>/)
    trends = [e for e in envs if e["source"] == "aa_trends"]
    if not trends:
        sys.exit("need an aa_trends envelope (artificialanalysis.ai/trends) as the registry backbone")
    reg, by_key = build_registry(max(trends, key=lambda e: e["retrieved"]), aliases)
    rows, unmatched, guessed = [], {}, {}
    for env in envs:
        date = re.sub(r"\D", "", env.get("wayback_capture") or env["retrieved"])[:8]
        date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        res = [(r, *resolve(r["model"], by_key, env["source"])) for r in env["records"]]
        slots = {}                                  # two source names landing on one model variant
        for r, e, eff, base, label, how in res:
            if e is not None:
                slots.setdefault((e["base_key"], eff), []).append((match_rank(how), r["model"]))
        for r, e, eff, base, label, how in res:
            if e is not None and len(slots[(e["base_key"], eff)]) > 1:
                same = slots[(e["base_key"], eff)]
                best = min(rk for rk, _ in same)
                winners = [m for rk, m in same if rk == best]
                tag = "collision" if len(winners) > 1 and r["model"] in winners else \
                      "collision_dropped" if r["model"] not in winners else ""
                how = ";".join(x for x in (how, tag) if x) or None
            if e is None:
                unmatched[(env["source"], r["model"])] = (base, how)
            elif how:
                guessed[(env["source"], r["model"])] = (e["base_name"], how)
            for metric, value in (r.get("metrics") or {}).items():
                if value is None or isinstance(value, (dict, list, bool)):
                    continue
                if isinstance(value, str):                     # e.g. '23.5 min' -> 23.5 (unit kept in metric notes)
                    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(%|s|min|ms)?\s*", value.replace(",", ""))
                    if not m:
                        continue
                    value = float(m.group(1)) * {"min": 60, "ms": 0.001}.get(m.group(2), 1)
                lo, hi = (r.get("ci") or {}).get(metric, [None, None])
                flags = list(r.get("flags") or [])
                if e is not None and label and eff == label and label not in e["variants"]:
                    flags.append("effort_not_in_registry")
                if eff == "unlabelled":
                    flags.append("effort_unlabelled")
                if how and e is not None:
                    flags.append(how)
                rows.append({"date": date, "source": env["source"], "category": env.get("category"), "metric": metric,
                             "model_raw": r["model"], "base_key": e["base_key"] if e else "", "base_name": e["base_name"] if e else base,
                             "effort": eff or (label or ""), "effort_label": label or "", "value": value,
                             "ci_low": lo, "ci_high": hi, "flags": ";".join(flags), "page": env.get("page"),
                             "wayback_capture": env.get("wayback_capture") or "", "retrieved": env.get("retrieved")})
    fields = list(rows[0].keys()) if rows else []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(os.path.join(out_dir, f"snapshot_{stamp}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fields); w.writeheader(); w.writerows(rows)
    obs = os.path.join(out_dir, "observations.csv")
    new = not os.path.exists(obs)
    with open(obs, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fields)
        if new:
            w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out_dir, "registry.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["base_key", "base_name", "org", "release_date", "params_total_b", "params_active_b", "open_weights", "licence",
                    "size_class", "deprecated", "efforts", "top_effort"])
        for e in sorted(reg.values(), key=lambda e: e["base_name"].lower()):
            w.writerow([e["base_key"], e["base_name"], e["org"], e["release_date"], e["params_total_b"], e["params_active_b"],
                        e["open_weights"], e["licence"], e.get("size_class"), e.get("deprecated"), "|".join(e["variants"]), top_effort(e["variants"])])
    with open(os.path.join(out_dir, "unmatched.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["source", "model_raw", "base_parsed", "registry_candidates"])
        for (s, m), (b, c) in sorted(unmatched.items()):
            w.writerow([s, m, b, c])
    with open(os.path.join(out_dir, "matches_guessed.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["source", "model_raw", "matched_to", "method"])   # review; fix wrong ones via aliases.json
        for (s, m), (b, how) in sorted(guessed.items()):
            w.writerow([s, m, b, how])
    per = {}
    for r in rows:
        per.setdefault(r["source"] + "/" + str(r["category"]), set()).add(r["model_raw"])
    print(f"{len(envs)} envelopes · {len(rows)} observations · registry {len(reg)} base models · "
          f"unmatched {len(unmatched)} · fuzzy matches to review {len(guessed)}")
    for k, v in sorted(per.items()):
        miss = sum(1 for (s, m) in unmatched if s == k.split('/')[0] and m in v)
        print(f"  {k:32s} {len(v):4d} models, {miss:3d} unmatched")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
