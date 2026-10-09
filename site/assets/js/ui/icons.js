// Original line icons on a 24px grid. Stroke uses currentColor so icons follow
// the theme and whatever text colour surrounds them.
import { s } from './dom.js';

const P = {
  // cricket roles
  bat: '<g transform="rotate(38 12 12)"><path d="M11 2.5h2v6.5h-2z"/><path d="M8.6 9h6.8v10.2a2.6 2.6 0 0 1-2.6 2.6h-1.6a2.6 2.6 0 0 1-2.6-2.6z"/><path d="M12 12.5v6" opacity=".5"/></g>',
  ball: '<circle cx="12" cy="12" r="7.5"/><path d="M8.6 5.4c1.9 4.1 1.9 9.1 0 13.2M15.4 5.4c-1.9 4.1-1.9 9.1 0 13.2" stroke-dasharray="1.6 1.6"/>',
  opener: '<g transform="rotate(38 10 13) translate(-2 1)"><path d="M11 2.5h2v6.5h-2z"/><path d="M8.6 9h6.8v10.2a2.6 2.6 0 0 1-2.6 2.6h-1.6a2.6 2.6 0 0 1-2.6-2.6z"/></g><path d="M15.5 4.5h4v4M19.5 4.5l-5 5"/>',
  finisher: '<g transform="rotate(38 10 13) translate(-2 1)"><path d="M11 2.5h2v6.5h-2z"/><path d="M8.6 9h6.8v10.2a2.6 2.6 0 0 1-2.6 2.6h-1.6a2.6 2.6 0 0 1-2.6-2.6z"/></g><path d="M16 9.5V2.8h5l-1.2 1.6 1.2 1.6h-5"/>',
  keeper: '<path d="M7.5 21v-8.6a1.5 1.5 0 0 1 3 0v-.4V5.6a1.5 1.5 0 0 1 3 0V11V6.6a1.5 1.5 0 0 1 3 0v6a1.5 1.5 0 0 1 3 .3V15a6 6 0 0 1-6 6z"/><path d="M7.5 16.5h11" opacity=".5"/>',
  allrounder: '<g transform="rotate(38 12 11) translate(1 -1)"><path d="M11 2.5h2v6.5h-2z"/><path d="M8.6 9h6.8v10.2a2.6 2.6 0 0 1-2.6 2.6h-1.6a2.6 2.6 0 0 1-2.6-2.6z"/></g><circle cx="6" cy="17.5" r="3.4"/><path d="M4.6 15.1c.8 1.5.8 3.3 0 4.8" stroke-dasharray="1 1"/>',
  pace: '<circle cx="15" cy="12" r="6"/><path d="M12.4 6.9c1.5 3.2 1.5 7 0 10.2" stroke-dasharray="1.4 1.4"/><path d="M2.5 9h5M1.5 12h5.5M2.5 15h5"/>',
  spin: '<circle cx="12" cy="12.5" r="5.2"/><path d="M10 7.9c1.3 2.9 1.3 6.3 0 9.2" stroke-dasharray="1.3 1.3"/><path d="M4.3 9.3A8.5 8.5 0 0 1 18.6 6"/><path d="M18.9 2.8l-.3 3.3-3.3-.4"/>',
  bowler: '<circle cx="12" cy="12" r="7.5"/><path d="M8.6 5.4c1.9 4.1 1.9 9.1 0 13.2M15.4 5.4c-1.9 4.1-1.9 9.1 0 13.2" stroke-dasharray="1.6 1.6"/>',
  stumps: '<path d="M8 7v13M12 7v13M16 7v13M7 5.5h4.4M12.6 5.5H17"/>',
  captain: '<circle cx="12" cy="12" r="8.5"/><path d="M15.2 9.2a4 4 0 1 0 0 5.6"/>',
  field: '<ellipse cx="12" cy="12" rx="9.5" ry="9.5"/><ellipse cx="12" cy="12" rx="4.6" ry="4.6" stroke-dasharray="1.5 1.8"/><path d="M11 9.5h2v5h-2z"/>',
  // interface
  home: '<path d="M3.5 11L12 4l8.5 7" /><path d="M5.5 9.5V20h13V9.5" fill="var(--icon-fill, none)"/><path d="M10 20v-5h4v5"/>',
  room: '<circle cx="12" cy="7.5" r="3" fill="var(--icon-fill, none)"/><circle cx="5.8" cy="9.5" r="2.3" fill="var(--icon-fill, none)"/><circle cx="18.2" cy="9.5" r="2.3" fill="var(--icon-fill, none)"/><path d="M6.5 19.5a5.5 5.5 0 0 1 11 0z" fill="var(--icon-fill, none)"/><path d="M2 19.5a4 4 0 0 1 5.2-3.8M22 19.5a4 4 0 0 0-5.2-3.8"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v5.2L5.2 18.3A1.5 1.5 0 0 0 6.5 20.5h11a1.5 1.5 0 0 0 1.3-2.2L13.5 8.7V3.5"/><path d="M7.4 15h9.2l1.7 3.3a.9.9 0 0 1-.8 1.2H6.5a.9.9 0 0 1-.8-1.2z" fill="var(--icon-fill, none)"/>',
  bars: '<path d="M4 20.5h16"/><rect x="5" y="13" width="3.4" height="7.5" fill="var(--icon-fill, none)"/><rect x="10.3" y="9" width="3.4" height="11.5" fill="var(--icon-fill, none)"/><rect x="15.6" y="4.5" width="3.4" height="16" fill="var(--icon-fill, none)"/>',
  database: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8" fill="var(--icon-fill, none)"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13M4.5 10c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8M4.5 14.4c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
  matchdata: '<circle cx="12" cy="12" r="8.5" fill="var(--icon-fill, none)"/><path d="M6.5 17.8L17.8 6.5M8.3 19.2L19.2 8.3" /><path d="M7.4 18.5l2-2M9.6 16.3l2-2M11.8 14.1l2-2M14 11.9l2-2" opacity=".6"/>',
  export: '<path d="M14 3.5H6.5v17h11V7z" fill="var(--icon-fill, none)"/><path d="M14 3.5V7h3.5"/><path d="M12 13.5h9M18.5 10.5l3 3-3 3"/>',
  compare: '<rect x="3.5" y="3.5" width="11" height="11" rx="1" fill="var(--icon-fill, none)"/><rect x="9.5" y="9.5" width="11" height="11" rx="1" fill="var(--icon-fill, none)"/>',
  profile: '<circle cx="12" cy="8" r="4" fill="var(--icon-fill, none)"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0z" fill="var(--icon-fill, none)"/>',
  bookmark: '<path d="M6.5 3.5h11v17L12 16l-5.5 4.5z" fill="var(--icon-fill, none)"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  gauge: '<path d="M4 16a8 8 0 1 1 16 0"/><path d="M12 16l4-5"/><circle cx="12" cy="16" r="1.4" fill="currentColor"/>',
  star: '<path d="M12 3.5l2.6 5.6 6 .7-4.5 4.1 1.2 6-5.3-3-5.3 3 1.2-6-4.5-4.1 6-.7z" fill="currentColor" stroke="none"/>',
  shield: '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.5-4.3-1.2-7.5-4.9-7.5-9.5V6z" fill="currentColor" stroke="none"/><path d="M8.6 12.2l2.4 2.4 4.6-4.8" stroke="var(--surface)" stroke-width="2"/>',
  wicket: '<path d="M8 6.5v14M12 6.5v14M16 6.5v14M7 4.6h4.3M12.7 4.6H17" stroke-width="2.2"/>',
  calendar: '<rect x="4" y="5.5" width="16" height="15" rx="2" fill="var(--icon-fill, none)"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  unlock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 6.8-1.2"/>',
  exclude: '<circle cx="12" cy="12" r="8.5"/><path d="M6 18L18 6"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.6v.1"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6L6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4"/>',
  moon: '<path d="M20.5 13.4A8.5 8.5 0 1 1 10.6 3.5a6.6 6.6 0 0 0 9.9 9.9z"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  users: '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18.5 20a6.5 6.5 0 0 0-3-5.5"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/>',
  shuffle: '<path d="M3 7h3.5c4 0 6 10 10 10H21M3 17h3.5c1.6 0 2.9-1.6 4-3.6M13.5 9.6C14.6 8 15.8 7 17 7h4M18 4l3 3-3 3M18 14l3 3-3 3"/>',
  filter: '<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z"/>',
  trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  github: '<path d="M9 19c-4 1.3-4-2-6-2.5M15 21v-3.6a3.1 3.1 0 0 0-.9-2.4c2.9-.3 6-1.4 6-6.4A5 5 0 0 0 18.8 5 4.6 4.6 0 0 0 18.7 1.5S17.6 1.2 15 3a12.3 12.3 0 0 0-6 0C6.4 1.2 5.3 1.5 5.3 1.5A4.6 4.6 0 0 0 5.2 5 5 5 0 0 0 4 8.6c0 5 3.1 6.1 6 6.4a3.1 3.1 0 0 0-.9 2.4V21"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 19V7.5A1.5 1.5 0 0 1 5.5 6H10"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  warn: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.2v.1"/>',
};

