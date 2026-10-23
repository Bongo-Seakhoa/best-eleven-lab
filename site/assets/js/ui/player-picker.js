import { h, clear, fmt, initials } from './dom.js';
import { icon, ROLE_ICON } from './icons.js';
import { teamLabel } from './teams.js';
import { SLOT_TYPES, VIRTUAL_SLOTS } from '../engine/metrics.js';
import { manualPoolFor, preferredRole, previewSwap } from '../engine/manual.js';
import { compositionText, queryString } from '../xistate.js';

const signed = (n) => fmt.signed(n, 1);
const roles = (p) => VIRTUAL_SLOTS.any.filter((r) => Number.isFinite(p.util[r]));

/** Shared, transactional player picker for Best XI and either side of XI vs XI. */
export function playerPicker({ state, evidence, result, outgoingId, incomingId, getState, apply, projection, editPresets, title }) {
  const signature = queryString(state), snapshot = { ...state };
  let closed = false, token = 0, selected = null, preview = null, chosenRole = null;
  let query = '', roleFilter = '', recommendations = false, limit = 40;
  let focusPreview = false;
  const opener = document.activeElement;
  const inXI = new Set(result.xi.map((x) => x.player.id));
  const recommended = new Set(result.pool.filter((p) => p.available !== false).map((p) => p.id));
  const pool = manualPoolFor(snapshot, evidence).filter((p) => !inXI.has(p.id));
  selected = pool.find((p) => p.id === incomingId) ?? null;
  const team = (p) => snapshot.mode === 'hist' ? p.team : evidence.scope.teams[p.team] || '';
  const outgoing = () => result.xi.find((x) => x.player.id === outgoingId);
  const dlg = h('dialog.player-picker', { 'aria-labelledby': 'picker-title' });
  const list = h('div.picker-list', { role: 'group', 'aria-label': 'Available player choices' });
  const count = h('p.tiny.muted.picker-count', { role: 'status' });
  const detail = h('section.picker-preview', { 'aria-label': 'Swap preview', 'aria-live': 'polite' });
  const error = h('p.picker-error.small', { role: 'alert', hidden: true });
  const confirm = h('button.btn.primary', { type: 'button', disabled: true, onclick: confirmSwap }, 'Choose a player');
  const close = () => {
    if (closed) return;
    closed = true; token++; dlg.close(); dlg.remove();
    if (opener?.isConnected) opener.focus();
  };
  const search = h('input.input', { type: 'search', placeholder: 'Find any player in this side…', 'aria-label': 'Search replacement players',
    oninput: (e) => { query = e.target.value.trim().toLowerCase(); limit = 40; drawList(); } });
  const outSelect = h('select.select', { 'aria-label': 'Player to replace', onchange: (e) => {
    outgoingId = e.target.value; chosenRole = null; drawList(); drawPreview();
  } }, result.xi.map((x) => h('option', { value: x.player.id, selected: x.player.id === outgoingId }, x.player.name)));

  function flags(p) {
    return [p.available === false ? (snapshot.av === 'squad' ? 'Outside squad' : 'Not active') : null,
      p.outsideWindow ? `Earlier record ${p.recordFrom}–${p.recordTo}` : null,
      !recommended.has(p.id) && !p.outsideWindow ? 'Outside recommendations' : null].filter(Boolean);
  }
  function record(p) {
    const s = p.stats;
    return [`${fmt.n(s.matches)} ${s.matches === 1 ? 'match' : 'matches'}`, s.runs ? `${fmt.n(s.runs)} runs` : null,
      s.wkts ? `${fmt.n(s.wkts)} wickets` : null].filter(Boolean).join(' · ');
  }
  function drawList() {
    clear(list);
    const shown = pool.filter((p) => (!recommendations || recommended.has(p.id)) &&
      (!roleFilter || roles(p).includes(roleFilter)) &&
      (!query || `${p.name} ${team(p)}`.toLowerCase().includes(query)));
    shown.sort((a, b) => {
      const fit = (p) => Number.isFinite(p.util[outgoing().type]) ? 1 : 0;
      return fit(b) - fit(a) || b.util.any - a.util.any || a.name.localeCompare(b.name);
    });
    for (const p of shown.slice(0, limit)) {
      const role = preferredRole(p, outgoing());
      list.append(h('button.picker-choice', { type: 'button', 'aria-label': `Preview ${p.name}`,
        'aria-pressed': selected?.id === p.id ? 'true' : 'false', onclick: () => { selected = p; chosenRole = null; focusPreview = true; drawList(); drawPreview(); } },
        h('span.avatar', { 'aria-hidden': 'true' }, initials(p.name)),
        h('span.picker-choice-main', h('strong', p.name),
          h('span.tiny.muted', `${SLOT_TYPES[role]?.label || role} · ${team(p)}`),
          h('span.tiny.muted', record(p)),
          flags(p).length ? h('span.picker-tags', flags(p).map((label) => h('span.picker-tag', label))) : null),
        h('span.picker-choice-score', h('strong.num', fmt.score(p.util[role])), h('span.tiny.muted', 'utility'))));
    }
    if (shown.length > limit) list.append(h('button.btn.sm.ghost.picker-more', { type: 'button', onclick: () => {
      const top = list.scrollTop, firstNew = limit; limit += 40; drawList();
      list.scrollTop = top;
      list.querySelectorAll('.picker-choice')[firstNew]?.focus({ preventScroll: true });
    } }, `Show ${Math.min(40, shown.length - limit)} more`));
    if (!shown.length) list.append(h('p.small.muted.picker-empty', 'No recorded players match. Try another name or clear the filters.'));
    count.textContent = `${shown.length} ${shown.length === 1 ? 'choice' : 'choices'} · same-role players first`;
  }
  function playerCard(p, role, label) {
    return h('div.picker-player', h('span.tiny.eyebrow', label),
      h('div.picker-player-name', h('span.avatar', { 'aria-hidden': 'true' }, initials(p.name)), h('strong', p.name)),
      h('div.small.muted', icon(ROLE_ICON[role] || 'ball', { size: 15 }), ` ${SLOT_TYPES[role]?.label || role}`),
      teamLabel(team(p), { size: 16 }), h('p.tiny.muted', record(p)));
  }
  async function drawPreview() {
    const currentToken = ++token;
    preview = null; confirm.disabled = true; error.hidden = true;
    clear(detail);
    if (!selected) {
      detail.append(h('div.picker-empty', icon('shuffle', { size: 32 }), h('h3', 'Build your eleven'),
        h('p.small.muted', 'Choose a replacement to compare the two players and see the effect on your team.'),
        h('p.tiny.muted', 'The other ten players stay. Presets guide recommendations; you can accept a different shape here.')));
      return;
    }
    confirm.textContent = 'Preparing preview…';
    try {
      // Yield once so rapid choices and route changes can invalidate old previews.
      await Promise.resolve();
      const p = previewSwap(snapshot, evidence, result, outgoingId, selected, chosenRole);
      const extra = projection ? await projection(p.result) : [];
      if (closed || currentToken !== token) return;
      preview = p;
      const roleSelect = h('select.select', { 'aria-label': 'Role for replacement', onchange: (e) => { chosenRole = e.target.value; focusPreview = true; drawPreview(); } },
        roles(selected).map((r) => h('option', { value: r, selected: p.requestedRole === r }, SLOT_TYPES[r].label)));
      detail.append(h('div.picker-impact', h('h3', p.changes.length ? 'This pick adjusts your presets' : 'Fits your current presets'),
          h('div.picker-tags', p.warnings.map((w) => h('span.picker-tag.warning', icon('warn', { size: 12 }), w)))),
        h('div.picker-pair', playerCard(p.outgoing.player, p.outgoing.type, 'Out'), playerCard(p.incoming, p.role, 'In')),
        h('label.field.picker-role', h('span.small', 'Role added to shape'), roleSelect),
        h('div.picker-metrics',
          Number.isFinite(p.delta) ? metric('Team utility', p.delta, 'points across the XI') : null,
          (extra || []).map((m) => metric(m.label, m.value, m.note))),
        h('div.picker-composition',
          h('p.tiny.muted', compositionText(p.slots)),
          p.changes.length ? h('p.small', p.changes.join(' · ')) : null,
          h('p.tiny.muted', 'The other ten players are kept. Roles may rebalance within this XI. Your eleven and presets are saved in the link.')));
      confirm.textContent = p.changes.length ? 'Swap & update presets' : 'Confirm swap';
      confirm.disabled = false;
      if (focusPreview) { roleSelect.focus(); focusPreview = false; }
    } catch (e) {
      if (closed || currentToken !== token) return;
      error.textContent = `Could not preview this swap. Your XI is unchanged. ${e.message}`;
      error.hidden = false; confirm.textContent = 'Preview unavailable';
    }
  }
  function metric(label, value, note) {
    return h('div.picker-metric', h('span.tiny.muted', label), h(`strong.num.${value >= 0 ? 'up' : 'down'}`, signed(value)), h('span.tiny.muted', note));
  }
  async function confirmSwap() {
    if (!preview || closed) return;
    if (queryString(getState()) !== signature) {
      error.textContent = 'Your settings changed. Close this picker and open it again to preview the current XI.';
      error.hidden = false; confirm.disabled = true; return;
    }
    confirm.disabled = true;
    try { const restoreFocus = await apply(preview); close(); restoreFocus?.(); }
    catch (e) { error.textContent = `Could not apply this swap. Your XI is unchanged. ${e.message}`; error.hidden = false; confirm.disabled = false; }
  }
  dlg.append(h('header.picker-head', h('div', h('div.eyebrow', title || 'Your selection'), h('h2.display', { id: 'picker-title' }, 'Make a swap')),
    h('button.icon-btn', { type: 'button', 'aria-label': 'Close player picker', onclick: close }, '×')),
    h('div.picker-out', h('label.small', 'Swap out', outSelect), h('span.tiny.muted', 'One change. The other ten stay.')),
    h('div.picker-body', h('section.picker-browser', { 'aria-label': 'Find a replacement' },
      h('div.picker-tools', h('div.input-icon', icon('search', { size: 16 }), search),
        h('div.picker-filters', h('select.select', { 'aria-label': 'Filter replacement role', onchange: (e) => { roleFilter = e.target.value; limit = 40; drawList(); } },
          h('option', { value: '' }, 'All roles'), VIRTUAL_SLOTS.any.map((r) => h('option', { value: r }, SLOT_TYPES[r].label))),
        h('label.tiny.picker-toggle', h('input', { type: 'checkbox', onchange: (e) => { recommendations = e.target.checked; limit = 40; drawList(); } }), 'Recommendations only'))),
      count, list), detail),
    h('footer.picker-footer', h('div', error,
      h('span.tiny.muted', 'Players need a recorded, scorable role in this team and format. Earlier records are labelled.')),
      h('div.picker-actions', h('button.btn.ghost', { type: 'button', onclick: () => { close(); editPresets?.(); } }, 'Edit presets'),
        h('button.btn.ghost', { type: 'button', onclick: close }, 'Cancel'), confirm)));
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
  document.body.append(dlg); drawList(); drawPreview(); dlg.showModal(); search.focus();
  return { close };
}
