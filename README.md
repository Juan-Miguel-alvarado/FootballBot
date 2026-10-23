# FootballBot

A Discord bot about football: **live league information** (matches, standings, top scorers, teams, players) and **image-based trivia** in the style of country-flag quiz bots, but with club crests — guess the club from a pixelated crest, a silhouette, the stadium, the kit, guess the player from their career path, and more.

> Status: **planning**. There is no code yet; these documents define what we are building and how we organize the work.

---

## What it will do

### 1. Football information (via API)
- Today's, live and upcoming matches, by league or by team.
- League standings, top scorers and top assists.
- Team and player profiles with crest/photo.
- Follow a team and get goal and result alerts in a channel.
- Generated image cards (standings table, player comparison, recent form).

### 2. Image trivia
- **Pixelated / blurred crest** that gets revealed over time (the main mode).
- Crest **silhouette**, **zoom** into a piece of the crest, **league logo**.
- **Stadium**, **kit**, **player photo**.
- **Career path**: a row of crests with years → who is the player?
- **Higher or lower**, **3x3 grid**, **daily player** (Wordle style).
- Extra: country **flags** for national teams and a club's country.
- Points, streaks, per-server and global leaderboards.

### 3. Social
- Profile card with stats, achievements, match prediction pools and (later) a sticker/card album.

The full catalog with priorities is in [COMMANDS.md](COMMANDS.md).

---

## Stack

| Part | Technology |
|---|---|
| Main language | **Python 3.12+** |
| Discord | [`discord.py`](https://discordpy.readthedocs.io/) 2.x (slash commands, buttons, select menus, autocomplete) |
| HTTP | `httpx` (async) |
| Images | `Pillow` (+ `cairosvg` for SVG crests) |
| Database | SQLite with `aiosqlite` at first, PostgreSQL if it grows |
| Answer matching | `rapidfuzz` + `unidecode` |
| Config | `.env` + `pydantic-settings` |
| Quality | `ruff`, `pytest`, GitHub Actions |
| Extra (optional) | JS/TS for a web leaderboard dashboard later on |

Data sources, all free (see [APIS.md](APIS.md)): **football-data.org**, **TheSportsDB**, **flagcdn** for flags (secondary) and, optionally, **API-Football**.

---

## Documents

| File | Purpose |
|---|---|
| [README.md](README.md) | This overview |
| [ROADMAP.md](ROADMAP.md) | Phases, tasks and work areas to split between us |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the bot is built internally: folders, data, images |
| [APIS.md](APIS.md) | Free APIs we use, their limits and sign-up links |
| [COMMANDS.md](COMMANDS.md) | Catalog of every command and trivia mode |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Team rules: branches, commits, PRs, code style |

---

## Getting started (once there is code)

```bash
git clone https://github.com/Juan-Miguel-alvarado/FootballBot.git && cd FootballBot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in the keys
python -m footballbot
```

Planned environment variables:

```env
DISCORD_TOKEN=
DISCORD_DEV_GUILD_ID=        # test server: slash commands sync instantly there
FOOTBALL_DATA_KEY=
API_FOOTBALL_KEY=
THESPORTSDB_KEY=
DATABASE_URL=sqlite:///data/footballbot.db
```

> Never commit `.env` or the bot token. If a token leaks, regenerate it in the Discord Developer Portal immediately.

---

## Disclaimer

Crests, logos and player photos are trademarks/property of their owners. This is a **non-commercial** project among friends; images are only used for the trivia games and are cached from the APIs, not redistributed.
