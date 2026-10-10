// Small DOM and formatting helpers shared by every view.

/** h('div.card.pad', {onclick, 'aria-label': ...}, child, [children]) */
export function h(tag, attrs, ...children) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className += (el.className ? ' ' : '') + v;
    else if (k === 'style' && typeof v === 'object') {
      // Custom properties (--tc, --c) need setProperty; plain assignment drops them.
      for (const [prop, val] of Object.entries(v)) {
        if (prop.startsWith('--')) el.style.setProperty(prop, val);
        else el.style[prop] = val;
      }
    }
    else if (k === 'html') el.innerHTML = v;
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const svgNS = 'http://www.w3.org/2000/svg';
export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  for (const c of children.flat()) if (c != null) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

export const fmt = {
  n: (x, d = 0) => (x == null || !Number.isFinite(x) ? '–' : x.toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d })),
  avg: (x) => (x == null || !Number.isFinite(x) ? '–' : x.toFixed(2)),
  sr: (x) => (x == null || !Number.isFinite(x) ? '–' : x.toFixed(1)),
  pct: (x, d = 0) => (x == null || !Number.isFinite(x) ? '–' : `${(x * 100).toFixed(d)}%`),
  signed: (x, d = 1) => (x == null || !Number.isFinite(x) ? '–' : `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x).toFixed(d)}`),
  score: (x) => (x == null || !Number.isFinite(x) ? '–' : Math.round(x).toString()),
  age: (dob) => {
    if (!dob) return null;
    const d = new Date(dob);
    if (Number.isNaN(+d)) return null;
    const now = new Date();
    let a = now.getFullYear() - d.getFullYear();
    if (now < new Date(now.getFullYear(), d.getMonth(), d.getDate())) a--;
    return a;
  },
};

export function initials(name) {
  const parts = String(name).replace(/[^A-Za-z\s'-]/g, ' ').trim().split(/\s+/);
  if (!parts.length) return '?';
  const last = parts[parts.length - 1];
  return (parts.length > 1 ? parts[0][0] : '') + last[0];
}

let tipEl = null;
export function tooltip(target, text) {
  const show = (e) => {
    if (!tipEl) { tipEl = h('div.tooltip', { role: 'tooltip' }); document.body.append(tipEl); }
    tipEl.textContent = typeof text === 'function' ? text() : text;
    const r = (e.currentTarget || target).getBoundingClientRect();
    tipEl.classList.add('show');
    const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
    tipEl.style.left = `${Math.max(8, Math.min(window.innerWidth - tw - 8, r.left + r.width / 2 - tw / 2))}px`;
    tipEl.style.top = `${r.top - th - 8 < 8 ? r.bottom + 8 : r.top - th - 8}px`;
  };
  const hide = () => tipEl && tipEl.classList.remove('show');
  target.addEventListener('mouseenter', show);
  target.addEventListener('focus', show);
  target.addEventListener('mouseleave', hide);
  target.addEventListener('blur', hide);
  return target;
}

export function debounce(fn, ms = 120) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** Accessible drawer; returns {body, close}. */
export function drawer(title, subtitle) {
  const backdrop = h('div.drawer-backdrop');
  const closeBtn = h('button.icon-btn', { type: 'button', 'aria-label': 'Close panel' },
    h('span', { 'aria-hidden': 'true', style: { fontSize: '18px', lineHeight: '1' } }, '×'));
  const body = h('div.drawer-body');
  const panel = h('aside.drawer', { role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('div.drawer-head', h('div', h('h2.display', { style: { fontSize: '24px' } }, title),
      subtitle ? h('div.muted.small', subtitle) : null), closeBtn), body);
  const prev = document.activeElement;
  const close = () => {
    panel.classList.remove('open'); backdrop.classList.remove('open');
    document.removeEventListener('keydown', onKey);
    setTimeout(() => { panel.remove(); backdrop.remove(); prev?.focus?.(); }, 250);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  closeBtn.addEventListener('click', close);
  backdrop.addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.append(backdrop, panel);
  requestAnimationFrame(() => { panel.classList.add('open'); backdrop.classList.add('open'); closeBtn.focus(); });
  return { body, close, panel };
}
