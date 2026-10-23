// Exact Best XI assignment as a min-cost flow.
//
//   source -> group (cap) -> player (1) -> slot type (count) -> sink
//
// Each player belongs to exactly one group: their team when a per-team cap is
// set, overseas/local when an overseas cap is set, otherwise a single group.
// Because that structure is a network, the linear relaxation is integral and
// successive shortest paths give the exact optimum. Locked players get a bonus
// larger than any possible utility gap, so they are always used when feasible.
// Combining an overseas cap with a per-team cap breaks the network structure
// and is rejected rather than approximated.

const COST_EPSILON = 1e-9;

class Graph {
  constructor(n) { this.n = n; this.adj = Array.from({ length: n }, () => []); this.e = []; }
  add(u, v, cap, cost) {
    this.adj[u].push(this.e.length); this.e.push({ to: v, cap, cost, flow: 0 });
    this.adj[v].push(this.e.length); this.e.push({ to: u, cap: 0, cost: -cost, flow: 0 });
  }
  // Successive shortest augmenting paths (SPFA handles the negative costs).
  minCostFlow(s, t, want) {
    let flow = 0, cost = 0;
    const n = this.n;
    while (flow < want) {
      const dist = new Float64Array(n).fill(Infinity);
      const inQ = new Uint8Array(n);
      const prevE = new Int32Array(n).fill(-1);
      const depth = new Int32Array(n);
      dist[s] = 0;
      const q = [s]; inQ[s] = 1;
      let head = 0;
      while (head < q.length) {
        const u = q[head++]; inQ[u] = 0;
        for (const id of this.adj[u]) {
          const ed = this.e[id];
          if (ed.cap - ed.flow > 0 && dist[u] + ed.cost < dist[ed.to] - COST_EPSILON) {
            dist[ed.to] = dist[u] + ed.cost; prevE[ed.to] = id;
            depth[ed.to] = depth[u] + 1;
            if (depth[ed.to] >= n) return { error: 'Selection encountered an unstable cost cycle. Change the picks and try again.' };
            if (!inQ[ed.to]) { inQ[ed.to] = 1; q.push(ed.to); }
          }
        }
      }
      if (dist[t] === Infinity) break;
      let push = want - flow;
      const seen = new Set();
      for (let v = t; v !== s; v = this.e[prevE[v] ^ 1].to) {
        if (prevE[v] < 0 || seen.has(v)) return { error: 'Selection could not construct a stable assignment.' };
        seen.add(v);
        const ed = this.e[prevE[v]]; push = Math.min(push, ed.cap - ed.flow);
      }
      for (let v = t; v !== s; v = this.e[prevE[v] ^ 1].to) {
        this.e[prevE[v]].flow += push; this.e[prevE[v] ^ 1].flow -= push;
      }
      flow += push; cost += push * dist[t];
    }
    return { flow, cost };
  }
}

/**
 * @param {Array<{type:string,count:number}>} slots
 * @param {Array<{id:any, util:Object<string,number>, overseas?:boolean, team?:any}>} cands
 * @param {{maxOverseas?:number|null, maxPerTeam?:number|null, locks?:Set, excludes?:Set}} opts
 * @returns {{total:number, picks:Array<{type:string,id:any,u:number}>, optimal:true}|{error:string}}
 */
export function solve(slots, cands, opts = {}) {
  const { maxOverseas = null, maxPerTeam = null, locks = new Set(), excludes = new Set() } = opts;
  if (maxOverseas != null && maxPerTeam != null) {
    return { error: 'Use either an overseas cap or a per-team cap, not both' };
  }
  const types = slots.filter((s) => s.count > 0);
  const need = types.reduce((a, s) => a + s.count, 0);
  const pool = cands.filter((c) => !excludes.has(c.id) && types.some((s) => c.util[s.type] != null));
  for (const s of types) {
    const n = pool.filter((c) => c.util[s.type] != null).length;
    if (n < s.count) return { error: `Only ${n} eligible for ${s.count} ${s.type} slot(s)` };
  }
  for (const id of locks) {
    if (!pool.some((c) => c.id === id)) return { error: 'A locked player is not eligible for any slot in this composition' };
  }
  // Keep the lock incentive above every possible utility gain without million-point cancellation.
  let minUtility = Infinity, maxUtility = -Infinity;
  for (const c of pool) for (const s of types) {
    const u = c.util[s.type];
    if (u == null) continue;
    if (!Number.isFinite(u)) return { error: 'A player has an invalid utility score.' };
    minUtility = Math.min(minUtility, u); maxUtility = Math.max(maxUtility, u);
  }
  const lockBonus = (need + 1) * (maxUtility - minUtility + 1);
  const groupOf = (c) => (maxPerTeam != null ? `t:${c.team}` : maxOverseas != null ? (c.overseas ? 'os' : 'local') : 'all');
  const capOf = (g) => (maxPerTeam != null ? maxPerTeam : g === 'os' ? maxOverseas : need);
  const groups = [...new Set(pool.map(groupOf))];
  const S = 0, T = 1, G0 = 2, P0 = G0 + groups.length, T0 = P0 + pool.length;
  const g = new Graph(T0 + types.length);
  const gIndex = new Map(groups.map((x, i) => [x, i]));
  groups.forEach((x, i) => g.add(S, G0 + i, capOf(x), 0));
  pool.forEach((c, i) => {
    g.add(G0 + gIndex.get(groupOf(c)), P0 + i, 1, 0);
    const bonus = locks.has(c.id) ? lockBonus : 0;
    types.forEach((s, k) => {
      const u = c.util[s.type];
      if (u != null) g.add(P0 + i, T0 + k, 1, -(u + bonus));
    });
  });
  types.forEach((s, k) => g.add(T0 + k, T, s.count, 0));
  const result = g.minCostFlow(S, T, need);
  if (result.error) return { error: result.error };
  const { flow } = result;
  if (flow < need) return { error: 'No eleven satisfies these constraints' };
  const picks = [];
  pool.forEach((c, i) => {
    for (const id of g.adj[P0 + i]) {
      const ed = g.e[id];
      if (ed.flow > 0 && ed.to >= T0) {
        const type = types[ed.to - T0].type;
        picks.push({ type, id: c.id, u: c.util[type] });
      }
    }
  });
  for (const id of locks) {
    if (!picks.some((p) => p.id === id)) return { error: 'Locked players cannot all fit these constraints' };
  }
  const total = picks.reduce((a, p) => a + p.u, 0);
  return { total, picks, optimal: true, nodes: g.n };
}
