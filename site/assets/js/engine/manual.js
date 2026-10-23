// Manual selection uses the same pool, scorer and exact solver as recommendations.
import { buildPool } from './select.js';
import { historicPool } from './historic.js';
import { SLOT_TYPES, VIRTUAL_SLOTS } from './metrics.js';
import { engineSettings, selectFor, slotsFor, slotsStr, idList, idString } from '../xistate.js';

const ids = (value) => new Set(idList(value));
const counts = (xi) => {
  const out = new Map();
  for (const x of xi) out.set(x.type, (out.get(x.type) || 0) + 1);
  return [...out].map(([type, count]) => ({ type, count }));
};
const sameShape = (a, b) => slotsStr(a.slice().sort((x, y) => x.type.localeCompare(y.type))) ===
  slotsStr(b.slice().sort((x, y) => x.type.localeCompare(y.type)));

/** All scored players with real records in this side's scope, including manual exceptions. */
export function manualPoolFor(st, evidence) {
  const settings = st.mode === 'hist' ? {
    country: st.team || null, fullOnly: !!st.fo,
    weights: { quality: st.quality, legacy: st.legacy, experience: st.experience, leadership: st.leadership },
    manualPool: true,
  } : { ...engineSettings(st, evidence.scope), manualPool: true, slots: [{ type: 'any', count: 11 }] };
  const { pool } = st.mode === 'hist' ? historicPool(evidence.hist, settings) : buildPool(evidence.scope, settings);
  return pool.filter((p) => Number.isFinite(p.util.any));
}

export function preferredRole(player, outgoing) {
  return Number.isFinite(player.util[outgoing.type]) ? outgoing.type : player.pick.any;
}

/** Preview is pure: state is only applied by the view after explicit confirmation. */
export function previewSwap(st, evidence, current, outgoingId, incoming, roleOverride = null) {
  const outgoing = current.xi.find((x) => x.player.id === outgoingId);
  if (!outgoing || current.xi.some((x) => x.player.id === incoming.id)) throw new Error('Choose a player outside this eleven.');
  const role = roleOverride ?? preferredRole(incoming, outgoing);
  if (!VIRTUAL_SLOTS.any.includes(role) || !Number.isFinite(incoming.util[role])) throw new Error('No recorded role can be scored for this player.');
  const proposed = current.xi.map((x) => x === outgoing ? { type: role, player: incoming } : x);
  const next = { ...st };
  const warnings = [], changes = [];
  const beforeSlots = slotsFor(st, evidence.scope?.family ?? 'multi');
  const virtual = beforeSlots.length === 1 ? VIRTUAL_SLOTS[beforeSlots[0].type] : null;
  const fitsVirtual = virtual?.includes(role);
  const shape = counts(proposed);
  if ((!virtual && !sameShape(beforeSlots, shape)) || (virtual && !fitsVirtual)) {
    next.comp = ''; next.slots = slotsStr(shape);
    const before = new Map((virtual ? counts(current.xi) : beforeSlots).map((s) => [s.type, s.count]));
    for (const s of shape) {
      const prior = before.get(s.type) || 0;
      if (s.count > prior) warnings.push(`${s.count} ${SLOT_TYPES[s.type].label.toLowerCase()}${s.count === 1 ? '' : 's'} · preset ${prior}`);
    }
    changes.push('Composition will match this eleven');
  }
  const constraints = st.mode === 'hist'
    ? { maxPerTeam: st.team ? null : st.mpt || null }
    : engineSettings(st, evidence.scope);
  if (constraints.maxPerTeam) {
    const teams = new Map();
    for (const x of proposed) teams.set(x.player.team, (teams.get(x.player.team) || 0) + 1);
    const largest = Math.max(...teams.values());
    if (largest > constraints.maxPerTeam) {
      warnings.push(`${largest} from one country · cap ${constraints.maxPerTeam}`);
      next.mpt = largest; changes.push(`Country cap ${constraints.maxPerTeam} → ${largest}`);
    }
  }
  if (constraints.maxOverseas != null) {
    const overseas = proposed.filter((x) => x.player.overseas).length;
    if (overseas > constraints.maxOverseas) {
      warnings.push(`${overseas} overseas players · cap ${constraints.maxOverseas}`);
      next.mos = overseas; changes.push(`Overseas cap ${constraints.maxOverseas} → ${overseas}`);
    }
  }
  if (incoming.available === false) warnings.push(st.av === 'squad' ? 'Outside the current squad' : 'Not marked active');
  if (incoming.outsideWindow) warnings.push(`Earlier record · ${incoming.recordFrom}–${incoming.recordTo}`);
  if (!current.pool.some((p) => p.id === incoming.id)) warnings.push('Below recommendation evidence threshold');
  const excludes = ids(st.excl); excludes.add(outgoingId); excludes.delete(incoming.id);
  next.lock = idString(proposed.map((x) => x.player.id));
  next.excl = idString(excludes);
  const result = selectFor(next, evidence);
  if (result.error) throw new Error(result.error);
  const selected = new Set(result.xi.map((x) => x.player.id));
  if (selected.size !== 11 || proposed.some((x) => !selected.has(x.player.id))) {
    throw new Error('This swap could not preserve the other ten players.');
  }
  // A relaxed recommendation may use a different reference cohort. Re-score the
  // current eleven at the same evidence setting before displaying a difference.
  const baseline = selectFor({ ...st, lock: idString(current.xi.map((x) => x.player.id)) }, evidence);
  const delta = baseline.error ? null : result.total - baseline.total;
  const actualRole = result.xi.find((x) => x.player.id === incoming.id).type;
  return { state: next, result, outgoing, incoming, role: actualRole, requestedRole: role, warnings, changes, delta, slots: result.slots ?? shape };
}
