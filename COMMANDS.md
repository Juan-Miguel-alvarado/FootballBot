# Command catalog

All commands are **slash commands** (`/command`). Priority:

- **MVP** — ships first
- **v2** — after the MVP
- **Idea** — if there is time / if someone wants to take it

The **Image** column describes the image the command produces or uses.

---

## 1. Information

| Command | What it does | Image | Priority |
|---|---|---|---|
| `/matches [league] [date]` | Today's matches (or a given date) grouped by league | Crests in the embed | MVP |
| `/live [league]` | Matches in progress with score (the free plan does not give the minute) | Crests | MVP |
| `/standings <league>` | League table | Text table now; **generated card** with crests, P, GD, Pts and colors per zone in Phase 4 | MVP |
| `/team <name>` | Profile: crest, country, stadium, coach, founded, colors, recent form, last and next match | Crest + form as 🟩🟨🟥 (generated strip later) | MVP |
| `/scorers <league>` | Top 10 scorers | Card with player photos | v2 |
| `/assists <league>` | Top 10 assists | Same as scorers | v2 |
| `/player <name>` | Profile: photo, club, position, age, season stats | Photo + nationality flag | v2 |
| `/next <team>` | Team's next match | "Versus" card with both crests | v2 |
| `/last <team>` | Team's last result | "Versus" card with the score | v2 |
| `/squad <team>` | Squad by position | Paginated list with buttons | v2 |
| `/h2h <team1> <team2>` | Head-to-head history | Versus card + win bars | Idea |
| `/compare <player1> <player2>` | Compare two players | Generated **radar chart** | Idea |
| `/follow <team>` / `/unfollow <team>` | Goal, kick-off and full-time alerts in the channel | Goal card | v2 |
| `/leagues` | Available leagues and their codes | — | MVP |

Every team/player/league argument uses **autocomplete** (Discord suggests while typing).

---

## 2. Trivia

### How it plays

- `/trivia start <mode> [difficulty] [rounds] [answers]` starts a game in the channel (1-20 rounds, 10 by default).
- **One game per channel** at a time.
- Two ways to answer (configurable per mode):
  - **Buttons** — 4 options, each player answers once. Fast and does not need to read chat.
  - **Typed** — answer in chat. Tolerates typos and nicknames (`barca`, `atleti`, `juve`, `spurs`). Requires the *Message Content* intent and `TRIVIA_TYPED_ANSWERS=true`.
- Images are **revealed in stages**: 4 stages of 5 s. Points by stage: 100 / 75 / 50 / 25, plus +10 per round won in a row (up to +50). The first correct answer wins the round; with buttons, a wrong answer locks you out of that round.
- `/trivia stop` ends the game (whoever started it, or someone with *Manage Messages*). `/hint` (v2) will spend points on a text hint.
- Difficulty: **easy** (Europe's top 5 leagues), **medium** (+ Eredivisie, Primeira Liga, Brasileirão, Champions League clubs), **hard** (+ Championship and Copa Libertadores).

### Modes

The core of the trivia is **club crests and league logos** (`crest`, `blur`, `silhouette`, `zoom`, `league`). Country flags are secondary: national team trivia, the `club-country` mode and player nationalities.

| Mode | What you see | What you guess | Image trick | Priority |
|---|---|---|---|---|
| `crest` | Pixelated crest that gets clearer | The club | Progressive pixelation (downscale and upscale) | MVP |
| `blur` | Blurred crest | The club | Decreasing Gaussian blur | MVP |
| `silhouette` | Crest filled solid black | The club | Alpha channel to solid black | v2 |
| `zoom` | A small crop of the crest that zooms out | The club | Random crop that grows each stage | v2 |
| `flag` | A country's flag | The national team | flagcdn flag, can be pixelated | v2 |
| `club-country` | A club crest | The club's country (options shown as flags) | Buttons with flag emoji | v2 |
| `club-clues` | Country flag + club colors + year founded + stadium | The club | Generated clue card | v2 |
| `stadium` | Stadium photo | The stadium or the club | TheSportsDB photo, cropped | v2 |
| `kit` | Club kit | The club | Kit image, logos removed if possible | Idea |
| `player` | Player photo in black and white / blurred | The player | Grayscale + blur | v2 |
| `career` | Row of crests with years: `2012 > 2015 > 2019 > ...` | The player | **Composite image** of crests with arrows | v2 |
| `who-am-i` | Clues that unlock: nationality, position, league, age, shirt number | The player | Clue card | v2 |
| `higher-lower` | Two cards side by side | Which one is higher? (stadium capacity, goals, titles, year founded) | Generated double card | v2 |
| `grid` | 3x3 grid with crests/flags on rows and columns | A player matching both | Generated grid | Idea |
| `scoreline` | Two crests + date of a historic match | The final score | Versus card | Idea |
| `league` | Pixelated league logo | The league | Same as `crest` | MVP |
| `mix` | Random mode from the ones above | — | — | v2 |

### Daily

| Command | What it does | Priority |
|---|---|---|
| `/daily` | **Player of the day**, Wordle style: each guess shows whether league, club, nationality, position and age match (higher/lower). Same player for everyone, 8 guesses, shareable result | v2 |
| `/daily-crest` | Crest of the day, one guess per reveal stage | Idea |

---

## 3. Social and points

| Command | What it does | Image | Priority |
|---|---|---|---|
| `/leaderboard [mode]` | Server points table (global ranking in Phase 5) | Text now, generated card later | MVP |
| `/profile [user]` | Points, accuracy, streak, favorite mode | **Profile card** with Discord avatar | v2 |
| `/achievements` | Unlocked badges (100 crests, 10-answer streak, etc.) | Badge grid | Idea |
| `/pool create <league> <matchday>` | Prediction pool for a matchday; everyone submits their score | — | Idea |
| `/pool predict` / `/pool table` | Submit a prediction / view the pool table | Card | Idea |
| `/pack` | Open a daily pack of player **cards** | Generated cards with photo, rarity and stats | Idea |
| `/album` / `/trade` | View your collection / trade cards with another user | Album grid | Idea |

---

## 4. Admin and utilities

| Command | What it does | Priority |
|---|---|---|
| `/help [command]` | Command list with examples | MVP |
| `/ping` | Bot latency and API status | MVP |
| `/config trivia-channel <channel>` | Restrict trivia to one channel | v2 |
| `/config leagues <leagues>` | Server's default leagues | v2 |
| `/config answers <buttons\|typed>` | Default answer mode | v2 |
| `/config language <en\|es>` | Bot language | Idea |

`/config` commands are only visible to users with the **Manage Server** permission.
