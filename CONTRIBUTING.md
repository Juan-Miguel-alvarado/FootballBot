# Contributing

## Workflow

1. Pick a task from [ROADMAP.md](ROADMAP.md) (or an issue) and put your name on it.
2. Branch off your area branch (`feat/bot`, `feat/data`, `feat/images`, `feat/games` — see [ROADMAP.md](ROADMAP.md#work-areas)), or off `main` for general changes:
   - `feat/trivia-silhouette`
   - `fix/standings-broken-crests`
   - `docs/architecture-cache`
3. Small commits using [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat(trivia): silhouette mode
   fix(providers): retry when football-data returns 429
   docs: real football-data.org limits
   ```
4. Open a **Pull Request** into the branch you started from. At least **one person** reviews it before merging.
5. Nobody pushes directly to `main`.

## Before opening a PR

- [ ] `ruff check . && ruff format .`
- [ ] `pytest`
- [ ] Tested on the Discord test server
- [ ] If the command renders an image: **screenshot in the PR**
- [ ] If it changes architecture, commands or phases: update the matching `.md`

## Code style

- Python 3.12+, **type hints** everywhere.
- Code and user-facing text in **English** (Spanish later through a translations file).
- Functions in `imaging/` are pure: image in, image out.
- No HTTP calls from `cogs/`: always go through `services/`.
- Anything blocking (Pillow, disk) goes through `asyncio.to_thread`.
- No `print`: use `logging`.

## Adding a new command

1. Add it to [COMMANDS.md](COMMANDS.md) with its priority.
2. Logic in `services/`, with a test.
3. Slash command in the matching cog (`cogs/info.py`, `cogs/trivia.py`, ...).
4. For a trivia mode: add a generator in `services/trivia/modes.py` that returns `Question(image, answer, options, hints)`.

## Secrets

- `.env` **never** goes in the repo; it is in `.gitignore`. Keys are shared by private message.
- If a token is committed by mistake: regenerate it right away in the Developer Portal / API dashboard and tell the group. Deleting the commit is not enough.

## Issues

Suggested labels: `bot`, `data`, `images`, `games`, `bug`, `idea`, `good-first-issue`.
