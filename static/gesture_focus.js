// /static/gesture_focus.js
(function () {
  const SELECTOR = '[data-gfocus]';
  const ACTIVE_CLASS = 'gfocus-active';

  function center(el) {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }
  function distance(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y;
    return Math.hypot(dx, dy);
  }
  function listFocusables() {
    return Array.from(document.querySelectorAll(SELECTOR))
      .filter(el => el.offsetParent !== null);
  }

  function findNext(current, candidates, dir) {
  if (!candidates.length) return null;
  if (!current || !candidates.includes(current)) return candidates[0];

  const c0 = center(current);
  const axis = {
    left:  { x: -1, y:  0 },
    right: { x:  1, y:  0 },
    up:    { x:  0, y: -1 },
    down:  { x:  0, y:  1 },
  }[dir];

  let best = null, bestScore = -Infinity;

  for (const el of candidates) {
    if (el === current) continue;
    const c1 = center(el);
    const v = { x: c1.x - c0.x, y: c1.y - c0.y };
    const proj = v.x * axis.x + v.y * axis.y;
    if (proj <= 0) continue;
    const orth = Math.abs(v.x * axis.y - v.y * axis.x);
    const d = Math.max(distance(c0, c1), 1);
    const score = proj / d - orth / (d * 2);
    if (score > bestScore) { bestScore = score; best = el; }
  }

  // --- NOWY fallback zależny od kierunku ---
  if (best) return best;

  const idx = candidates.indexOf(current);
  if (dir === 'left' || dir === 'up') {
    // poprzedni w kolejności
    return candidates[(idx - 1 + candidates.length) % candidates.length];
  } else {
    // następny w kolejności
    return candidates[(idx + 1) % candidates.length];
  }
  }


  // Fallback stylu (gdy CSS się nie zaciągnął)
  function applyActiveStyle(el) {
    // Jeśli CSS zadziałał, outline już istnieje — nie nadpisuj
    const cs = getComputedStyle(el);
    const ow = cs.outlineWidth, os = cs.outlineStyle;
    const visible = (ow && ow !== '0px') || (os && os !== 'none');
    if (!visible) {
      el.dataset.gfPrevOutline = el.style.outline || '';
      el.dataset.gfPrevOffset  = el.style.outlineOffset || '';
      el.dataset.gfPrevRadius  = el.style.borderRadius || '';
      el.style.outline = '4px solid #4a90e2';
      el.style.outlineOffset = '6px';
      if (!el.style.borderRadius) el.style.borderRadius = '14px';
    }
  }
  function removeActiveStyle(el) {
    if ('gfPrevOutline' in el.dataset) el.style.outline = el.dataset.gfPrevOutline;
    if ('gfPrevOffset'  in el.dataset) el.style.outlineOffset = el.dataset.gfPrevOffset;
    if ('gfPrevRadius'  in el.dataset) el.style.borderRadius = el.dataset.gfPrevRadius;
    delete el.dataset.gfPrevOutline;
    delete el.dataset.gfPrevOffset;
    delete el.dataset.gfPrevRadius;
  }

  // Debug do terminala
  async function dbg(payload) {
    try {
      await fetch('/api/debug_key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
      });
    } catch {}
  }

  // stan aktywnego elementu
  let active = null;

  async function setActive(el) {
    const focusables = listFocusables();
    const before = active;
    const newIndex = el ? focusables.indexOf(el) : -1;

    if (before && before !== el) {
      before.classList.remove(ACTIVE_CLASS);
      removeActiveStyle(before); // usuń fallback
    }
    active = el || null;
    if (active) {
      active.classList.add(ACTIVE_CLASS);
      applyActiveStyle(active);  // fallback (jeśli CSS brak)
      if (!active.hasAttribute('tabindex')) active.setAttribute('tabindex', '0');
      active.focus({ preventScroll: true });
      active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    // loguj zmianę aktywnego
    const txt = active ? (active.innerText || active.textContent || '').trim().slice(0,50) : null;
    dbg({ event: 'setActive', index: newIndex, text: txt });
  }

  function activate(el) {
    if (!el) return;
    const action = el.dataset.genter || 'auto';
    if (action === 'auto') {
      if (typeof el.click === 'function') el.click();
      else {
        const form = el.closest('form');
        if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
      }
      return;
    }
    if (action === 'click') { el.click(); return; }
    if (action === 'link')  {
      const href = el.getAttribute('href') || el.dataset.href;
      if (href) window.location.href = href;
      return;
    }
    if (action === 'submit') {
      const form = el.closest('form');
      if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
      return;
    }
    if (action.startsWith('js:')) {
      try { (0, eval)(action.slice(3)); } catch (e) { console.error(e); }
      return;
    }
  }

  function handleKey(e, where) {
    const focusables = listFocusables();
    const k = e.key;
    const kc = e.keyCode || e.which;
    const isArrow = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(k) ||
                    [37,39,38,40].includes(kc);
    const isEnter = (k === 'Enter') || (kc === 13);
    if (!isArrow && !isEnter) return;

    e.preventDefault();
    e.stopPropagation();

    dbg({
      where,
      key: k, code: e.code, keyCode: kc,
      focusables: focusables.length,
      activeIndex: active ? focusables.indexOf(active) : -1,
      activeText: active ? (active.innerText || active.textContent || '').trim().slice(0,50) : null
    });

    if (!focusables.length) return;

    if (!active || !focusables.includes(active)) {
      setActive(focusables[0]);
      return;
    }

    if (isEnter) { activate(active); return; }

    const dir =
      (k === 'ArrowLeft' || kc === 37) ? 'left'  :
      (k === 'ArrowRight'|| kc === 39) ? 'right' :
      (k === 'ArrowUp'   || kc === 38) ? 'up'    :
      (k === 'ArrowDown' || kc === 40) ? 'down'  : null;

    if (dir) {
      const next = findNext(active, focusables, dir);
      if (next) setActive(next);
    }
  }

  window.addEventListener('keydown', (e) => handleKey(e, 'window'));
  document.addEventListener('keydown', (e) => handleKey(e, 'document'), true);

  document.addEventListener('click', (e) => {
    const el = e.target.closest(SELECTOR);
    if (el) setActive(el);
  });

  window.addEventListener('DOMContentLoaded', () => {
    // wymuś fokus na body
    if (document.body && typeof document.body.focus === 'function') {
      document.body.setAttribute('tabindex', '-1');
      document.body.focus({ preventScroll: true });
    }
    const list = listFocusables();
    if (list[0]) setActive(list[0]);
    const mo = new MutationObserver(() => {
      const now = listFocusables();
      if (!now.length) return;
      if (!active || !now.includes(active)) setActive(now[0]);
    });
    mo.observe(document.body, { childList: true, subtree: true, attributes: true });
  });
})();
