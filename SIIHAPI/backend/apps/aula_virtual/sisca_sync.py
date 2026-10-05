"""
SIIHAPI · apps/aula_virtual — envío de asistencia consolidada a SISCA.

Reutiliza el patrón ya probado de `apps/integracion_sisca/cliente.py`
(HTTP + JWT/Bearer + reintentos con backoff + circuit breaker +
auditoría en `integracion_log`) en vez de abrir un segundo camino hacia
SISCA: se extiende `ClienteSISCA` con un método más, sin tocar el
módulo núcleo.

⚠️ Dos cosas que dependen del lado de SISCA y hay que confirmar antes de
   darlas por funcionando en producción:

   1. El endpoint `POST /api/v1/asistencia/virtual` todavía NO existe en
      SISCA. Mientras no exista, el envío falla de forma controlada: la
      sesión queda `sincronizada_sisca=False` con el error guardado y se
      puede reintentar (`reintentar_sincronizacion`) sin perder datos.
   2. `operacion='PUBLICAR_ASISTENCIA'` es un valor nuevo para
      `integracion_log.operacion` (la columna es `managed=False` y aquí
      NO se altera). Si esa tabla tiene un CHECK constraint sobre la
      columna, habrá que ampliarlo — ver el script SQL del esquema. El
      `_log` de `ClienteSISCA` ya traga sus propias excepciones, así que
      en el peor caso se pierde la fila de auditoría, nunca el envío.
"""
import logging

from django.utils import timezone

from apps.integracion_sisca.circuit_breaker import CircuitBreakerAbiertoError, sisca_cb
from apps.integracion_sisca.cliente import ClienteSISCA, ClienteSISCAError

log = logging.getLogger(__name__)

OPERACION_LOG = 'PUBLICAR_ASISTENCIA'
ENDPOINT_SISCA = '/api/v1/asistencia/virtual'


class ClienteAsistenciaVirtual(ClienteSISCA):
    """`ClienteSISCA` + el envío de asistencia de una sesión virtual."""

    def publicar_asistencia_virtual(self, payload: dict) -> dict:
        try:
            return sisca_cb.call(
                self._request, 'POST', ENDPOINT_SISCA, payload, OPERACION_LOG
            )
        except CircuitBreakerAbiertoError as e:
            # Mismo contrato que el resto del cliente: hacia afuera todo
            # error de integración es un ClienteSISCAError.
            log.warning('[aula_virtual] circuit breaker abierto: %s', e)
            raise ClienteSISCAError(str(e)) from e


def construir_payload(sesion) -> dict:
    """Asistencia consolidada de una sesión, lista para SISCA.

    Se envían minutos acumulados y no marcas sueltas porque lo que SISCA
    registra es la asistencia a una clase, no un log de conexiones.
    """
    participantes = sesion.participantes.select_related('usuario').all()
    return {
        'origen': 'SIIHAPI/aula_virtual',
        'id_sesion_siihapi': sesion.id_sesion,
        'materia_codigo': sesion.canal.materia.codigo,
        'materia_id': sesion.canal.materia_id,
        'docente_correo': sesion.canal.docente.usuario.correo,
        'periodo': sesion.canal.periodo.codigo if sesion.canal.periodo else None,
        'titulo': sesion.titulo,
        'fecha_inicio': sesion.fecha_inicio.isoformat(),
        'duracion_minutos': sesion.duracion_minutos,
        'modalidad': 'VIRTUAL',
        'participantes': [
            {
                'correo': p.usuario.correo,
                'documento': p.usuario.cedula or None,
                'hora_entrada': p.hora_entrada.isoformat(),
                'hora_salida': p.hora_salida.isoformat() if p.hora_salida else None,
                'minutos': p.minutos_acumulados,
                # Criterio de "asistió": haber estado al menos la mitad de
                # la clase. Un usuario que entra 2 minutos y se cae no
                # debería contar como asistencia en SISCA.
                'asistio': p.minutos_acumulados * 2 >= sesion.duracion_minutos,
            }
            for p in participantes
        ],
        'total_participantes': participantes.count(),
    }


def enviar_asistencia(sesion) -> tuple[bool, str]:
    """Envía la asistencia de `sesion` a SISCA.

    Devuelve `(ok, detalle)` y deja el resultado persistido en la propia
    sesión. NUNCA propaga la excepción: cerrar una clase no puede fallar
    porque SISCA esté caído — para eso está el reintento.
    """
    try:
        respuesta = ClienteAsistenciaVirtual().publicar_asistencia_virtual(
            construir_payload(sesion))
    except ClienteSISCAError as e:
        sesion.sincronizada_sisca = False
        sesion.error_sincronizacion = str(e)[:1000]
        sesion.save(update_fields=['sincronizada_sisca', 'error_sincronizacion'])
        log.warning('[aula_virtual] sesión %s no sincronizada: %s', sesion.pk, e)
        return False, str(e)
    except Exception as e:  # noqa: BLE001 — red de seguridad, ver docstring
        sesion.sincronizada_sisca = False
        sesion.error_sincronizacion = f'Error inesperado: {e}'[:1000]
        sesion.save(update_fields=['sincronizada_sisca', 'error_sincronizacion'])
        log.exception('[aula_virtual] error inesperado sincronizando sesión %s', sesion.pk)
        return False, str(e)

    sesion.sincronizada_sisca = True
    sesion.fecha_sincronizacion = timezone.now()
    sesion.error_sincronizacion = ''
    sesion.save(update_fields=[
        'sincronizada_sisca', 'fecha_sincronizacion', 'error_sincronizacion'])
    return True, str(respuesta)[:500]