/** icon('bat', {size: 18, label: 'Opener'}) -> <svg>. Decorative unless a label is given. */
export function icon(name, { size = 18, label = null, cls = '' } = {}) {
  const el = s('svg', {
    viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor',
    'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    class: `icon ${cls}`.trim(), 'aria-hidden': label ? null : 'true', role: label ? 'img' : null,
    'aria-label': label,
  });
  el.innerHTML = P[name] || P.info;
  return el;
}

export const ROLE_ICON = { opener: 'opener', batter: 'bat', finisher: 'finisher', keeper: 'keeper',
                           allrounder: 'allrounder', pace: 'pace', spin: 'spin', bowler: 'bowler' };

/** The brand mark: the numeral 11 in a gold-ruled square, as on the brand board. */
export function logoMark(size = 36) {
  const el = s('svg', { viewBox: '0 0 64 64', width: size, height: size, 'aria-hidden': 'true', class: 'logo-mark' });
  el.innerHTML = MARK_SVG;
  return el;
}

export const MARK_SVG = `<rect width="64" height="64" rx="3" fill="var(--logo-bg, #173d2c)"/>
  <rect x="5" y="5" width="54" height="54" fill="none" stroke="var(--logo-seam, #c9aa6c)" stroke-width="1.6"/>
  <text x="32" y="46" text-anchor="middle" font-family="Fraunces, Georgia, 'Times New Roman', serif" font-weight="600"
        font-size="38" letter-spacing="-2.5" fill="var(--logo-ink, #dcc38f)">11</text>`;

