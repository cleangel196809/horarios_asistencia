"""
SIIHAPI - Cache in-process para resultados del LLM.

Evita llamadas redundantes al LLM cuando el mismo archivo (mismo hash
SHA-256 del contenido) ya fue analizado recientemente.

Por que importa en produccion:
  - Gemini/OpenAI cobran por token; un archivo de 100 horarios
    puede costar $0.01-0.05 USD por analisis. Si el coordinador
    hace clic en "Analizar" 10 veces en el mismo archivo, son
    10 llamadas identicas. Con cache: 1 llamada real, 9 desde cache.
  - Latencia: LLM tarda 3-8s; cache responde en microsegundos.

Implementacion: LRU in-process con TTL. Sin dependencias externas
(no requiere Redis). Para escalar a multi-proceso usar Redis con
django.core.cache.

Clave de cache: SHA-256(contenido_bytes) + proveedor_llm
"""
import hashlib
import time
import threading
from typing import Any, Optional

_DEFAULT_TTL_S  = 3600   # 1 hora
_DEFAULT_MAX    = 128     # max entradas en el LRU


class _Entrada:
    __slots__ = ('valor', 'expires_at')
    def __init__(self, valor: Any, ttl: float):
        self.valor      = valor
        self.expires_at = time.monotonic() + ttl


class CacheLLM:
    """
    Cache LRU thread-safe con TTL para resultados del LLM.
    No persiste entre reinicios del servidor (intencional: el LLM
    podria haber mejorado o el schema de datos cambio).
    """

    def __init__(self, max_size: int = _DEFAULT_MAX, ttl: float = _DEFAULT_TTL_S):
        self._max  = max_size
        self._ttl  = ttl
        self._data: dict[str, _Entrada] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # ── Clave ────────────────────────────────────────────────────────────────

    @staticmethod
    def make_key(contenido: bytes, proveedor: str = '', periodo: str = '') -> str:
        """Genera clave unica a partir del hash del contenido."""
        h = hashlib.sha256(contenido).hexdigest()
        return f"{h[:16]}:{proveedor}:{periodo}"

    # ── Get / Set ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.monotonic() > entry.expires_at:
                del self._data[key]
                self._misses += 1
                return None
            # Mover al final (LRU touch): re-insertar
            self._data.pop(key)
            self._data[key] = entry
            self._hits += 1
            return entry.valor

    def set(self, key: str, valor: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            if key in self._data:
                self._data.pop(key)
            elif len(self._data) >= self._max:
                # Evict LRU (primer elemento del dict ordenado)
                oldest = next(iter(self._data))
                del self._data[oldest]
            self._data[key] = _Entrada(valor, ttl if ttl is not None else self._ttl)

    def invalidar(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def limpiar(self) -> int:
        """Elimina entradas expiradas. Retorna cuantas se eliminaron."""
        now = time.monotonic()
        with self._lock:
            expiradas = [k for k, e in self._data.items() if now > e.expires_at]
            for k in expiradas:
                del self._data[k]
        return len(expiradas)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                'entradas_activas': len(self._data),
                'max_size':         self._max,
                'ttl_s':            self._ttl,
                'hits':             self._hits,
                'misses':           self._misses,
                'hit_rate_pct':     round(self._hits / total * 100, 1) if total else 0,
            }


# ── Singleton global ──────────────────────────────────────────────────────────
cache_llm = CacheLLM(max_size=128, ttl=3600)
