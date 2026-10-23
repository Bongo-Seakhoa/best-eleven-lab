import fs from 'node:fs';
import assert from 'node:assert/strict';
import { buildPool } from '../assets/js/engine/select.js';
import { manualPoolFor, previewSwap } from '../assets/js/engine/manual.js';
import { historicPool, HISTORIC_TEMPLATE } from '../assets/js/engine/historic.js';
import { defaults, engineSettings, selectFor, toQuery, fromQuery, idString, idList } from '../assets/js/xistate.js';

const T = { scope: JSON.parse(fs.readFileSync(process.argv[2])), hist: null };
const S = { scope: JSON.parse(fs.readFileSync(process.argv[3])), hist: null };
const ID = '44afbf2d';
const ids = (r) => r.xi.map((x) => x.player.id).sort();
function swap(st, evidence, current, out, incoming, role = null) {
  const saved = JSON.stringify(st);
  const p = previewSwap(st, evidence, current, out.player.id, incoming, role);
  assert.equal(JSON.stringify(st), saved, 'preview must not mutate settings');
  const committed = selectFor(p.state, evidence);
  assert.ok(!committed.error, committed.error);
  assert.deepEqual(ids(committed), ids(p.result));
  assert.deepEqual(ids(committed), [...ids(current).filter((x) => x !== out.player.id), incoming.id].sort());
  assert.ok(Math.abs(committed.total - p.result.total) < 1e-7);
  const restored = selectFor(defaults(fromQuery(new URLSearchParams(toQuery(p.state)))), evidence);
  assert.deepEqual(ids(restored), ids(committed));
  assert.ok(Math.abs(restored.total - committed.total) < 1e-7);
  const sameScale = selectFor({ ...st, lock: idString(ids(current)) }, evidence);
  assert.ok(Math.abs(p.delta - (p.result.total - sameScale.total)) < 1e-7);
  assert.equal(p.role, p.result.xi.find((x) => x.player.id === incoming.id).type);
  return p;
}

const st = defaults({ team: 'Australia', from: 2023, to: 2026 });
const settings = engineSettings(st, T.scope);
const normal = buildPool(T.scope, settings), manual = buildPool(T.scope, { ...settings, manualPool: true });
assert.deepEqual(normal.ref, manual.ref);
assert.ok(!normal.pool.some((p) => p.id === ID));
for (const p of normal.pool) assert.deepEqual(manual.pool.find((x) => x.id === p.id).sc, p.sc);
const madd = manualPoolFor(st, T).find((p) => p.id === ID);
assert.equal(madd.outsideWindow, false);
assert.equal(madd.stats.matches, 1); assert.equal(madd.stats.runs, 48);
assert.equal(madd.recordFrom, 2026); assert.equal(madd.recordTo, 2026);
const base = selectFor(st, T), opener = base.xi.find((x) => x.type === 'opener');
swap(st, T, base, opener, madd);
const role = swap(st, T, base, opener, madd, 'batter');
assert.equal(role.requestedRole, 'batter');
const shapeChange = swap(st, T, base, base.xi.find((x) => x.type === 'pace'), madd);
assert.ok(shapeChange.changes.length);
assert.ok(shapeChange.warnings.some((w) => w.includes('preset')));
const repeated = swap(shapeChange.state, T, shapeChange.result,
  shapeChange.result.xi.find((x) => x.player.id === ID),
  manualPoolFor(shapeChange.state, T).find((p) => p.id === base.xi.find((x) => x.type === 'pace').player.id));
assert.deepEqual(ids(repeated.result), ids(base));

const ts = defaults({ team: 'Australia', f: 'T20I', from: 2023, to: 2026 });
const old = manualPoolFor(ts, S).find((p) => p.id === ID);
assert.equal(old.outsideWindow, true); assert.equal(old.available, false);
assert.equal(old.stats.matches, 6); assert.equal(old.recordFrom, 2013); assert.equal(old.recordTo, 2018);
assert.ok(!Number.isFinite(old.util.spin));
const early = manualPoolFor({ ...ts, from: 2015, to: 2015 }, S).find((p) => p.id === ID);
assert.equal(early.stats.matches, 2); assert.equal(early.recordFrom, 2013); assert.equal(early.recordTo, 2014);
assert.ok(!manualPoolFor({ ...st, from: 2015, to: 2015 }, T).some((p) => p.id === ID));
const ordinary = buildPool(S.scope, engineSettings(ts, S.scope));
const locked = buildPool(S.scope, { ...engineSettings(ts, S.scope), locks: new Set([ID]) });
assert.deepEqual(locked.pool.filter((p) => !ordinary.pool.some((q) => q.id === p.id)).map((p) => p.id), [ID]);
assert.deepEqual(locked.ref, ordinary.ref);
assert.deepEqual(buildPool(S.scope, engineSettings(ts, S.scope)), ordinary, 'cached aggregates must remain unchanged');
const tb = selectFor(ts, S), oldSwap = swap(ts, S, tb, tb.xi[0], old);
assert.ok(oldSwap.warnings.some((w) => w.includes('Earlier record')));

