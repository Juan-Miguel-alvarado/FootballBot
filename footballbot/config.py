"""Configuración del bot: lee las variables del archivo `.env` (o del entorno).

Quién lo usa: `__main__.py` crea `Settings()` y se lo pasa a `FootballBot` (bot.py).

Para añadir una variable nueva:
1. Añade un campo aquí abajo (el nombre en minúsculas = la variable en mayúsculas del `.env`).
2. Añádela también a `.env.example` con un comentario de para qué sirve.
"""

from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads the bot configuration from the environment and `.env`."""

    # env_ignore_empty: una variable vacía (`DISCORD_DEV_GUILD_ID=`) cuenta como "no puesta"
    # y usa el valor por defecto, en vez de fallar al intentar convertir "" a número.
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # SecretStr evita que el token salga en logs o en errores: hay que pedir el valor
    # explícitamente con `.get_secret_value()`.
    discord_token: SecretStr
    # Servidor de pruebas. Si está puesto, los comandos se sincronizan solo ahí (al instante).
    discord_dev_guild_id: int | None = None
    # Canal donde el bot publica los errores inesperados con su traceback (opcional).
    discord_errors_channel_id: int | None = None
    football_data_key: SecretStr
    thesportsdb_key: str = "123"  # todavía no se usa: llega en la Fase 2 (dataset de trivia)
    database_url: str = "sqlite:///data/footballbot.db"  # todavía no se usa: Fase 2
    # Zona horaria para "hoy" en /matches y para mostrar las horas de los partidos.
    timezone: str = "America/Bogota"
    log_level: str = "INFO"

    @property
    def tz(self) -> ZoneInfo:
        """La zona horaria como objeto, lista para usar con datetime."""
        return ZoneInfo(self.timezone)
