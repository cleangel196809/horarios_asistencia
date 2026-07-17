"""
SIIHAPI - Circuit Breaker para la integracion con SISCA.

Patron: si SISCA falla N veces consecutivas, el circuito se "abre"
y las llamadas posteriores fallan rapido (sin hacer TCP) durante
_RECOVERY_S segundos. Luego pasa a HALF-OPEN para probar si SISCA
volvio. Si el probe tiene exito, el circuito se cierra de nuevo.

        CLOSED ──(N fallos)──> OPEN ──(timeout)──> HALF-OPEN
           ^                                             |
           └──────────── exito en probe ────────────────┘

Thread-safe via threading.Lock. Estado persiste en memoria del proceso.
"""
import threading
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Any

log = logging.getLogger(__name__)

# ── Parametros por defecto ────────────────────────────────────────────────────
_FAILURE_THRESHOLD = 4    # fallos consecutivos para abrir el circuito
_RECOVERY_S        = 30   # segundos antes de intentar HALF-OPEN
_HALF_OPEN_PROBES  = 1    # requests de prueba en estado HALF-OPEN


class Estado(str, Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class _Metrics:
    fallos_consecutivos: int = 0
    total_exitos:        int = 0
    total_fallos:        int = 0
    total_rechazados:    int = 0   # llamadas bloqueadas por circuito abierto
    ultimo_fallo:        float = 0.0
    ultimo_exito:        float = 0.0


class CircuitBreakerAbiertoError(Exception):
    """Se lanza cuando el circuito esta abierto y se bloquea la llamada."""


class CircuitBreaker:
    """
    Decorador / wrapper thread-safe para proteger llamadas a SISCA.

    Uso directo:
        cb = CircuitBreaker(name='sisca')
        result = cb.call(cliente.ping)

    Como decorador:
        @sisca_cb.protect
        def publicar(...): ...
    """

    def __init__(self,
                 name: str = 'sisca',
                 failure_threshold: int = _FAILURE_THRESHOLD,
                 recovery_timeout: float = _RECOVERY_S):
        self.name             = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self._estado           = Estado.CLOSED
        self._lock             = threading.Lock()
        self._metrics          = _Metrics()

    # ── Estado ───────────────────────────────────────────────────────────────

    @property
    def estado(self) -> Estado:
        return self._estado

    @property
    def esta_abierto(self) -> bool:
        return self._estado == Estado.OPEN

    def _puede_pasar(self) -> bool:
        """True si la llamada debe ejecutarse; False si debe rechazarse."""
        with self._lock:
            if self._estado == Estado.CLOSED:
                return True
            if self._estado == Estado.OPEN:
                elapsed = time.monotonic() - self._metrics.ultimo_fallo
                if elapsed >= self.recovery_timeout:
                    log.info(f"[CB:{self.name}] OPEN→HALF_OPEN (recovery tras {elapsed:.0f}s)")
                    self._estado = Estado.HALF_OPEN
                    return True
                return False
            # HALF_OPEN: deja pasar exactamente 1 prueba
            return True

    def _on_exito(self) -> None:
        with self._lock:
            prev = self._estado
            self._estado = Estado.CLOSED
            self._metrics.fallos_consecutivos = 0
            self._metrics.total_exitos += 1
            self._metrics.ultimo_exito = time.monotonic()
            if prev != Estado.CLOSED:
                log.info(f"[CB:{self.name}] {prev}→CLOSED (exito)")

    def _on_fallo(self) -> None:
        with self._lock:
            self._metrics.fallos_consecutivos += 1
            self._metrics.total_fallos += 1
            self._metrics.ultimo_fallo = time.monotonic()
            if (self._estado == Estado.CLOSED and
                    self._metrics.fallos_consecutivos >= self.failure_threshold):
                self._estado = Estado.OPEN
                log.warning(
                    f"[CB:{self.name}] CLOSED→OPEN "
                    f"({self._metrics.fallos_consecutivos} fallos consecutivos)"
                )
            elif self._estado == Estado.HALF_OPEN:
                self._estado = Estado.OPEN
                log.warning(f"[CB:{self.name}] HALF_OPEN→OPEN (fallo en probe)")

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """Ejecuta fn(*args, **kwargs) respetando el estado del circuito."""
        if not self._puede_pasar():
            self._metrics.total_rechazados += 1
            elapsed = time.monotonic() - self._metrics.ultimo_fallo
            resta   = max(0, self.recovery_timeout - elapsed)
            raise CircuitBreakerAbiertoError(
                f"Circuito SISCA abierto. Reintento en {resta:.0f}s."
            )
        try:
            result = fn(*args, **kwargs)
            self._on_exito()
            return result
        except CircuitBreakerAbiertoError:
            raise
        except Exception as exc:
            self._on_fallo()
            raise exc

    def protect(self, fn: Callable) -> Callable:
        """Decorador: @cb.protect"""
        from functools import wraps
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(fn, *args, **kwargs)
        return wrapper

    def metrics(self) -> dict:
        with self._lock:
            return {
                'estado':               self._estado.value,
                'fallos_consecutivos':  self._metrics.fallos_consecutivos,
                'total_exitos':         self._metrics.total_exitos,
                'total_fallos':         self._metrics.total_fallos,
                'total_rechazados':     self._metrics.total_rechazados,
                'recovery_timeout_s':   self.recovery_timeout,
                'failure_threshold':    self.failure_threshold,
            }

    def reset(self) -> None:
        """Fuerza CLOSED (util en tests o reset manual desde admin)."""
        with self._lock:
            self._estado = Estado.CLOSED
            self._metrics = _Metrics()
            log.info(f"[CB:{self.name}] Reset manual -> CLOSED")


# ── Singleton global ──────────────────────────────────────────────────────────
# Todas las llamadas a SISCA comparten este circuito.
sisca_cb = CircuitBreaker(name='sisca', failure_threshold=4, recovery_timeout=30)