/** Brand-board pitch: a square of turf with the strip and creases. */
export function pitchArt(size = 160) {
  const el = s('svg', { viewBox: '0 0 160 140', width: size, 'aria-hidden': 'true', class: 'pitch-art' });
  el.innerHTML = `<rect width="160" height="140" rx="6" fill="var(--logo-bg, #173d2c)"/>
    <rect x="14" y="14" width="132" height="112" fill="none" stroke="#f3ead2" stroke-opacity=".75" stroke-width="1.2"/>
    <rect x="30" y="38" width="100" height="64" fill="none" stroke="#f3ead2" stroke-opacity=".55" stroke-dasharray="4 4"/>
    <rect x="68" y="26" width="24" height="88" fill="#d9c08a"/>
    <path d="M68 38h24M68 102h24" stroke="#173d2c" stroke-width="1.2"/>
    <path d="M74 14v18M80 14v18M86 14v18M74 108v18M80 108v18M86 108v18" stroke="#f3ead2" stroke-width="2"/>`;
  return el;
}

/** Brand-board ground: a round field, the inner ring and a few fielders. */
export function groundArt(size = 180) {
  const el = s('svg', { viewBox: '0 0 180 180', width: size, 'aria-hidden': 'true', class: 'ground-art' });
  const dots = [[90, 38], [134, 62], [142, 104], [90, 142], [38, 104], [46, 62]];
  el.innerHTML = `<circle cx="90" cy="90" r="88" fill="var(--logo-bg, #173d2c)"/>
    <circle cx="90" cy="90" r="76" fill="none" stroke="#f3ead2" stroke-opacity=".55" stroke-width="1.2"/>
    <circle cx="90" cy="90" r="52" fill="none" stroke="#f3ead2" stroke-opacity=".7" stroke-dasharray="3 5"/>
    <circle cx="90" cy="90" r="17" fill="none" stroke="#f3ead2" stroke-opacity=".35"/>
    <rect x="85" y="76" width="10" height="28" rx="1.5" fill="#d9c08a"/>
    ${dots.map(([x, y], i) => `<circle class="fa-dot" style="--d:${i * 80}ms" cx="${x}" cy="${y}" r="4.2" fill="#f3ead2"/>`).join('')}`;
  return el;
}

