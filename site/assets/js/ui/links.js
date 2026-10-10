// Link targets shared across views.

/**
 * A player's page: the Cricsheet id when there is one, otherwise the Wikipedia
 * title (career-only players from the all-eras lists and captaincy records).
 * Null when neither is known, so the name is shown without a link.
 */
export function playerHref(id, title) {
  if (id) return `#/player/${encodeURIComponent(id)}`;
  if (title) return `#/player/w:${encodeURIComponent(title)}`;
  return null;
}
