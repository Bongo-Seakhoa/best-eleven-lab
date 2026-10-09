// Command-line bridge to the browser selection engine (used by `best-eleven select`).
import { readFileSync } from 'node:fs';
import { selectXI, defaultSlots, PRESETS, SLOT_TYPES } from '../assets/js/engine/select.js';

const opt = JSON.parse(process.argv[2]);
const scope = JSON.parse(readFileSync(opt.scope, 'utf8'));
const preset = PRESETS[opt.preset] ?? PRESETS.balanced;
const to = opt.to ?? scope.years[1];
const from = opt.from ?? (opt.preset === 'legacy' ? scope.years[0] : to - 3);
const team = opt.team ? scope.teams.indexOf(opt.team) : null;
if (opt.team && team < 0) {
  process.stdout.write(JSON.stringify({ error: `Unknown team "${opt.team}". Teams: ${scope.teams.join(', ')}` }));
  process.exit(0);
}
const res = selectXI(scope, {
  from, to, team, fullOnly: scope.tier === 'national' && opt.fullOnly !== false && team === null,
  halfLife: preset.halfLife, evidence: 1, availability: opt.availability ?? 'any',
  weights: preset.weights, slots: defaultSlots(scope.family),
  maxPerTeam: team === null && scope.tier === 'national' ? opt.maxPerTeam : null,
  maxOverseas: scope.tier === 'league' ? (opt.maxOverseas ?? scope.maxOverseas ?? null) : null,
});
if (res.error) {
  process.stdout.write(JSON.stringify({ error: res.error, shortfall: res.shortfall }));
  process.exit(0);
}
const f1 = (x) => (x == null ? '-' : x.toFixed(1));
const xi = res.xi.map((x) => {
  const p = x.player, s = p.stats;
  const bat = s.inns ? `${s.runs} runs @ ${f1(s.avg)}, SR ${f1(s.sr)}` : '';
  const bowl = s.wkts ? `${s.wkts} wkts @ ${f1(s.bowlAvg)}, econ ${s.econ?.toFixed(2)}` : '';
  return { id: p.id, name: p.name, slot: SLOT_TYPES[x.type].label, team: scope.teams[p.team] ?? '',
           line: [bat, bowl].filter(Boolean).join(' | '), utility: +x.u.toFixed(1),
           captain: p.id === res.captain, keeper: p.id === res.keeper };
});
process.stdout.write(JSON.stringify({
  title: `${opt.team ?? (scope.tier === 'league' ? scope.label + ' all-franchise' : 'World')} XI: ${scope.label}, ${from}-${to}`,
  subtitle: `${preset.label} lens; availability ${opt.availability ?? 'any'}`,
  xi, total: res.total,
  note: res.relaxed ? `Evidence bar lowered to ${Math.round(res.relaxed * 100)}% to fill every slot.` : '',
}));
