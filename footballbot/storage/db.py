"""Conexión a la base de datos SQLite y migraciones.

Quién lo usa: bot.py crea `Database(settings.database_url)` y llama `connect()` al arrancar.
Las consultas están en repos.py.

Migraciones: cada archivo de storage/migrations/ es un cambio al esquema, numerado
(001_init.sql, 002_..., ...). SQLite guarda en `PRAGMA user_version` la última que se aplicó;
al arrancar se aplican solo las que faltan. Para cambiar una tabla, NUNCA edites una migración
que ya está en main: crea la siguiente (ej. 002_add_guilds.sql).
"""

import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def sqlite_path(url: str) -> str:
    """'sqlite:///data/footballbot.db' -> 'data/footballbot.db' (relativo a donde corre el bot)."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"only sqlite is supported for now, got {url!r}")
    return url.removeprefix(prefix)


class Database:
    def __init__(self, url: str) -> None:
        self._path = sqlite_path(url)
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() has not been called")
        return self._conn

    async def connect(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        # Las filas se pueden leer por nombre de columna: row["points"]
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self.migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def migrate(self) -> None:
        """Aplica, en orden, las migraciones con número mayor a `user_version`."""
        async with self.conn.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        current = row[0] if row else 0
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            number = int(path.name.split("_", 1)[0])
            if number <= current:
                continue
            log.info("Applying migration %s", path.name)
            await self.conn.executescript(path.read_text(encoding="utf-8"))
            # PRAGMA no acepta parámetros (?), por eso el número va en el texto
            await self.conn.execute(f"PRAGMA user_version = {number}")
            await self.conn.commit()
