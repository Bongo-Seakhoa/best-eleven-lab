// Team flags and franchise logos (sources in assets/img/teams/index.json).
import { h } from './dom.js';
import { teamColour } from '../data.js';

let index = {};
let loading = null;

/** Load the image index once; resolves to {} if it is missing. */
export function loadTeamIndex() {
  if (!loading) {
    loading = fetch('assets/img/teams/index.json')
      .then((r) => (r.ok ? r.json() : {}))
      .catch(() => ({}))
      .then((d) => { index = d || {}; return index; });
  }
  return loading;
}

export const teamImages = () => index;

/** Small flag or logo; a colour chip when there is no image for the team. */
export function teamBadge(name, { size = 18 } = {}) {
  const e = index[name];
  if (e) {
    return h(`img.team-badge.${e.kind}`, { src: `assets/img/teams/${e.slug}.png`, alt: '', width: size, height: size,
                                           loading: 'lazy', decoding: 'async' });
  }
  return h('span.team-badge.chip', { 'aria-hidden': 'true',
                                     style: { '--tc': teamColour(name), width: `${size}px`, height: `${size}px` } });
}

/** Badge followed by the team name. */
export function teamLabel(name, opts) {
  if (!name) return h('span', '');
  return h('span.team-label', teamBadge(name, opts), h('span', name));
}
