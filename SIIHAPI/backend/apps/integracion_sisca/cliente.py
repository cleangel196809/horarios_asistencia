"""
SIIHAPI - Cliente HTTP real para integracion con SISCA.

Implementa los endpoints documentados en el RF-40 y RF-42 del documento
tecnico. Usa requests con timeout, reintentos exponenciales y registro
de auditoria en SIIHAPI_INTEGRACION_LOG (RNF-40).
"""
import json
import time
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from django.conf import settings
from django.utils import timezone

from .models import IntegracionLog
from .circuit_breaker import sisca_cb, CircuitBreakerAbiertoError

log = logging.getLogger(__name__)


class ClienteSISCAError(Exception):
    """Error generico de comunicacion con SISCA."""


class ClienteSISCA:
    """Cliente HTTP para hablar con la API de SISCA."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None,
                 timeout: int = 10, max_retries: int = 3):
        cfg = getattr(settings, 'SIIHAPI', {})
        self.base_url = (base_url or cfg.get('SISCA_API_URL') or 'http://localhost:8080').rstrip('/')
        self.token = token or cfg.get('SISCA_API_TOKEN', '')
        self.timeout = timeout
        self.max_retries = max_retries

    # =====================================================
    # Helpers privados
    # =====================================================
    def _headers(self) -> Dict[str, str]:
        h = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'SIIHAPI/1.0 (Politecnico Internacional)',
        }
        if self.token:
            h['Authorization'] = f'Bearer {self.token}'
        return h

    def _request(self, method: str, path: str, payload: Optional[Dict] = None,
                 operacion: str = 'CONSULTAR_ASISTENCIA') -> Dict[str, Any]:
        """Ejecuta un request a SISCA con reintentos y auditoria."""
        url = f"{self.base_url}{path}"
        intentos = 0
        last_error = None
        last_status = None
        respuesta_json: Dict[str, Any] = {}
        inicio = time.time()

        while intentos < self.max_retries:
            intentos += 1
            try:
                resp = requests.request(
                    method,
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                last_status = resp.status_code
                try:
                    respuesta_json = resp.json()
                except ValueError:
                    respuesta_json = {'raw': resp.text[:500]}

                if 200 <= resp.status_code < 300:
                    # Exito
                    duracion = int((time.time() - inicio) * 1000)
                    self._log(operacion, 'EXITO', path, payload, respuesta_json,
                              resp.status_code, intentos, '', duracion)
                    return respuesta_json
                else:
                    last_error = f"HTTP {resp.status_code}: {respuesta_json}"

            except requests.exceptions.ConnectionError as e:
                last_error = f"Conexion fallida: {e}"
            except requests.exceptions.Timeout:
                last_error = f"Timeout despues de {self.timeout}s"
            except Exception as e:
                last_error = f"Error inesperado: {e}"

            # Backoff exponencial entre reintentos
            if intentos < self.max_retries:
                time.sleep(2 ** intentos)

        # Si llegamos aca, todos los reintentos fallaron
        duracion = int((time.time() - inicio) * 1000)
        self._log(operacion, 'ERROR', path, payload, respuesta_json,
                  last_status, intentos, last_error or 'Sin detalle', duracion)
        raise ClienteSISCAError(last_error or 'SISCA no respondio')

    def _log(self, operacion: str, estado: str, endpoint: str, payload, respuesta,
             codigo_http, intentos, error_msg, duracion_ms):
        """Registra en SIIHAPI_INTEGRACION_LOG."""
        try:
            IntegracionLog.objects.create(
                operacion=operacion,
                estado=estado,
                endpoint=endpoint,
                payload=payload or {},
                respuesta=respuesta or {},
                codigo_http=codigo_http,
                intentos=intentos,
                error_msg=error_msg[:1000] if error_msg else '',
                duracion_ms=duracion_ms,
            )
        except Exception:
            pass  # No queremos que el log rompa la integracion

    # =====================================================
    # API publica del cliente
    # =====================================================
    def ping(self) -> bool:
        """Verifica si SISCA esta accesible. Devuelve True/False.
        El ping no pasa por el circuit breaker — sirve para diagnostico."""
        try:
            url = f"{self.base_url}/"
            resp = requests.get(url, timeout=3, headers=self._headers())
            ok = resp.status_code < 500
            if ok:
                sisca_cb._on_exito()   # exito de ping cuenta para cerrar el CB
            return ok
        except Exception:
            return False

    def estado_circuit_breaker(self) -> dict:
        """Expone metricas del circuit breaker para el panel de integracion."""
        return sisca_cb.metrics()

    def publicar_horarios(self, periodo: str, horarios: list) -> Dict[str, Any]:
        """
        RF-40 · Publica horarios a SISCA para que cree las sesiones de clase.

        Args:
            periodo: ej. '2026-2'
            horarios: lista de dicts con la estructura del payload SIIHAPI->SISCA
        """
        payload = {
            'periodo': periodo,
            'horarios': horarios,
            'metadata': {
                'generado_por': 'SIIHAPI v1.0',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'total_sesiones': len(horarios),
            }
        }
        try:
            return sisca_cb.call(
                self._request, 'POST', '/api/v1/horarios/publicar',
                payload, 'PUBLICAR_HORARIOS'
            )
        except CircuitBreakerAbiertoError as e:
            log.warning(f"[SISCA] Circuit breaker abierto: {e}")
            raise ClienteSISCAError(str(e)) from e

    def actualizar_horario(self, id_sisca: str, datos: Dict) -> Dict[str, Any]:
        """RF-40 · Actualiza un horario especifico tras edicion manual."""
        try:
            return sisca_cb.call(
                self._request, 'PUT', f'/api/v1/horarios/{id_sisca}',
                datos, 'ACTUALIZAR_HORARIO'
            )
        except CircuitBreakerAbiertoError as e:
            raise ClienteSISCAError(str(e)) from e

    def cancelar_horario(self, id_sisca: str) -> Dict[str, Any]:
        """RF-40 · Cancela un horario en SISCA."""
        try:
            return sisca_cb.call(
                self._request, 'DELETE', f'/api/v1/horarios/{id_sisca}',
                       None, 'CANCELAR_HORARIO'
            )
        except CircuitBreakerAbiertoError as e:
            raise ClienteSISCAError(str(e)) from e

    def consultar_asistencia_sesion(self, id_sesion: str) -> Dict[str, Any]:
        """RF-42 · Consulta la asistencia de una sesion especifica."""
        try:
            return sisca_cb.call(
                self._request, 'GET', f'/api/v1/asistencia/sesion/{id_sesion}',
                None, 'CONSULTAR_ASISTENCIA'
            )
        except CircuitBreakerAbiertoError as e:
            raise ClienteSISCAError(str(e)) from e

    def consultar_asistencia_materia(self, id_materia: str, periodo: str) -> Dict[str, Any]:
        """RF-42 · Consulta porcentaje de asistencia de una materia en el periodo."""
        try:
            return sisca_cb.call(
                self._request, 'GET',
                f'/api/v1/asistencia/materia/{id_materia}/periodo/{periodo}',
                None, 'CONSULTAR_ASISTENCIA'
            )
        except CircuitBreakerAbiertoError as e:
            raise ClienteSISCAError(str(e)) from e


# ── Singleton thread-safe ─────────────────────────────────────────────────────
import threading as _threading
_cliente: 'ClienteSISCA | None' = None
_lock = _threading.Lock()

def get_cliente() -> ClienteSISCA:
    global _cliente
    if _cliente is None:
        with _lock:
            if _cliente is None:
                _cliente = ClienteSISCA()
    return _cliente
