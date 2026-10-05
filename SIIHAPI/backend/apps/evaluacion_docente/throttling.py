"""SIIHAPI · apps/evaluacion_docente — throttles (modularización, 2026-10-05)."""
from rest_framework.throttling import UserRateThrottle


class VozTranscripcionThrottle(UserRateThrottle):
    """Tope del endpoint de transcripción (`voz_transcripcion` en settings).

    Transcribir audio con faster-whisper ocupa CPU en el mismo proceso que
    atiende las peticiones: sin tope, un solo usuario puede dejar el
    servicio sin respuesta. Por eso la tarifa es baja (20/hora por
    defecto).

    Igual que en apps.eventos: `UserRateThrottle` con `scope` fijo, no
    `ScopedRateThrottle` — `@api_view` no traslada `throttle_scope` a la
    vista y el tope quedaría sin efecto sin que nada lo avise.
    """

    scope = 'voz_transcripcion'
