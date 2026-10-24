"""Limitador de peticiones: evita pasarnos del límite gratis de la API (10 por minuto).

Quién lo usa: `football_data.py` llama `await limiter.acquire()` antes de cada petición HTTP.
Si ya se hicieron 10 peticiones en los últimos 60 s, `acquire()` espera hasta que se libere
un cupo. Las peticiones esperan en orden de llegada (la primera que llegó, sale primero).
"""

import asyncio
import time
from collections import deque


class RateLimiter:
    """Sliding window limiter: at most `max_calls` per `period` seconds, served in FIFO order.

    "Ventana deslizante": se guarda la hora de cada petición de los últimos `period` segundos.
    Si hay menos de `max_calls`, se puede pasar; si no, se espera a que la más vieja salga.
    """

    def __init__(self, max_calls: int, period: float) -> None:
        self._max_calls = max_calls
        self._period = period
        self._calls: deque[float] = deque()  # horas (time.monotonic) de las últimas peticiones
        # El lock hace que solo una petición a la vez revise el cupo: así respetan el orden
        # de llegada y dos no toman el mismo cupo.
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                # Sacamos las peticiones que ya tienen más de `period` segundos.
                while self._calls and now - self._calls[0] >= self._period:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                # No hay cupo: dormimos justo hasta que la petición más vieja salga de la ventana.
                await asyncio.sleep(self._period - (now - self._calls[0]))
