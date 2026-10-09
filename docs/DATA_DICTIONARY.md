# Data contracts

## Core relations

| Relation | Grain and purpose |
|---|---|
| `players` | Stable provider identity and most recently ingested display name. Analyses join on ID, not spelling. |
| `matches` | One provider match ID; dates, format, gender, team level, competition, venue, revision, schema, raw content hash and provenance. `is_synthetic` separates test demonstrations. |
| `match_sources` | Match-to-source mapping. Overlapping country and format archives can refer to one canonical match. |
| `appearances` | One official roster identity per match and team. A roster can contain replacement players. |
| `innings` | Match plus innings ordinal; teams, super-over/declaration/forfeit flags, target and pre/post penalty runs. |
| `deliveries` | Match, innings and integer delivery ordinal; striker, non-striker, bowler, component outcomes, legal/faced flags, derived phase and prior score. |
| `wickets` | One event per delivery plus wicket-event ordinal. Actual player out, event kind, out flag and bowler credit remain separate. |
| `batting` | Player-innings totals, actual dismissals and first-observed batting position. |
| `fielding` | Named fielding participants attached to wicket events. Not field locations or all fielding opportunities. |
| `metadata` | Player, format, level, effective date and source snapshot; role/hand/style, team, appointments, credits, availability and observation date. |
| `fetches` | Latest source acquisition receipt; HTTP validators where available, timestamp, raw archive hash/path and import status. |
| `ingestion_errors` | Quarantined match file, source, error and timestamp. |

Foreign keys and per-match transactions prevent orphan deliveries after revision replacement. Match hashes make exact repeats cheap. An archive is not a transaction: valid matches can enter while invalid matches are quarantined. Consumers must inspect the returned partial status.

## Metadata CSV

The exact header is in `config/metadata-template.csv`. Roles are `opener`, `bat`, `keeper`, `all_rounder`, `bowler`. Hands are `left` or `right`. Bowling style is a source-attributed text label; the simple pace/spin capability parser recognizes fast/medium/seam and spin/orthodox/break strings. Review unfamiliar labels rather than assuming classification.

`available=1` is a dated, source-attributed assertion, not an inferred fitness score. Under strict national selection, its team must match the selected candidate team. `captain_matches` and `vice_captain_matches` are non-negative counts for the stated format/level as known at `observed_at`. Both blank means unknown. Explicit zero means the source supports zero. Snapshot rows are not an additive appointment history.

## Exports and lineage

Ranking and selection JSON include the exact scope, preferences, raw statistics, score components, role evidence, peer fallback counts and limitations. Acquisition receipts contain archive hashes. Raw match content hashes remain in the database. Live downloads and browser imports retain content-addressed ZIPs locally under the selected database’s `raw` directory. Keep these with the database to reproduce the exact snapshot.

The database is an accumulated, revision-aware record store, not a mirror of the provider’s newest full snapshot. A match disappearing from a later archive is not automatically deleted, and a lower provider revision is not substituted. Explicit withdrawal/retraction reconciliation is an outstanding operational capability. Old raw archives need an owner-approved retention policy; this prototype does not silently erase them.

## Rejected / unsupported inputs

Unreviewed schemas, non-six-ball-over formats, unknown dismissal kinds, invalid identities, unsafe ZIP members, inconsistent component runs and unsupported team/gender values are rejected or quarantined. ODM/MDM and formats other than Test/ODI/T20 are outside this release; IT20 is normalized to T20. Format changes are not guessed.

Field coordinates, shot maps, ball tracking, full career totals outside available matches and verified live squads are not present merely because a match has player names. Their absence must remain visible.
