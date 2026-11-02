"""Descarga imágenes (escudos, logos) y las guarda en disco para no bajarlas otra vez.

Quién lo usa: bot.py crea un ImageLoader (`bot.images`) y cogs/trivia.py le pide los escudos.

La caché vive en data/cache/img/ (está en .gitignore). Si la borras, se vuelve a llenar sola.
Las imágenes de crests.football-data.org no gastan cuota de la API.
"""

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# footballbot/imaging/loader.py -> raíz del proyecto -> data/cache/img
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "img"


class ImageDownloadError(Exception):
    """No se pudo bajar una imagen (404, sin internet, no era una imagen...)."""


class ImageLoader:
    def __init__(
        self, cache_dir: Path = CACHE_DIR, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._cache_dir = cache_dir
        # Los tests pasan un transport falso para no salir a internet
        self._client = httpx.AsyncClient(
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "FootballBot (Discord trivia bot)"},
            transport=transport,
        )
        # Descargas en curso: si dos partes del bot piden la misma imagen a la vez,
        # la segunda espera a la primera en vez de bajarla otra vez
        self._downloading: dict[str, asyncio.Future[bytes]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str) -> bytes:
        """Los bytes de la imagen: del disco si ya la tenemos, si no la descarga y la guarda."""
        # Nombre de archivo = hash de la URL (las URLs tienen "/" y ":" que no sirven como nombre)
        path = self._cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.img"
        if path.exists():
            return await asyncio.to_thread(path.read_bytes)

        pending = self._downloading.get(url)
        if pending is None:
            pending = asyncio.ensure_future(self._download(url, path))
            self._downloading[url] = pending
            pending.add_done_callback(lambda _: self._downloading.pop(url, None))
        return await pending

    async def _download(self, url: str, path: Path) -> bytes:
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as e:
            raise ImageDownloadError(f"could not download {url}: {e!r}") from e
        is_image = response.headers.get("content-type", "").startswith("image/")
        if response.status_code != 200 or not is_image:
            raise ImageDownloadError(f"{url} returned {response.status_code}")

        data = response.content
        await asyncio.to_thread(self._save, path, data)
        return data

    @staticmethod
    def _save(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Se escribe a un archivo temporal y luego se renombra: así nunca queda una imagen a medias
        # Nombre único: dos descargas a la vez nunca escriben el mismo archivo temporal
        tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
