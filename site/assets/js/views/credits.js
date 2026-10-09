// Credits: data sources, licences and every team image with its file page.
import { h } from '../ui/dom.js';
import { icon, MARK_SVG } from '../ui/icons.js';
import { loadTeamIndex } from '../ui/teams.js';
import * as data from '../data.js';

export async function mount(root) {
  const [images, meta] = await Promise.all([loadTeamIndex(), data.meta().catch(() => null)]);
  const page = h('div.page.credits-page');
  root.append(page);
  const mark = h('span.credits-mark', { 'aria-hidden': 'true' });
  mark.innerHTML = `<svg viewBox="0 0 64 64" width="64" height="64">${MARK_SVG}</svg>`;
  page.append(h('header.credits-hero', mark, h('div',
    h('div.eyebrow', 'Credits'),
    h('h1.display', 'Sources, licences and thanks'),
    h('p.lede', 'Best Eleven is a non-commercial fan project. It is not affiliated with the ICC, any national board, league or franchise.'))));

  page.append(h('div.rule-title.mt-l', 'Data'));
  page.append(h('div.grid-2.mt',
    source('matchdata', 'Cricsheet', 'https://cricsheet.org',
      'Ball-by-ball data for every match on this site, released under the Open Data Commons Attribution License (ODC-By 1.0).',
      meta ? `Archive checksum ${meta.source.sha256.slice(0, 12)}…, ${meta.source.matches.toLocaleString('en-GB')} matches.` : ''),
    source('database', 'Wikipedia and Wikidata', 'https://en.wikipedia.org',
      'Player attributes, current squads, captaincy records and historic career lists. Text and tables are CC BY-SA 4.0; Wikidata is CC0.',
      'Every reference row keeps its source page and revision id.')));

  page.append(h('div.rule-title.mt-l', 'Team flags and logos'));
  const rows = Object.entries(images).sort((a, b) => a[1].kind.localeCompare(b[1].kind) || a[0].localeCompare(b[0]));
  page.append(h('p.small.muted.mt', 'Country flags come from Wikimedia Commons, mostly in the public domain. Franchise and club logos are trademarks of their owners; they are shown small, next to the team name, only to identify the team, and each links to its file page with the licence stated there.'));
  page.append(h('div.table-wrap.mt', h('table.data', h('thead', h('tr', h('th', 'Team'), h('th', 'Type'), h('th', 'File'), h('th', 'Licence'))),
    h('tbody', rows.map(([team, e]) => h('tr',
      h('td', h('span.team-label', h(`img.team-badge.${e.kind}`, { src: `assets/img/teams/${e.slug}.png`, alt: '', width: 20, height: 20, loading: 'lazy' }), team)),
      h('td.small', e.kind === 'flag' ? 'Flag' : 'Logo'),
      h('td.small', h('a', { href: e.page, rel: 'noopener' }, e.file)),
      h('td.small', e.licence || (e.nonfree ? 'Non-free' : '–'))))))));

  page.append(h('div.rule-title.mt-l', 'Design and code'));
  page.append(h('ul.small.credits-list.mt',
    h('li', 'Typefaces: Fraunces, Inter, Montserrat and JetBrains Mono, all under the SIL Open Font License, served by Google Fonts.'),
    h('li', 'The cricket grounds behind the field plans and the selection room are rendered from code for this project (scripts/render_grounds.py): no stock or AI imagery.'),
    h('li', 'The brand mark, icons and charts are original work made for this project.'),
    h('li', 'Code is MIT licensed. ', h('a', { href: 'https://github.com/Bongo-Seakhoa/best-eleven-lab', rel: 'noopener' }, icon('github', { size: 15 }), ' Source on GitHub'), '.'),
    h('li', 'No player photographs are used anywhere on the site.')));
  return {};
}

function source(ic, name, href, body, note) {
  return h('div.callout.verified', h('span.badge-ico', icon(ic, { size: 24 })),
    h('div', h('div.k', 'Verified source'), h('div.t', h('a', { href, rel: 'noopener' }, name)), h('p', body),
      note ? h('p.tiny.faint', { style: { marginTop: '6px' } }, note) : null));
}
