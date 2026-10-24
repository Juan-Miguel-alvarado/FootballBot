# Guía del código

Para entender dónde está cada cosa y cómo viaja un comando por el bot. Léela antes de tocar el código.
Cada archivo también explica en su cabecera qué hace, quién lo usa y cómo añadirle cosas.

---

## La idea en una frase

Discord → **cogs** (los comandos) → **services** (la lógica) → **providers** (las APIs) → y de vuelta,
siempre con los **models** (equipos, partidos, tablas) como "idioma común".

```
 Usuario escribe /standings PL
            │
            ▼
   cogs/        → lee la opción, responde con un embed            (sabe de Discord)
            │
            ▼
   services/    → decide qué pedir, filtra y ordena                (no sabe de Discord)
            │
            ▼
   providers/   → caché, límite de peticiones, HTTP, JSON → models (solo sabe de la API)
            │
            ▼
   football-data.org
```

Regla de oro: **un comando nunca llama a la API directamente**. Siempre pasa por `services/`.

---

## Mapa de archivos

```
footballbot/
├── __main__.py              Arranque: `python -m footballbot` empieza aquí
├── bot.py                   El bot: carga los comandos, los sincroniza y maneja TODOS los errores
├── config.py                Lee el .env (token, keys, zona horaria...)
├── errors.py                UserFacingError: errores cuyo mensaje se le muestra al usuario
│
├── cogs/                    ── COMANDOS DE DISCORD ──
│   ├── info.py              /matches /live /standings /team /leagues + cómo se ven (formato)
│   ├── admin.py             /ping /help
│   └── common.py            Autocompletado, leer fechas y ligas, repartir embeds largos
│
├── services/                ── LÓGICA (sin Discord) ──
│   ├── football.py          FootballService: partidos del día, en vivo, tablas, perfil de equipo,
│   │                        y el índice de equipos para el autocompletado
│   ├── leagues.py           Las 13 ligas: código, nombre, bandera, apodos
│   └── text.py              normalize(): "Atlético!" → "atletico" (para buscar)
│
├── providers/               ── APIs EXTERNAS ──
│   ├── football_data.py     Cliente de football-data.org: caché + HTTP + JSON → models
│   ├── ratelimit.py         Máximo 10 peticiones por minuto
│   └── base.py              Qué métodos debe tener un provider + errores de API
│
└── models/
    └── football.py          Team, Match, Standing, StandingRow, Player, Competition

tests/
├── test_football_data.py    El provider, con respuestas reales guardadas (sin internet)
├── test_football_service.py La lógica, con un provider falso
├── test_leagues_and_parsing.py  Ligas, fechas, helpers de embeds
├── conftest.py              load_fixture()
└── fixtures/football_data/  Respuestas reales de la API en JSON
```

Los `__init__.py` solo le dicen a Python que la carpeta es un paquete; no tienen código.

---

## Recorrido completo: `/standings PL`

| Paso | Dónde | Qué pasa |
|---|---|---|
| 1 | Discord | El usuario escribe `/standings`. Mientras escribe la liga, Discord llama a `league_autocomplete` ([cogs/common.py](footballbot/cogs/common.py)) para mostrar sugerencias |
| 2 | [cogs/info.py](footballbot/cogs/info.py) `standings()` | Recibe `league="PL"`. `parse_league` ([cogs/common.py](footballbot/cogs/common.py)) lo busca en [services/leagues.py](footballbot/services/leagues.py) |
| 3 | mismo | `interaction.response.defer()`: Discord muestra *"thinking..."* (sin esto, hay solo 3 s para responder) |
| 4 | [services/football.py](footballbot/services/football.py) `standings()` | Le pasa el pedido al provider |
| 5 | [providers/football_data.py](footballbot/providers/football_data.py) `standings()` → `_get()` | ¿Está en caché (10 min)? Si sí, la devuelve. Si no: espera turno en el [rate limiter](footballbot/providers/ratelimit.py), hace `GET /competitions/PL/standings` |
| 6 | mismo, `_standing_row()` | Convierte el JSON en `Standing` y `StandingRow` ([models/football.py](footballbot/models/football.py)) |
| 7 | [cogs/info.py](footballbot/cogs/info.py) `_table_block()` | Arma la tabla alineada en un bloque de código |
| 8 | mismo | `interaction.followup.send(embeds=...)`: el usuario ve la tabla |

**¿Y si falla?** Cualquier excepción salta a `on_app_command_error` en [bot.py](footballbot/bot.py):

| Error | Ejemplo | El usuario ve | ¿Va al canal de errores? |
|---|---|---|---|
| `UserFacingError` | escribió `/matches date:mañana` | el mensaje exacto ("is not a date...") | No |
| `NotFoundError` | equipo que no existe | "I couldn't find that..." | No |
| `RateLimitedError` | se gastaron las 10 peticiones del minuto | "The football API is busy..." | No |
| `ProviderError` | la API está caída | "The football data service is not responding..." | No (queda en el log) |
| cualquier otro | un bug nuestro | "Something went wrong..." | **Sí**, con traceback |

