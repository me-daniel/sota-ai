// model-ratings-pipeline · extractors.js · v1.0 (2026-10-29)
// One snippet for every supported leaderboard page. It reads the data the page already loaded and returns
// a standard JSON envelope: { source, category, page, wayback_capture, retrieved, n, records: [...] }.
//   record = { model, key, org, metrics: {name: value}, ci: {name: [low, high]}, attrs: {...}, flags: [...] }
//
// Agent use: run the whole file with the browser pane's JavaScript tool on the page; the result is the JSON string.
// Human use: paste into the browser console (Cmd+Option+J / Ctrl+Shift+J). Set `window.RATINGS_DOWNLOAD = true`
//            first to get a dated .json file instead of console output.
// Supported pages (also their Wayback Machine captures):
//   artificialanalysis.ai/leaderboards/models          aa_leaderboard  (index, cost/task, speed, ~35 benchmarks)
//   artificialanalysis.ai/trends                       aa_trends       (Progress Index, params, release dates)
//   artificialanalysis.ai/evaluations/aa-personalitybench   aa_personality (29 traits incl. slop, sycophancy)
//   arena.ai/leaderboard/(chat/)text[/<category>]      lmarena_text    (Elo + CI + votes per category)
//   arena.ai/leaderboard/agent[/code|chat|work]        arena_agent     (net improvement + signals, exact signs)
//   vals.ai/benchmarks/<benchmark>                     vals            (accuracy, cost; components if expanded)
//   epoch.ai/eci  (any epoch.ai page)                  epoch_eci       (ECI + CI from eci_scores.csv)
// Attribution: data belongs to the respective publishers; cite them when reusing.
await (async () => {
  const VERSION = '1.0';
  const href = location.href;
  const page = href.replace(/^https?:\/\/web\.archive\.org\/web\/\d+(?:[a-z_]+)?\//, '');
  const wayback = (href.match(/web\.archive\.org\/web\/(\d+)/) || [])[1] || null;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const r4 = x => (typeof x === 'number' && isFinite(x)) ? Math.round(x * 1e4) / 1e4 : (x ?? null);
  const num = s => { if (s == null) return null; const m = String(s).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/); return m ? parseFloat(m[0]) : null; };
  const SKIP = new Set(['_owner', 'return', 'child', 'sibling', 'alternate', 'stateNode', 'fuse', '_docs']);
  const reactArrays = (pred, minLen = 10) => {
    const out = [], seen = new WeakSet();
    const scan = (o, d) => {
      if (!o || typeof o !== 'object' || seen.has(o) || d > 14) return;
      seen.add(o);
      if (Array.isArray(o) && o.length >= minLen && o[0] && typeof o[0] === 'object' && pred(o[0])) { out.push(o); return; }
      for (const k in o) { if (SKIP.has(k)) continue; try { scan(o[k], d + 1); } catch (e) { /* getter threw */ } }
    };
    for (const el of document.querySelectorAll('body *')) {
      const k = Object.keys(el).find(k => k.startsWith('__reactProps'));
      if (k) scan(el[k], 0);
    }
    return out.sort((a, b) => b.length - a.length);
  };
  const tableRows = t => [...t.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')]);
  const txt = c => (c ? c.innerText.replace(/\s+/g, ' ').trim() : '');
  const lastSeg = () => page.replace(/[?#].*$/, '').split('/').filter(Boolean).pop();

  const X = {
    aa_leaderboard: {
      match: /artificialanalysis\.ai\/(?:[a-z]{2}\/)?leaderboards\/models/,
      run: async () => {
        const A = reactArrays(o => 'intelligenceIndex' in o && 'scores' in o, 50)[0];
        if (!A) throw new Error('no embedded model data yet — wait for the page to load');
        return { category: 'llm', records: A.map(m => ({
          model: m.name, key: m.slug, org: m.modelCreatorName,
          metrics: Object.assign({
            intelligence_index: r4(m.intelligenceIndex), cost_per_task: r4(m.intelligenceIndexCostPerTask),
            omniscience: r4(m.omniscience), price_in: m.price1mInputTokens, price_out: m.price1mOutputTokens,
            cache_hit_price: m.cacheHitPrice, tokens_per_s: r4(m.medianOutputTokensPerSecond),
            ttft_s: r4(m.medianTimeToFirstTokenSeconds), ttfat_s: r4(m.medianTimeToFirstAnswerTokenSeconds),
            e2e_s: r4(m.medianEndToEndResponseTimeSeconds), reasoning_s: r4(m.medianReasoningTimeSeconds),
          }, Object.fromEntries(Object.entries(m.scores || {}).map(([k, v]) => ['bench.' + k, r4(v)]))),
          attrs: { reasoning: !!m.isReasoning, open_weights: !!m.isOpenWeights, param_class: m.paramClass,
                   context: m.contextWindowTokens, deprecated: !!m.deprecated },
          flags: m.intelligenceIndexIsEstimated ? ['index_estimated'] : [],
        })) };
      },
    },
    aa_trends: {
      match: /artificialanalysis\.ai\/(?:[a-z]{2}\/)?trends/,
      run: async () => {
        const A = reactArrays(o => 'inferenceParametersActiveBillions' in o && 'score' in o, 100)[0];
        if (!A) throw new Error('no Progress Index data found');
        return { category: 'progress', records: A.map(m => ({
          model: m.name, key: m.slug, org: m.creator && m.creator.name,
          metrics: { progress_index: r4(m.score), intelligence_index: r4(m.intelligenceIndex), cost_per_task: r4(m.intelligenceIndexCostPerTask),
                     price_out: m.price1mOutputTokens, tokens_per_s: r4(m.medianOutputSpeed) },
          attrs: { release_date: m.releaseDate, params_total_b: m.parameters, params_active_b: m.inferenceParametersActiveBillions,
                   size_class: m.sizeClass, licence: m.openSourceCategorization, open_weights: !!m.isOpenWeights,
                   reasoning: !!m.isReasoning, context: m.contextWindowTokens, release: m.release && m.release.name,
                   country: m.creator && m.creator.country },
          flags: m.intelligenceIndexIsEstimated ? ['index_estimated'] : [],
        })) };
      },
    },
    aa_personality: {
      match: /artificialanalysis\.ai\/(?:[a-z]{2}\/)?evaluations\/aa-personalitybench/,
      run: async () => {
        const A = reactArrays(o => 'judged' in o && 'measured' in o, 10)[0];
        if (!A) throw new Error('open the main AA-PersonalityBench page (not a sub-index page)');
        return { category: 'personality', records: A.map(m => {
          const j = m.judged || {}, me = m.measured || {}, metrics = {}, ci = {};
          for (const [k, v] of Object.entries(j.scores || {})) metrics['trait.' + k] = r4(v);
          for (const [k, v] of Object.entries(j.cis || {})) ci['trait.' + k] = [r4(v.lower), r4(v.upper)];
          for (const [k, v] of Object.entries(j.indexScores || {})) metrics['index.' + k] = r4(v);
          for (const [k, v] of Object.entries(me.means || {})) metrics['measured.' + k] = r4(v);
          return { model: m.name, key: m.slug, org: m.creator && m.creator.name, metrics, ci,
                   attrs: { open_weights: !!m.isOpenWeights, reasoning: !!m.isReasoning }, flags: [] };
        }) };
      },
    },
    lmarena_text: {
      match: /arena\.ai\/(?:[a-z]{2}\/)?leaderboard\/(?:chat\/)?text/,
      run: async () => {
        const seg = lastSeg();
        const A = reactArrays(o => 'rating' in o && 'ratingUpper' in o && 'modelDisplayName' in o, 20)[0];
        if (!A) {  // fallback when React hasn't hydrated (e.g. hidden pane): parse the rendered table (Elo rounded, symmetric CI)
          const t = document.querySelector('table');
          if (!t) throw new Error('no leaderboard entries or table found');
          const rows = tableRows(t); const head = rows[0].map(txt);
          const ci_ = n => head.findIndex(h => h.toLowerCase() === n);
          return { category: seg === 'text' ? 'overall' : seg, notes: { mode: 'table-fallback' }, records: rows.slice(1).map(c => {
            const mc = c[ci_('model')], sc = c[ci_('score')];
            const spans = sc ? [...sc.querySelectorAll('span')].map(s => s.innerText) : [];
            const elo = num(spans[0] ?? txt(sc)), hw = num((spans.find(s => /±/.test(s)) || '').replace('±', ''));
            return { model: (mc && mc.querySelector('[title]')) ? mc.querySelector('[title]').getAttribute('title') : txt(mc), key: null,
                     org: null, metrics: { elo, votes: num(txt(c[ci_('votes')])), rank: num(txt(c[ci_('rank')])) },
                     ci: hw != null && elo != null ? { elo: [elo - hw, elo + hw] } : {},
                     attrs: { licence: ((txt(mc).match(/·\s*(.+)$/) || [])[1]) || null },
                     flags: /Preliminary/.test(txt(sc)) ? ['preliminary'] : [] };
          }) };
        }
        return { category: seg === 'text' ? 'overall' : seg, notes: { mode: 'embedded' }, records: A.map(e => ({
          model: e.modelDisplayName, key: e.modelKey, org: e.modelOrganization,
          metrics: { elo: r4(e.rating), votes: e.votes, rank: e.rank },
          ci: { elo: [r4(e.ratingLower), r4(e.ratingUpper)], rank: [e.rankUpper, e.rankLower] },
          attrs: { licence: e.license, price_in: e.inputPricePerMillion, price_out: e.outputPricePerMillion, context: e.contextLength },
          flags: Object.keys(e).filter(k => /prelim/i.test(k) && e[k]).map(() => 'preliminary'),
        })) };
      },
    },
    arena_agent: {
      match: /arena\.ai\/(?:[a-z]{2}\/)?leaderboard\/agent/,
      run: async () => {
        const t = document.querySelector('table');
        if (!t) throw new Error('no table found');
        const rows = tableRows(t);
        const head = rows[0].map(txt);
        const seg = lastSeg();
        const pct = cell => {  // "23.48%±3.04%" with the sign carried by an Up/Down icon
          const s = txt(cell); const m = s.match(/(-?\d+(?:\.\d+)?)%\s*±\s*(\d+(?:\.\d+)?)%/);
          if (!m) return null;
          const down = cell.querySelector('[aria-label="Down"], .text-interactive-negative');
          const v = parseFloat(m[1]) * (down ? -1 : 1);
          return { v: r4(v), hw: parseFloat(m[2]) };
        };
        const records = rows.slice(1).map(cells => {
          const titled = cells[1] && cells[1].querySelector('[title]');
          const model = titled ? titled.getAttribute('title') : txt(cells[1]);
          const orgLic = (txt(cells[1]).match(/([^·]+)·\s*([^·]+?)(?:·Preliminary)?$/) || []);
          const metrics = {}, ci = {};
          head.forEach((h, i) => {
            if (i < 2) return;
            const key = h.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
            const p = pct(cells[i]);
            if (p) { metrics[key] = p.v; ci[key] = [r4(p.v - p.hw), r4(p.v + p.hw)]; }
            else metrics[key] = /\$|min|s$|K$|M$/.test(txt(cells[i])) || /sessions/.test(key) ? txt(cells[i]) : num(txt(cells[i]));
          });
          if (typeof metrics.sessions === 'string') metrics.sessions = num(metrics.sessions);
          if (typeof metrics.cost_task_p50 === 'string') metrics.cost_task_p50 = num(metrics.cost_task_p50);
          const rankSpans = cells[0] ? [...cells[0].querySelectorAll('span')].map(s => num(s.innerText)) : [];
          return { model, key: null, org: orgLic[1] ? orgLic[1].replace(model, '').trim() : null, metrics, ci,
                   attrs: { licence: orgLic[2] ? orgLic[2].trim() : null, rank: rankSpans[0] ?? null },
                   flags: /Preliminary/.test(txt(cells[1])) ? ['preliminary'] : [] };
        });
        return { category: seg === 'agent' ? 'overall' : seg, records };
      },
    },
    vals: {
      match: /vals(?:-ai)?\.ai\/benchmarks\//,
      run: async () => {
        const tables = [...document.querySelectorAll('table')];
        if (!tables.length) throw new Error('no table found');
        const main = tableRows(tables[0]); const head = main[0].map(txt);
        const col = n => head.findIndex(h => h.toLowerCase().startsWith(n));
        const records = main.slice(1).map(c => ({
          model: txt(c[col('model')]), key: null, org: null,
          metrics: { accuracy: num(txt(c[col('accuracy')])), cost_per_test: num(txt(c[col('cost')])), rank: num(txt(c[0])) },
          ci: {}, attrs: { tokens_per_test: col('tokens') >= 0 ? txt(c[col('tokens')]) : null, duration: col('duration') >= 0 ? txt(c[col('duration')]) : null }, flags: [] }));
        // component table (two header rows; first column = model). Click "View N more models" first to get all rows.
        const comp = tables.map(tableRows).find(r => r.length > 2 && txt(r[0][0]).toUpperCase() === 'MODELS');
        let componentRows = 0;
        if (comp) {
          const names = comp[1].map(txt).filter(Boolean);
          for (const r of comp.slice(2)) {
            const vals = r.map(txt); const model = vals[0];
            const nums = vals.slice(1).filter(v => v !== '').map(num);
            const rec = records.find(x => x.model === model);
            if (rec && nums.length === names.length) { names.forEach((n, i) => { rec.metrics['component.' + n] = nums[i]; }); componentRows++; }
          }
        }
        const bt = document.body.innerText;
        const updated = (bt.match(/Updated:?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i) || bt.match(/As of ([A-Z][a-z]+ \d{1,2}, \d{4})/) || [])[1] || null;
        return { category: lastSeg(), records, notes: { updated, component_rows: componentRows } };
      },
    },
    epoch_eci: {
      match: /epoch\.ai\//,
      run: async () => {
        const res = await fetch('/data/eci_scores.csv');
        if (!res.ok) throw new Error('eci_scores.csv returned ' + res.status);
        const lines = (await res.text()).trim().split(/\r?\n/);
        const parse = l => { const out = []; let cur = '', q = false; for (const ch of l) { if (ch === '"') q = !q; else if (ch === ',' && !q) { out.push(cur); cur = ''; } else cur += ch; } out.push(cur); return out; };
        const h = parse(lines[0]);
        const idx = n => h.indexOf(n);
        return { category: 'eci', records: lines.slice(1).map(l => { const c = parse(l); return {
          model: c[idx('Display name')] || c[idx('Model')], key: c[idx('Model')], org: c[idx('Organization')],
          metrics: { eci: num(c[idx('eci')]) }, ci: { eci: [num(c[idx('eci_ci_low')]), num(c[idx('eci_ci_high')])] },
          attrs: { date: c[idx('date')], accessibility: c[idx('Model accessibility')], weights: c[idx('Accessibility group')],
                   country: c[idx('Country (of organization)')], versions: c[idx('model_versions')] || null }, flags: [] }; }) };
      },
    },
  };

  const id = Object.keys(X).find(k => X[k].match.test(page));
  if (!id) return JSON.stringify({ error: 'unsupported page', page });
  await sleep(1500);
  const out = await X[id].run();
  const env = { extractor_version: VERSION, source: id, category: out.category, page, wayback_capture: wayback,
                retrieved: new Date().toISOString(), n: out.records.length, notes: out.notes || null, records: out.records };
  if (window.RATINGS_SUMMARY) {  // quick check: counts, metric coverage, one sample record
    const cov = {};
    for (const r of out.records) for (const [k, v] of Object.entries(r.metrics)) if (v != null) cov[k] = (cov[k] || 0) + 1;
    return JSON.stringify({ source: id, category: out.category, page, wayback_capture: wayback, n: env.n, notes: env.notes,
                            approx_chars: JSON.stringify(env).length, metric_coverage: cov, sample: out.records[0] });
  }
  if (window.RATINGS_SLICE) {    // the agent bridge truncates results above ~260k characters: fetch in slices, e.g. [0,120]
    const [a, b] = window.RATINGS_SLICE;
    env.slice = [a, Math.min(b, env.n)];
    env.records = out.records.slice(a, b);
  }
  if (window.RATINGS_PAD) {      // agent use: results under ~100k chars come back inline; padding makes the harness save a file
    const cur = JSON.stringify(env).length;
    if (cur < window.RATINGS_PAD) env._pad = ' '.repeat(window.RATINGS_PAD - cur);
  }
  const json = JSON.stringify(env);
  if (window.RATINGS_DOWNLOAD) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    a.download = `${id}_${out.category}_${(wayback || env.retrieved.slice(0, 10).replace(/-/g, '')).slice(0, 8)}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    return `saved ${env.n} records as ${a.download}`;
  }
  return json;
})();
