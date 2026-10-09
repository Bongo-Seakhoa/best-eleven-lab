// Reads solver instances (JSON array) from argv[2]; prints one result per instance.
import { readFileSync } from 'node:fs';
import { solve } from '../assets/js/engine/solver.js';

const instances = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const results = instances.map((inst) => {
  const r = solve(inst.slots, inst.cands, {
    maxOverseas: inst.maxOverseas ?? null,
    maxPerTeam: inst.maxPerTeam ?? null,
    locks: new Set(inst.locks ?? []),
    excludes: new Set(inst.excludes ?? []),
  });
  return r.error ? { error: r.error } : { total: r.total, ids: r.picks.map((p) => p.id), optimal: r.optimal, nodes: r.nodes };
});
process.stdout.write(JSON.stringify(results));
