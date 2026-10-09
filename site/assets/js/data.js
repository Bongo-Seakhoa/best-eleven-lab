// Cached JSON loading for site/data. Every file is fetched once per session.

const cache = new Map();

export function load(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(`data/${path}`).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }).catch((e) => { cache.delete(path); throw e; }));
  }
  return cache.get(path);
}

export const meta = () => load('meta.json');
export const scope = (key) => load(`scopes/${key}.json`);
export const historic = (key) => load(`historic/${key}.json`);
export const player = (id) => load(`players/${id}.json`);
export const playerIndex = () => load('players/index.json');
export const captains = () => load('captains.json');
export const validation = () => load('validation.json');
export const runExpectancy = () => load('model/run_expectancy.json');
export const bowlerFamily = () => load('model/bowler_family.json');
export const reference = () => load('reference.json');

export const FULL_MEMBERS = ['Australia', 'England', 'India', 'South Africa', 'New Zealand', 'Pakistan',
  'Sri Lanka', 'West Indies', 'Bangladesh', 'Zimbabwe', 'Afghanistan', 'Ireland'];

// Team colours: recognisable, never relied on alone (names always shown).
export const TEAM_COLOURS = {
  'Australia': '#e2b007', 'England': '#1f3b8c', 'India': '#1e63c4', 'South Africa': '#0f7a43',
  'New Zealand': '#1a1a1a', 'Pakistan': '#0c6b37', 'Sri Lanka': '#1b3f8f', 'West Indies': '#7a1f2b',
  'Bangladesh': '#0b6e4f', 'Zimbabwe': '#c8102e', 'Afghanistan': '#2b59a8', 'Ireland': '#169b62',
};
export function teamColour(name) {
  if (TEAM_COLOURS[name]) return TEAM_COLOURS[name];
  let h = 0;
  for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 45% 42%)`;
}