---

## Qué pasa al arrancar

1. `python -m footballbot` → [`__main__.py`](footballbot/__main__.py) lee el `.env` con `Settings` ([config.py](footballbot/config.py)). Si falta algo, dice qué variable.
2. Crea `FootballBot` ([bot.py](footballbot/bot.py)), que crea el provider y el `FootballService` (uno solo para todo el bot).
3. `setup_hook` carga los cogs de `EXTENSIONS` y sincroniza los comandos con el servidor de pruebas (`DISCORD_DEV_GUILD_ID`): así aparecen al escribir `/`.
4. Al cargar [cogs/info.py](footballbot/cogs/info.py) arranca la tarea `refresh_teams`: va llenando el índice de equipos para el autocompletado de `/team`, una liga cada 12 s (~3 min en total) para no gastar toda la cuota. Se repite cada 24 h.
5. `on_ready`: el log dice `Logged in as FootballTrivia#...`.

---

## "Quiero hacer X, ¿qué toco?"

| Quiero... | Archivo(s) |
|---|---|
| **Un comando nuevo** | Copia `leagues` (simple) o `standings` (con API) en [cogs/info.py](footballbot/cogs/info.py). Si necesita datos, añade un método en [services/football.py](footballbot/services/football.py). Anótalo en [COMMANDS.md](COMMANDS.md) |
| **Un archivo de comandos nuevo** (ej. `trivia.py`) | Créalo en `cogs/` con una función `setup(bot)` al final (copia la de [admin.py](footballbot/cogs/admin.py)) y añádelo a `EXTENSIONS` en [bot.py](footballbot/bot.py) |
| **Cambiar cómo se ve un comando** | Las funciones `_match_line`, `_table_block`, `_team_embed` al final de [cogs/info.py](footballbot/cogs/info.py) |
| **Añadir una liga o un apodo** | `LEAGUES` en [services/leagues.py](footballbot/services/leagues.py) |
| **Un endpoint nuevo de football-data** | Un método en [providers/football_data.py](footballbot/providers/football_data.py) (copia `team()`), y si es nuevo en el Protocol, en [providers/base.py](footballbot/providers/base.py) |
| **Otra API** (TheSportsDB...) | Un archivo nuevo en `providers/` que devuelva los modelos de [models/football.py](footballbot/models/football.py) |
| **Un campo nuevo en un modelo** | [models/football.py](footballbot/models/football.py) y la función `_team`/`_match`/... que lo llena en [football_data.py](footballbot/providers/football_data.py) |
| **Una variable de configuración** | [config.py](footballbot/config.py) y [.env.example](.env.example) |
| **Un mensaje de error** | `on_app_command_error` en [bot.py](footballbot/bot.py) |
| **Un test** | `tests/`: copia uno parecido. Correr con `pytest` |

---

## Glosario

| Palabra | Qué es |
|---|---|
| **Slash command** | Un comando que empieza por `/` en Discord, con opciones y sugerencias |
| **Cog** | Una clase que agrupa slash commands (un archivo en `cogs/`) |
| **Embed** | El recuadro con título, campos, color e imagen que manda el bot |
| **Autocomplete** | Las sugerencias que salen mientras escribes una opción. Hay que responder en < 3 s |
| **defer** | "Estoy en ello": muestra *thinking...* y da 15 min para responder en vez de 3 s |
| **ephemeral** | Mensaje que solo ve quien usó el comando |
| **followup** | La respuesta que se manda después de un `defer` |
| **Sync** | Enviarle a Discord la lista de comandos para que aparezcan en el menú `/` |
| **Provider** | Cliente de una API externa (`providers/`) |
| **Service** | Lógica del bot, sin Discord (`services/`) |
| **Model** | Una clase de datos: `Team`, `Match`... (`models/`) |
| **Caché (TTL)** | Guardar una respuesta un tiempo (Time To Live) para no volver a pedirla a la API |
| **Rate limit** | Límite de peticiones: 10 por minuto en el plan gratis de football-data.org |
| **429** | Código HTTP de "demasiadas peticiones, espera" |
| **async / await** | El bot atiende a muchos a la vez: `await` = "espera esto sin bloquear a los demás" |
| **Fixture (tests)** | Datos guardados que usan los tests; o un objeto que pytest le pasa a cada test |

---

## Comandos útiles

```bash
source .venv/bin/activate      # entrar al entorno (una vez por terminal)
python -m footballbot          # correr el bot (Ctrl+C para pararlo)
pytest                         # correr los tests
ruff check . && ruff format .  # revisar y formatear el código
```