/** Brand-board ball: deep red leather, raised seam, soft highlight. */
export function ballArt(size = 120) {
  const el = s('svg', { viewBox: '0 0 120 120', width: size, 'aria-hidden': 'true', class: 'ball-art' });
  el.innerHTML = `<defs>
      <radialGradient id="ba-l" cx=".36" cy=".32" r=".75"><stop offset="0" stop-color="#c0392f"/><stop offset=".55" stop-color="#8f1d1d"/><stop offset="1" stop-color="#5a0f12"/></radialGradient>
    </defs>
    <circle cx="60" cy="60" r="56" fill="url(#ba-l)"/>
    <path d="M30 96C52 80 82 48 94 22M36 102C58 86 88 54 100 28" fill="none" stroke="#f1dcc0" stroke-width="2.2" stroke-linecap="round" opacity=".9"/>
    <path d="M33 92l4 5M40 86l4 5M47 80l4 5M54 73l4 5M61 66l4 5M68 58l4 5M75 50l4 5M82 41l4 5M89 32l4 5" stroke="#f1dcc0" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>
    <ellipse cx="42" cy="34" rx="16" ry="9" fill="#fff" opacity=".12" transform="rotate(-30 42 34)"/>`;
  return el;
}

/** Decorative oval with mown stripes, the 30-yard circle, a pitch and eleven fielders. */
export function fieldArt({ width = 420, title = null } = {}) {
  const el = s('svg', { viewBox: '0 0 420 320', width, class: 'field-art', 'aria-hidden': title ? null : 'true',
                        role: title ? 'img' : null, 'aria-label': title });
  const fielders = [[210, 196], [197, 214], [223, 214], [244, 206], [270, 160], [262, 104], [176, 92], [128, 140],
                    [150, 222], [312, 248], [96, 248]];
  el.innerHTML = `
    <defs>
      <clipPath id="fa-oval"><ellipse cx="210" cy="160" rx="196" ry="146"/></clipPath>
      <radialGradient id="fa-glow" cx=".5" cy=".45" r=".6"><stop offset="0" stop-color="var(--pitch-2)" stop-opacity=".22"/><stop offset="1" stop-color="var(--pitch)" stop-opacity=".05"/></radialGradient>
    </defs>
    <ellipse cx="210" cy="160" rx="196" ry="146" fill="url(#fa-glow)" stroke="var(--pitch)" stroke-opacity=".35" stroke-width="1.5"/>
    <g clip-path="url(#fa-oval)" fill="var(--pitch)" opacity=".07">
      ${Array.from({ length: 11 }, (_, i) => `<rect x="${14 + i * 36}" y="0" width="18" height="320"/>`).join('')}
    </g>
    <ellipse cx="210" cy="160" rx="104" ry="80" fill="none" stroke="var(--pitch)" stroke-opacity=".45" stroke-width="1.3" stroke-dasharray="4 6"/>
    <rect x="202" y="112" width="16" height="96" rx="2" fill="var(--gold-soft)" stroke="var(--gold)" stroke-opacity=".55"/>
    <path d="M198 124h24M198 196h24" stroke="var(--gold)" stroke-opacity=".6"/>
    <path d="M210 118 C 236 150, 300 210, 330 246" fill="none" stroke="var(--ball)" stroke-width="1.6" stroke-dasharray="2 5" stroke-linecap="round" opacity=".7"/>
    <circle cx="330" cy="246" r="4.5" fill="var(--ball)"/>
    ${fielders.map(([x, y], i) => `<g class="fa-dot" style="--d:${i * 70}ms"><circle cx="${x}" cy="${y}" r="7.5" fill="var(--surface)" stroke="var(--pitch)" stroke-width="2"/><circle cx="${x}" cy="${y}" r="3" fill="var(--pitch)"/></g>`).join('')}`;
  return el;
}

/** Shown when no eleven fits: stumps with the bails flying. */
export function bailsArt() {
  const el = s('svg', { viewBox: '0 0 120 90', width: 120, 'aria-hidden': 'true', class: 'bails-art' });
  el.innerHTML = `
    <path d="M40 84V36M60 84V36M80 84V36" stroke="var(--gold)" stroke-width="5" stroke-linecap="round"/>
    <path d="M36 82h48" stroke="var(--line)" stroke-width="3" stroke-linecap="round"/>
    <rect x="30" y="18" width="18" height="5" rx="2.5" fill="var(--gold)" transform="rotate(-28 39 20)"/>
    <rect x="66" y="10" width="18" height="5" rx="2.5" fill="var(--gold)" transform="rotate(22 75 12)"/>
    <circle cx="96" cy="44" r="7" fill="var(--ball)"/>
    <path d="M93 39c1.6 3 1.6 7 0 10" stroke="var(--surface)" stroke-width="1.2" stroke-dasharray="1.4 1.4" fill="none"/>
    <path d="M18 30l6 3M14 44h7M20 56l5-3" stroke="var(--muted)" stroke-width="2" stroke-linecap="round"/>`;
  return el;
}