// Controlled membership changes isolate cap behavior from ranking/role choices.
const freeState = { ...st, comp: 'free', av: 'any' };
const free = selectFor(freeState, T);
const freeIds = ids(free);
const extra = manualPoolFor(freeState, T).find((p) => !freeIds.includes(p.id));
const membership = new Map(freeIds.map((id, i) => [id, i < 2 ? 0 : i - 1]));
membership.set(extra.id, 0);
const countries = structuredClone(T.scope);
countries.teams = Array.from({ length: 11 }, (_, i) => `Fixture country ${i}`);
countries.teamsFull = countries.teams.map(() => 1);
countries.seasons.t = countries.seasons.p.map((pi) => membership.get(countries.players.id[pi]) ?? 10);
const worldState = { ...freeState, team: '', mpt: 2, lock: freeIds.join(',') };
const worldEvidence = { scope: countries, hist: null };
const world = selectFor(worldState, worldEvidence);
assert.ok(!world.error, world.error);
const capSwap = swap(worldState, worldEvidence, world,
  world.xi.find((x) => x.player.team !== 0), manualPoolFor(worldState, worldEvidence).find((p) => p.id === extra.id));
assert.equal(capSwap.state.mpt, 3); assert.equal(capSwap.state.mos, worldState.mos);
const unlimited = swap({ ...worldState, mpt: 0 }, worldEvidence, world,
  world.xi.find((x) => x.player.team !== 0), manualPoolFor(worldState, worldEvidence).find((p) => p.id === extra.id));
assert.equal(unlimited.state.mpt, 0);
const league = structuredClone(T.scope); league.tier = 'league';
league.players.overseas = league.players.id.map((id) => membership.get(id) === 0);
const leagueState = { ...freeState, tier: 'league', team: '', mos: 2, lock: freeIds.join(',') };
const leagueEvidence = { scope: league, hist: null }, leagueXI = selectFor(leagueState, leagueEvidence);
assert.ok(!leagueXI.error, leagueXI.error);
const overseas = swap(leagueState, leagueEvidence, leagueXI,
  leagueXI.xi.find((x) => !x.player.overseas), manualPoolFor(leagueState, leagueEvidence).find((p) => p.id === extra.id));
assert.equal(overseas.state.mos, 3); assert.equal(overseas.state.mpt, leagueState.mpt);
const H = { scope: null, hist: JSON.parse(fs.readFileSync(process.argv[4])) };
const hs = defaults({ mode: 'hist', team: 'Australia', quality: 80, legacy: 0 });
const hSettings = { country: 'Australia', weights: hs };
const hNormal = historicPool(H.hist, hSettings), hManual = historicPool(H.hist, { ...hSettings, manualPool: true });
assert.deepEqual(hNormal.ref, hManual.ref);
const hBase = selectFor(hs, H);
assert.ok(!hBase.error, hBase.error);
assert.deepEqual(hBase.slots, HISTORIC_TEMPLATE);
const hExtra = manualPoolFor(hs, H).find((p) => p.id.includes(',') && Number.isFinite(p.util.batter) && !hNormal.pool.some((q) => q.id === p.id));
assert.ok(hExtra, 'the manual career pool should include a real short career');
const hSwap = swap(hs, H, hBase, hBase.xi.find((x) => x.type === 'pace'), hExtra, 'batter');
assert.ok(hSwap.state.slots, 'career mode must retain accepted custom composition');
assert.ok(!hSwap.warnings.some((w) => w.includes('active')));
assert.ok(idList(hSwap.state.lock).includes(hExtra.id));
assert.deepEqual(idList('p1,p2'), ['p1', 'p2']);
assert.deepEqual(selectFor({ ...hs, slots: 'opener11' }, H).slots, HISTORIC_TEMPLATE);
console.log(JSON.stringify({ ok: true, checks: 'records, season cutoff, refs, exact swaps, repeated swaps, URL, roles, caps' }));
