# Roadmap

Mark tasks with `[x]` when done and put the owner's name next to them: `- [ ] Task — @name`.

**Current status:** Phase 0 and Phase 1 done. Next up: **Phase 2 — first trivia**.

---

## Work areas

To split the work without stepping on each other. Each area touches different folders (see [ARCHITECTURE.md](ARCHITECTURE.md)).

| Area | Base branch | Folders | Includes |
|---|---|---|---|
| **Bot and commands** | `feat/bot` | `cogs/`, `bot.py` | Slash commands, embeds, buttons, autocomplete, permissions |
| **Data and APIs** | `feat/data` | `providers/`, `services/football.py`, `scripts/` | API clients, cache, trivia dataset, aliases |
| **Images** | `feat/images` | `imaging/` | Effects, generated cards, fonts, visual design |
| **Games and scoring** | `feat/games` | `services/trivia/`, `services/scoring.py`, `storage/` | Trivia sessions, modes, matching, DB, leaderboard |

Each area works on its own branch and keeps it up to date with `main` (`git pull origin main`). For larger tasks, branch off the area branch (`feat/games-silhouette`) and open the PR back into it; once something in the area is stable, open a PR from the area branch into `main`.

---

## Phase 0 — Setup ✅

- [x] Create the GitHub repo and invite everyone — @Juan-Miguel-alvarado
- [x] Create the bot application in the [Discord Developer Portal](https://discord.com/developers/applications) (**FootballTrivia**) and share the token through a private channel (never through the repo) — @Juan-Miguel-alvarado
- [x] Create a Discord test server (uses `🧪-testing` and `🤖-bot-commands` for the bot)
- [ ] Create an `#errors` channel and put its ID in `DISCORD_ERRORS_CHANNEL_ID` so tracebacks get posted there
- [x] Create accounts and get keys for the APIs in [APIS.md](APIS.md); record the real limits there — @Juan-Miguel-alvarado
- [x] Project skeleton: `pyproject.toml`, `.env.example`, `.gitignore`, folder structure — @Juan-Miguel-alvarado
- [x] `ruff` + `pytest` + a GitHub Action that runs both on every PR — @Juan-Miguel-alvarado
- [ ] Decide the bot's name/avatar (the application is called *FootballTrivia* for now)

**Done when:** anyone can clone, fill in `.env`, and the bot shows up online on the test server. ✅

---

## Phase 1 — Basic bot + info (MVP) ✅

- [x] `bot.py`: load cogs and sync commands to the test server — @Juan-Miguel-alvarado
- [x] `/ping`, `/help`, `/leagues` — @Juan-Miguel-alvarado
- [x] Shared models (`Team`, `Match`, `Standing`, `Player`) + base `FootballProvider` — @Juan-Miguel-alvarado
- [x] football-data.org provider with TTL cache and a 10 requests/minute rate limiter — @Juan-Miguel-alvarado
- [x] `/matches`, `/live` — @Juan-Miguel-alvarado
- [x] `/standings` (text embed first) — @Juan-Miguel-alvarado
- [x] `/team` with crest, recent form and next match — @Juan-Miguel-alvarado
- [x] Autocomplete for leagues, teams and dates — @Juan-Miguel-alvarado
- [x] Error handling: friendly message to the user + traceback to the `#errors` channel — @Juan-Miguel-alvarado
- [ ] Everyone tries every command on the test server and reports anything odd in `🐛-bug-reports`

**Done when:** you can check matches and standings for the top 5 leagues without the bot crashing.

Notes from building it:
- The free plan covers **13** competitions, Copa Libertadores included (see [APIS.md](APIS.md)).
- `/live` shows the score but not the minute: the free plan does not send it.
- Team autocomplete reads an in-memory index that loads all 13 competitions in the background at startup (about 3 minutes, spaced out to leave quota for commands) and refreshes daily.

---

## Phase 2 — First trivia (MVP)

- [ ] `scripts/build_dataset.py`: teams from the main leagues with crest, country, league, founded, stadium
- [ ] Initial `aliases.json` (nicknames for the ~100 best-known clubs)
- [ ] `imaging/loader.py`: download, disk cache, SVG to PNG
- [ ] `imaging/effects.py`: `pixelate`, `blur`
- [ ] `GameSession` + round loop with reveal stages
- [ ] **Button** answers (4 options)
- [ ] **Typed** answers with `matching.py` (fuzzy + aliases)
- [ ] Modes `crest`, `blur`, `league`
- [ ] SQLite DB: `games`, `answers`, `scores`
- [ ] Server `/leaderboard`
- [ ] `/trivia stop`, one game per channel

**Done when:** several people can play a 10-round crest game and the leaderboard is saved.

> **End of MVP.** Test it with friends on a real server before moving on.

---

## Phase 3 — More image trivia

- [ ] Effects `silhouette`, `zoom_crop`, `grayscale`
- [ ] Modes `silhouette`, `zoom`, `club-country`, `flag`, `stadium`
- [ ] Player dataset (football-data squads + TheSportsDB): photo, nationality, position, clubs with years
- [ ] `player` mode (blurred black and white photo)
- [ ] `career` mode with a composite crest image
- [ ] `who-am-i` mode with progressive clues
- [ ] `higher-lower` mode with a double card
- [ ] Easy / medium / hard difficulties
- [ ] `/hint` and `mix` mode

---

## Phase 4 — Advanced info and cards

- [ ] `imaging/cards.py`: **standings** card with crests and zone colors
- [ ] **Versus** card for `/next` and `/last`
- [ ] `/scorers`, `/assists`, `/player`, `/squad`
- [ ] `/follow` + `poll_live` task with goal alerts
- [ ] Wikidata provider as backup for missing career paths
- [ ] `/config` (trivia channel, default leagues, answer mode)

---

## Phase 5 — Social

- [ ] `/profile` with a generated card (Discord avatar + stats)
- [ ] Streaks and `/achievements`
- [ ] Wordle-style `/daily` with a shareable result
- [ ] Global leaderboard across servers
- [ ] `/pool` match predictions per matchday

---

## Phase 6 — Extras and production

- [ ] 24/7 deployment (Docker on a VPS / Railway / Raspberry Pi)
- [ ] `grid` 3x3 mode
- [ ] `kit` and `scoreline` modes
- [ ] Cards: `/pack`, `/album`, `/trade`
- [ ] Web dashboard (JS/TS) with leaderboards and album
- [ ] Spanish support via `/config language`
- [ ] Move to Postgres if needed

---

## Loose ideas (no phase yet)

Add any idea here before discussing it:

- Tournament mode between servers
- Voice trivia (the bot reads the question in a voice channel)
- Historic / retro crests on hard difficulty
- Guess the club from its anthem or nickname
