// Artificial Analysis snapshot — downloads the model data embedded in an AA page as a dated JSON file.
//
// Use: open one of these pages in a normal browser, wait until it has loaded, open the developer
// console (Cmd+Option+J on Mac / Ctrl+Shift+J on Windows), paste this whole file, press Enter.
//   https://artificialanalysis.ai/leaderboards/models   -> every model × effort: Intelligence Index,
//        AA's "estimated" flag, cost per index task, prices, speed, latency, ~35 per-benchmark scores
//   https://artificialanalysis.ai/trends                -> Progress Index v1 for ~700 variants, release
//        dates, total / active parameters, size class
// Also works on a Wayback Machine capture of those pages (web.archive.org/web/<timestamp>/<url>),
// which is how the final Intelligence Index v4.3.2 values were recovered.
//
// It only reads data the page already loaded (one page view, no extra requests).
// Attribution required for any reuse: data from Artificial Analysis, https://artificialanalysis.ai/
(() => {
  const SKIP = new Set(['_owner', 'return', 'child', 'sibling', 'alternate', 'stateNode', 'fuse', '_docs']);
  const DROP = /logo|color|^shortName$|nameAndCreatorLabel|chartDefaultSelected/i;
  const seen = new WeakSet();
  const candidates = [];
  const scan = (o, depth) => {
    if (!o || typeof o !== 'object' || seen.has(o) || depth > 12) return;
    seen.add(o);
    if (Array.isArray(o) && o.length >= 50 && o[0] && typeof o[0] === 'object' && 'slug' in o[0] &&
        ('intelligenceIndex' in o[0] || 'score' in o[0])) {
      candidates.push(o);
      return;
    }
    for (const k in o) {
      if (SKIP.has(k)) continue;
      try { scan(o[k], depth + 1); } catch (e) { /* ignore getters that throw */ }
    }
  };
  for (const el of document.querySelectorAll('main *')) {
    const key = Object.keys(el).find(k => k.startsWith('__reactProps'));
    if (key) scan(el[key], 0);
  }
  if (!candidates.length) {
    console.error('AA snapshot: no embedded model data found. Wait for the page to finish loading and try again.');
    return;
  }
  // richest dataset = most rows × most fields
  const best = candidates.sort((a, b) => b.length * Object.keys(b[0]).length - a.length * Object.keys(a[0]).length)[0];
  const clean = v => {
    if (Array.isArray(v)) return v.map(clean);
    if (v && typeof v === 'object') {
      const out = {};
      for (const [k, x] of Object.entries(v)) if (!DROP.test(k)) out[k] = clean(x);
      return out;
    }
    return v;
  };
  const page = location.href.replace(/^https?:\/\/web\.archive\.org\/web\/\d+\//, '');
  const capture = (location.href.match(/web\.archive\.org\/web\/(\d+)/) || [])[1] || null;
  const payload = {
    source: location.href,
    page,
    waybackCapture: capture,
    retrieved: new Date().toISOString(),
    n: best.length,
    attribution: 'Data from Artificial Analysis — https://artificialanalysis.ai/',
    models: best.map(clean),
  };
  const name = (page.replace(/[?#].*$/, '').split('/').filter(Boolean).pop() || 'page');
  const stamp = capture ? capture.slice(0, 8) : new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `aa_${name}_${stamp}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  console.log(`AA snapshot: saved ${payload.n} models from ${page} as ${a.download}`);
})();
