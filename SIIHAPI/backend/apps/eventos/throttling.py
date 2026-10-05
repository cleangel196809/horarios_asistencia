"""SIIHAPI · apps/eventos — throttles (modularización, 2026-10-05)."""
from rest_framework.throttling import UserRateThrottle


class EscaneoQRThrottle(UserRateThrottle):
    """Tope para el escaneo de QR (`eventos_escaneo` en settings).

    Se usa `UserRateThrottle` con `scope` fijo y NO `ScopedRateThrottle`:
    éste último lee `view.throttle_scope`, y `@api_view` no traslada ese
    atributo a la clase de vista que genera, así que el tope nunca se
    aplicaría (silenciosamente). Con el scope en la clase, la tarifa sale
    de DEFAULT_THROTTLE_RATES igual, y se cuenta por usuario autenticado.

    La tarifa es alta a propósito: el escáner dispara muchas lecturas
    seguidas en una ceremonia de grado y además vacía la cola offline. Lo
    que se corta es la fuerza bruta de tokens, no el uso normal.
    """

    scope = 'eventos_escaneo'
