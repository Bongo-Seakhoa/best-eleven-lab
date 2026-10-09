// Shell: hash router, theme, navigation, data-as-of badge.
import { h, clear } from './ui/dom.js';
import { icon } from './ui/icons.js';
import { loadTeamIndex } from './ui/teams.js';
import * as data from './data.js';

const routes = {
  select: () => import('./views/select.js'),
  players: () => import('./views/players.js'),
  player: () => import('./views/player.js'),
  captains: () => import('./views/captains.js'),
  method: () => import('./views/method.js'),
  credits: () => import('./views/credits.js'),
};

/** Parse "#/player/abc?x=1" -> {name: 'player', arg: 'abc', query: URLSearchParams} */
export function parseHash(hash = location.hash) {
  const raw = hash.replace(/^#\/?/, '');
  const [path, qs = ''] = raw.split('?');
  const [name = '', arg = ''] = path.split('/');
  const route = name === '' ? 'select' : name;
  return { name: routes[route] ? route : 'notfound', arg: decodeURIComponent(arg), query: new URLSearchParams(qs) };
}

/** Replace the query part of the current route without a navigation. */
export function setQuery(params) {
  const { name, arg } = parseHash();
  const base = name === 'select' ? '#/' : `#/${name}${arg ? '/' + encodeURIComponent(arg) : ''}`;
  const qs = new URLSearchParams(params).toString();
  history.replaceState(null, '', qs ? `${base}?${qs}` : base);
}

let current = null;
let renderToken = 0;

async function render() {
  const route = parseHash();
  const main = document.getElementById('main');
  for (const a of document.querySelectorAll('.nav a')) {
    const active = a.dataset.route === route.name || (route.name === 'player' && a.dataset.route === 'players');
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  document.getElementById('nav').classList.remove('open');
  document.getElementById('menu-toggle').setAttribute('aria-expanded', 'false');
  if (current && current.name === route.name && current.arg === route.arg && current.view?.update) {
    current.view.update(route);   // same page, new query: let the view update in place
    return;
  }
  const token = ++renderToken;
  current?.view?.destroy?.();
  clear(main);
  if (route.name === 'notfound') {
    main.append(h('div.page', h('h1.display', 'Not found'), h('p', h('a', { href: '#/' }, 'Back to the selector'))));
    current = null;
    return;
  }
  main.append(h('div.page', h('div.row', h('div.spinner'), h('span.muted', 'Loading…'))));
  try {
    const mod = await routes[route.name]();
    if (token !== renderToken) return;
    clear(main);
    const view = await mod.mount(main, route);
    current = { name: route.name, arg: route.arg, view };
    if (!route.query.toString()) window.scrollTo(0, 0);
  } catch (err) {
    if (token !== renderToken) return;
    console.error(err);
    clear(main);
    main.append(h('div.page', h('div.notice.error', h('div',
      h('strong', 'This page could not load. '), String(err.message || err)))));
  }
}

function initTheme() {
  const btn = document.getElementById('theme-toggle');
  const dark = () => document.documentElement.dataset.theme === 'dark' ||
    (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  const label = () => {
    btn.setAttribute('aria-label', dark() ? 'Switch to light theme' : 'Switch to dark theme');
    btn.replaceChildren(icon(dark() ? 'sun' : 'moon', { size: 18 }));
  };
  label();
  btn.addEventListener('click', () => {
    const next = dark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('be-theme', next); } catch (e) { /* storage unavailable */ }
    label();
    window.dispatchEvent(new Event('themechange'));
  });
}

const NAV_ICONS = { select: 'room', players: 'profile', captains: 'captain', method: 'database', credits: 'info' };
function initNavIcons() {
  for (const a of document.querySelectorAll('.nav a')) {
    const name = NAV_ICONS[a.dataset.route];
    if (name && !a.querySelector('.icon')) a.prepend(icon(name, { size: 17 }));
  }
}

function initMenu() {
  const btn = document.getElementById('menu-toggle');
  const nav = document.getElementById('nav');
  btn.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    btn.setAttribute('aria-expanded', String(open));
  });
}

async function initAsOf() {
  try {
    const m = await data.meta();
    const d = new Date(m.dataEnd);
    document.getElementById('asof').textContent =
      `Data to ${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;
  } catch (e) { /* badge is optional */ }
}

initTheme();
initNavIcons();
initMenu();
initAsOf();
window.addEventListener('hashchange', render);
loadTeamIndex().finally(render);
