# ruff: noqa: E501
"""In-page extraction script. Read-only: it never types, clicks, focuses or submits anything.

It returns descriptors and small derived values only; the raw HTML and script text never leave
the page. Classification happens in Python (``falcon_core.signals.page``).
"""

EXTRACT_JS = r"""
() => {
  const T = (s, n = 120) => (s == null ? '' : String(s)).slice(0, n);
  const abs = (u) => { try { return new URL(u, document.baseURI).href; } catch (e) { return ''; } };
  const labelOf = (el) => {
    let t = '';
    try {
      if (el.labels && el.labels.length) t = [...el.labels].map(l => l.textContent).join(' ');
      if (!t) { const l = el.closest('label'); if (l) t = l.textContent; }
    } catch (e) {}
    return T(t, 120);
  };
  const desc = (el) => ({
    type: T(el.tagName === 'SELECT' ? 'select' : (el.getAttribute('type') || (el.tagName === 'TEXTAREA' ? 'textarea' : 'text')), 20).toLowerCase(),
    name: T(el.getAttribute('name')), id: T(el.id),
    autocomplete: T(el.getAttribute('autocomplete'), 40),
    placeholder: T(el.getAttribute('placeholder')), aria: T(el.getAttribute('aria-label')),
    label: labelOf(el), inputmode: T(el.getAttribute('inputmode'), 20),
    maxlength: parseInt(el.getAttribute('maxlength') || '0', 10) || 0,
  });
  const controls = (root) => [...root.querySelectorAll('input,textarea,select')].slice(0, 60);
  const forms = [...document.forms].slice(0, 20).map(f => ({
    action: abs(f.getAttribute('action') || ''), method: T(f.getAttribute('method') || 'get', 10),
    fields: controls(f).map(desc),
  }));
  const loose = [...document.querySelectorAll('input,textarea')].filter(e => !e.form).slice(0, 60);
  if (loose.length) forms.push({ action: '', method: 'get', fields: loose.map(desc) });

  const scripts = [...document.scripts].filter(s => !s.src).map(s => s.textContent || '');
  const js = scripts.join('\n').slice(0, 300000);
  const count = (re) => (js.match(re) || []).length;
  const indicators = {
    eval_calls: count(/\beval\s*\(/g), atob_calls: count(/\batob\s*\(/g),
    from_char_code: count(/fromCharCode/g), unescape_calls: count(/\bunescape\s*\(/g),
    function_ctor: count(/new\s+Function\s*\(/g), hex_escapes: count(/\\x[0-9a-fA-F]{2}/g),
    unicode_escapes: count(/\\u[0-9a-fA-F]{4}/g), long_base64_strings: count(/[A-Za-z0-9+\/]{200,}={0,2}/g),
    obfuscated_identifiers: count(/\b_0x[0-9a-f]{3,}\b/g), document_write: count(/document\.write\s*\(/g),
    debugger_statements: count(/\bdebugger\b/g),
    contextmenu_block: count(/contextmenu/g),
    f12_block: count(/keyCode\s*={2,3}\s*123|key\s*={2,3}\s*['"]F12/g),
    devtools_detect: count(/devtools|outerWidth\s*-\s*innerWidth|console\.clear\s*\(/gi),
    inline_script_bytes: js.length,
    js_location_assignments: count(/(?:window\.|top\.|self\.)?location(?:\.href)?\s*=[^=]|location\.(?:replace|assign)\s*\(/g),
    meta_refresh: !!document.querySelector('meta[http-equiv="refresh" i]'),
  };
  const typed = [];
  // does the call site read form data? (looked for in the 700 characters after the call; payload, not destination)
  const FD = /\.value\b|FormData|serialize|URLSearchParams|passw|\botp\b|\bcvv\b|card|\bpin\b|emirates/i;
  const addAll = (re, kind) => { for (const m of js.matchAll(re)) { const u = abs(m[2]); if (u) typed.push({kind, url: u, body: FD.test(js.slice(m.index, m.index + 700))}); } };
  addAll(/fetch\(\s*(['"`])([^'"`]+)\1\s*,\s*\{[^}]{0,300}method\s*:\s*['"`]POST/gi, 'fetch');
  addAll(/\.open\(\s*['"`]POST['"`]\s*,\s*(['"`])([^'"`]+)\1/gi, 'xhr');
  addAll(/sendBeacon\(\s*(['"`])([^'"`]+)\1/g, 'beacon');
  const literals = [...new Set([...js.matchAll(/https?:\/\/[^\s'"`<>\\)]{4,200}/g)].map(m => m[0]))].slice(0, 80);

  const toks = [];
  const walk = (el, depth, parent) => {
    if (toks.length > 4000) return;
    const tag = el.tagName.toLowerCase();
    toks.push(depth + ':' + tag); toks.push(parent + '>' + tag);
    if (tag === 'input') toks.push('input:' + T(el.getAttribute('type') || 'text', 12).toLowerCase());
    if (tag === 'script' || tag === 'style') return;
    for (const c of el.children) walk(c, depth + 1, tag);
  };
  if (document.documentElement) walk(document.documentElement, 0, '');

  const icon = document.querySelector('link[rel~="icon" i]');
  return {
    title: T(document.title, 300), lang: T(document.documentElement.lang, 20),
    forms, js: indicators, typed, literals, struct: toks,
    text: T(document.body ? document.body.innerText : '', 20000),
    favicon: icon ? abs(icon.getAttribute('href')) : abs('/favicon.ico'),
  };
}
"""
