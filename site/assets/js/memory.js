// Where each main page was left, so moving between pages never loses work.
// The four sections run left to right in menu order, and links between them
// point the same way: Best XI, Players, Captains, XI vs XI.
//
// Saved pages persist in this browser (localStorage); the visit trail and
// scroll positions belong to the tab (sessionStorage). Storage failures fall
// back to memory, so the site still works in private windows.

export const SECTIONS = ['select', 'players', 'captains', 'versus'];
export const SECTION_LABEL = { select: 'Best XI', players: 'Players', captains: 'Captains', versus: 'XI vs XI' };

const PAGES_KEY = 'be-pages';
const TRAIL_KEY = 'be-trail';
const SCROLL_KEY = 'be-scroll';
const TRAIL_MAX = 12;
const SCROLL_MAX = 40;

function read(store, key, fallback) {
  try { const v = JSON.parse(window[store].getItem(key) || 'null'); return v ?? fallback; } catch (e) { return fallback; }
}
function write(store, key, value) {
  try { window[store].setItem(key, JSON.stringify(value)); } catch (e) { /* storage unavailable: memory only */ }
}

// A saved address must belong to its section; anything else (a corrupt or
// hand-edited entry) is ignored rather than followed.
const OWN = {
  select: /^#\/(\?|$)/, players: /^#\/(players(\?|$)|player\/)/, captains: /^#\/captains(\?|$)/, versus: /^#\/versus(\?|$)/,
};
function clean(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) return {};
  const out = {};
  for (const s of SECTIONS) {
    const e = p[s];
    if (e && typeof e.href === 'string' && OWN[s].test(e.href)) {
      out[s] = { href: e.href, title: typeof e.title === 'string' ? e.title : undefined,
                 dirHref: typeof e.dirHref === 'string' && OWN.players.test(e.dirHref) ? e.dirHref : undefined };
    }
  }
  return out;
}

let pages = clean(read('localStorage', PAGES_KEY, {}));
let trail = read('sessionStorage', TRAIL_KEY, []);
let scrolls = read('sessionStorage', SCROLL_KEY, {});
if (!Array.isArray(trail)) trail = [];
if (typeof scrolls !== 'object' || Array.isArray(scrolls)) scrolls = {};

const listeners = new Set();
const notify = () => { for (const fn of listeners) fn(); };
export const onMemory = (fn) => listeners.add(fn);

// Another tab may have saved since this one loaded: read before every change, and follow its writes.
const fresh = () => { pages = clean(read('localStorage', PAGES_KEY, pages)); };
window.addEventListener('storage', (e) => { if (e.key === PAGES_KEY) { fresh(); notify(); } });

/** Section for a route name ('player' belongs to Players), or null. */
export function sectionOf(routeName) {
  if (routeName === 'player') return 'players';
  return SECTIONS.includes(routeName) ? routeName : null;
}

/** {href, title, dirHref?} for a section, or null when it has never been used. */
export const saved = (section) => (pages[section]?.href ? pages[section] : null);

/** Record where a section now is. `dirHref` keeps the player directory's own filters. */
export function rememberHref(routeName, href) {
  const section = sectionOf(routeName);
  if (!section || !OWN[section].test(href)) return;
  fresh();
  const prev = pages[section] || {};
  // Another page (a different player, say) drops the old title until its view sets one;
  // new settings on the same page keep it, since views set the title as they render.
  const path = (x) => (x || '').split('?')[0];
  const next = { ...prev, href, title: path(prev.href) === path(href) ? prev.title : undefined };
  if (routeName === 'players') next.dirHref = href;
  pages = { ...pages, [section]: next };
  write('localStorage', PAGES_KEY, pages);
  notify();
}

/** Short description of the section's saved state, shown on return links. */
export function rememberTitle(section, title) {
  if (!OWN[section].test(location.hash)) return;   // a view that is no longer on screen keeps quiet
  fresh();
  if (!pages[section]) return;
  pages = { ...pages, [section]: { ...pages[section], title } };
  write('localStorage', PAGES_KEY, pages);
  notify();
}

/** Drop a saved state that no longer loads. */
export function forget(section) {
  fresh();
  const { [section]: _, ...rest } = pages;
  pages = rest;
  write('localStorage', PAGES_KEY, pages);
  notify();
}

/** Where a bare menu link should land: the saved state, or null for the default page. */
export function restoreHref(routeName) {
  const p = pages[sectionOf(routeName)];
  if (!p) return null;
  return routeName === 'players' ? p.dirHref || null : p.href;
}

export function visit(routeName) {
  const section = sectionOf(routeName);
  if (!section || trail[trail.length - 1] === section) return;
  trail = [...trail, section].slice(-TRAIL_MAX);
  write('sessionStorage', TRAIL_KEY, trail);
}

/**
 * The (up to) two sections visited most recently before this one that still
 * have a saved state, each with the direction its link points.
 */
export function neighbours(current, limit = 2) {
  const out = [];
  for (let i = trail.length - 1; i >= 0 && out.length < limit; i--) {
    const s = trail[i];
    if (s === current || out.some((o) => o.section === s) || !saved(s)) continue;
    out.push({ section: s, ...pages[s], dir: SECTIONS.indexOf(s) < SECTIONS.indexOf(current) ? 'left' : 'right' });
  }
  return out.sort((a, b) => SECTIONS.indexOf(a.section) - SECTIONS.indexOf(b.section));
}

export function saveScroll(href, y) {
  if (!href) return;
  const { [href]: _, ...rest } = scrolls;
  scrolls = { ...rest, [href]: Math.round(y) };
  const keys = Object.keys(scrolls);
  if (keys.length > SCROLL_MAX) for (const k of keys.slice(0, keys.length - SCROLL_MAX)) delete scrolls[k];
  write('sessionStorage', SCROLL_KEY, scrolls);
}

export const savedScroll = (href) => scrolls[href] ?? null;
