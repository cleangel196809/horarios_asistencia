"""
SISCA — Verificación de tickets de entrada emitidos por SIIHAPI.

Portal único (decisión 2026-09-30): INTEGRA-PI (SIIHAPI) es la casa y el
único lugar donde alguien escribe una contraseña. Cuando el usuario entra a
Asistencia desde el menú, SIIHAPI le firma un ticket corto y SISCA lo
canjea por una sesión propia. SISCA no verifica contraseñas de nadie más
que del administrador de respaldo.

Formato del ticket:  base64url(payload_json) + "." + base64url(hmac_sha256)

El secreto es SISCA_API_TOKEN, el mismo que ya comparten las dos apps para
sus llamadas de API. No se inventa un secreto nuevo: si ese token no
coincide entre los dos servicios, la integración entera ya estaba rota.

El ticket es deliberadamente mínimo y de vida corta:
  - dura VENTANA_S segundos (60 por defecto),
  - es de un solo uso (la tabla SSO_TICKET_USADO guarda el jti),
  - viaja en la URL, así que NO lleva nada sensible: ni contraseñas, ni
    hashes, ni identificadores internos de SIIHAPI. Solo lo que SISCA
    necesita para crear su usuario espejo.
"""
import base64
import hmac
import json
import time
from hashlib import sha256

VENTANA_S = 60


class TicketInvalido(Exception):
    """El ticket no se puede aceptar. El mensaje explica por qué."""


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')


def firmar(datos: dict, secreto: str, ventana_s: int = VENTANA_S) -> str:
    """Emite un ticket. SISCA no la usa en producción — SIIHAPI es quien
    emite — pero vive acá para que las dos puntas compartan exactamente el
    mismo formato y las pruebas puedan generar tickets válidos."""
    cuerpo = dict(datos)
    cuerpo['exp'] = int(time.time()) + ventana_s
    crudo = json.dumps(cuerpo, separators=(',', ':'), sort_keys=True).encode()
    firma = hmac.new(secreto.encode(), crudo, sha256).digest()
    return f'{_b64e(crudo)}.{_b64e(firma)}'


def verificar(ticket: str, secreto: str) -> dict:
    """Devuelve el payload si el ticket es válido; si no, TicketInvalido.

    Verifica la firma ANTES de mirar el contenido: un payload no firmado no
    merece que lo parseemos.
    """
    if not secreto:
        raise TicketInvalido('SISCA_API_TOKEN no está configurado en este servicio')
    if not ticket or ticket.count('.') != 1:
        raise TicketInvalido('ticket con formato inesperado')

    p_b64, f_b64 = ticket.split('.')
    try:
        crudo = _b64d(p_b64)
        firma = _b64d(f_b64)
    except Exception:
        raise TicketInvalido('ticket con base64 inválido')

    esperada = hmac.new(secreto.encode(), crudo, sha256).digest()
    # compare_digest y no ==: la comparación normal corta al primer byte
    # distinto y filtra información por tiempo.
    if not hmac.compare_digest(firma, esperada):
        raise TicketInvalido('firma inválida')

    try:
        datos = json.loads(crudo)
    except Exception:
        raise TicketInvalido('payload ilegible')

    exp = datos.get('exp')
    if not isinstance(exp, int):
        raise TicketInvalido('ticket sin expiración')
    ahora = int(time.time())
    if ahora > exp:
        raise TicketInvalido('ticket vencido')
    # Un `exp` demasiado lejano significa que alguien emitió un ticket de
    # larga duración: no es lo que este esquema promete, así que se rechaza
    # aunque la firma sea buena.
    if exp - ahora > VENTANA_S + 30:
        raise TicketInvalido('ticket con vigencia mayor a la permitida')

    for campo in ('sub', 'rol', 'jti'):
        if not datos.get(campo):
            raise TicketInvalido(f'ticket sin {campo}')

    return datos
