# APIs

Every data source has to be **free**. This is what we use, what each free tier gives us and what it does not.

| API | Role | Key needed | Sign up |
|---|---|---|---|
| [football-data.org](https://www.football-data.org/) | **Main source**: matches, standings, scorers, teams | Yes (free) | https://www.football-data.org/client/register |
| [TheSportsDB](https://www.thesportsdb.com/) | **Images for trivia**: crests, kits, stadiums, banners, colors | No (public key `123`) | Not needed for the free key |
| [flagcdn](https://flagcdn.com/) | Country flags (secondary) | No | Not needed |
| [API-Football](https://www.api-football.com/) | **Optional**: players, career paths, leagues not covered above | Yes (free) | https://dashboard.api-football.com/register |

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
- Images can be requested smaller by appending `/medium`, `/small` or `/tiny` to the URL.

**Limits found (tested 2026-10-23):**
- `searchteams.php?t=<name>` returns **1 result**.
- `search_all_teams.php?l=<league>` returns **only 10 teams** (e.g. 10 of 20 Premier League clubs).
- Livescores and the v2 API are premium only.

**How we use it:** the team list comes from football-data.org; then `scripts/build_dataset.py` looks up each team on TheSportsDB by name to get its images. Runs once a week, so the limits do not matter.

Example: `https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t=Arsenal`

---

## flagcdn

Docs: https://flagcdn.com/

- No key, no limits worth worrying about.
- PNG by ISO 3166 code and width: `https://flagcdn.com/w320/co.png`
- SVG: `https://flagcdn.com/co.svg`
- Secondary: used for player nationalities, the `club-country` mode and the `flag` (national teams) mode.

Note: England, Scotland and Wales use subdivision codes (`gb-eng`, `gb-sct`, `gb-wls`).

---

## API-Football (optional)

Docs: https://www.api-football.com/documentation-v3

**Free tier:**
- 100 requests per **day** (resets at 00:00 UTC), 10 per minute.
- All endpoints and all leagues, including Colombian Liga BetPlay and Copa Libertadores.
- Player photos, transfers, career history.

**Catch (to verify when creating the account):** several reports say the free plan **does not include the current season**, only past ones. If confirmed, we only use it for:
- the trivia dataset (career paths, `who-am-i`, `player` mode), built offline;
- historical data.

It is not used for live or current-season commands.

**Auth:** header `x-apisports-key: <API_FOOTBALL_KEY>`.

---

## What this means for the bot

| Feature | Source | Works on free? |
|---|---|---|
| `/matches`, `/standings`, `/scorers`, `/team` | football-data.org | Yes, for the 12 competitions |
| `/live`, `/follow` alerts | football-data.org | Yes, but **delayed** |
| Crest / silhouette / zoom / blur trivia | football-data.org crests + TheSportsDB | Yes |
| Stadium / kit trivia | TheSportsDB | Yes |
| Flag trivia | flagcdn | Yes |
| Player / career / who-am-i trivia | API-Football (past seasons) | Yes, with older data |
| Liga BetPlay, Libertadores info | API-Football | Only past seasons — out of scope for now |

---

## Keys

- Each key goes in `.env` (see `README.md`), never in the repo.
- One person creates the accounts and shares the keys privately; tracked in the "Create API accounts" issue.
- When an account is created, update this file with the **real limits** shown in its dashboard.
