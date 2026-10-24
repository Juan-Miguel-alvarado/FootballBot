"""Errores propios del bot que no dependen de ninguna API.

Los errores de las APIs (ProviderError, NotFoundError, RateLimitedError) están en
`providers/base.py`. Todos se convierten en un mensaje para el usuario en
`bot.py:on_app_command_error`.
"""


class UserFacingError(Exception):
    """An error whose message is safe and useful to show to the user as is.

    Úsalo cuando el usuario se equivocó (fecha mal escrita, liga que no existe...):
    `raise UserFacingError("Unknown league **xyz**.")` y el bot le responde ese texto,
    solo visible para él. No se reporta al canal de errores porque no es un bug.
    """
