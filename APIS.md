# APIs

Every data source has to be **free**. This is what we use, what each free tier gives us and what it does not.

| API | Role | Key needed | Sign up |
|---|---|---|---|
| [football-data.org](https://www.football-data.org/) | **Main source**: matches, standings, scorers, teams | Yes (free) | https://www.football-data.org/client/register |
| [TheSportsDB](https://www.thesportsdb.com/) | **Trivia data**: crests, kits, stadiums, colors, players, career paths | No (public key `123`) | Not needed for the free key |
| [flagcdn](https://flagcdn.com/) | Country flags (secondary) | No | Not needed |
| [Wikidata](https://www.wikidata.org/) | **Backup** for player career paths | No | Not needed |

football-data.org is the only account we need.

API-Football was considered for player data and dropped: the free sign-up kept failing and its free plan reportedly does not include the current season. TheSportsDB covers the same player data for free.

---

## Crests and logos

Crests are the core of the trivia. Both sources serve them **publicly, without a key** (checked 2026-10-23):

| Source | URL | Format | Best for |
|---|---|---|---|
| football-data.org | `https://crests.football-data.org/<team_id>.png` / `.svg` | PNG and **SVG** | `crest`, `blur`, `zoom`: SVG stays sharp at any size before pixelating |
| football-data.org | `https://crests.football-data.org/<competition_code>.png` (e.g. `PL`) | PNG | `league` mode |
| TheSportsDB | `strBadge` field, add `/small` or `/medium` for smaller sizes | Transparent PNG | `silhouette`: clean alpha channel |
| TheSportsDB | `strLogo`, `strEquipment` | PNG | Alternate logos, `kit` mode |

The crest URL is stored in the trivia dataset; images are downloaded once and cached on disk.

---

## football-data.org

Docs: https://docs.football-data.org/general/v4/index.html

**Free tier:**
- 10 requests per minute.
- 12 competitions: Premier League, Championship, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Primeira Liga, Brasileirao Serie A, Champions League, World Cup, European Championship.
- Fixtures, results, standings, top scorers, teams with crest URL (confirm scorers and crests once the key works).
- Current season only.

**Not included:**
- Real-time scores: free scores are **delayed**, so `/live` and `/follow` alerts will lag a few minutes.
- Lineups, substitutions, cards, match stats, odds.

**Auth:** header `X-Auth-Token: <FOOTBALL_DATA_KEY>`.

---

## TheSportsDB

Docs: https://www.thesportsdb.com/documentation

**Free tier:**
- Public key `123`, 30 requests per minute.
- Team data: `strBadge` (crest), `strLogo`, `strEquipment` (kit), `strBanner`, `strFanart1-4`, `strColour1-3`, `intFormedYear`, `strStadium`, `idVenue`.
- Player data (`searchplayers.php`, `lookupplayer.php`): `strThumb` (photo), `strCutout` (transparent cutout), `strNationality`, `strPosition`, `dateBorn`, `strTeam`, plus external IDs such as `idWikidata`.
- Career path (`lookupformerteams.php?id=<player_id>`): every former club with `strJoined`, `strDeparted` and its `strBadge`.
- Images can be requested smaller by appending `/medium`, `/small` or `/tiny` to the URL.

**Limits found (tested 2026-10-23):**
- `searchteams.php?t=<name>` and `searchplayers.php?p=<name>` return **1 result**.
- `search_all_teams.php?l=<league>` returns **only 10 teams** (e.g. 10 of 20 Premier League clubs).
- `lookup_all_players.php?id=<team_id>` returns **only 10 players** per team.
- Livescores and the v2 API are premium only.

**How we use it:** team and squad lists come from football-data.org; then `scripts/build_dataset.py` looks up each team and player on TheSportsDB by name to get images, details and career path. Runs once a week, so the limits do not matter.

Examples:
- `https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t=Arsenal`
- `https://www.thesportsdb.com/api/v1/json/123/searchplayers.php?p=Luis%20Diaz`
- `https://www.thesportsdb.com/api/v1/json/123/lookupformerteams.php?id=34171827` (Barranquilla FC 2016-17, Atletico Junior 2017-19, Porto 2019-22, Liverpool 2022-25)

---

## flagcdn

Docs: https://flagcdn.com/

- No key, no limits worth worrying about.
- PNG by ISO 3166 code and width: `https://flagcdn.com/w320/co.png`
- SVG: `https://flagcdn.com/co.svg`
- Secondary: used for player nationalities, the `club-country` mode and the `flag` (national teams) mode.

Note: England, Scotland and Wales use subdivision codes (`gb-eng`, `gb-sct`, `gb-wls`).

---

## Wikidata (backup)

Docs: https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service

- Free, no key. Query with SPARQL at `https://query.wikidata.org/sparql`.
- Use it only when TheSportsDB is missing a player's career path: property `P54` (member of sports team) with start/end qualifiers.
- TheSportsDB gives the player's Wikidata ID (`idWikidata`), so no name matching is needed.
- Send a descriptive `User-Agent` header, as Wikimedia requires.

Not tested yet.

---

## What this means for the bot

| Feature | Source | Works on free? |
|---|---|---|
| `/matches`, `/standings`, `/scorers`, `/team` | football-data.org | Yes, for the 12 competitions |
| `/live`, `/follow` alerts | football-data.org | Yes, but **delayed** |
| Crest / silhouette / zoom / blur trivia | football-data.org crests + TheSportsDB | Yes |
| Stadium / kit trivia | TheSportsDB | Yes |
| Flag trivia | flagcdn | Yes |
| Player / career / who-am-i trivia, `/daily` | TheSportsDB (+ Wikidata backup) | Yes |
| `/player`, `/squad` | football-data.org squads + TheSportsDB details | Yes (confirm squads once the key works) |
| Liga BetPlay, Libertadores | No free source with current data | Out of scope for now |

---

## Keys

- Each key goes in `.env` (see `README.md`), never in the repo.
- One person creates the accounts and shares the keys privately; tracked in the "Create API accounts" issue.
- When an account is created, update this file with the **real limits** shown in its dashboard.
