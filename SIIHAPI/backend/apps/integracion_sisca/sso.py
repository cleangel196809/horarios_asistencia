"""
SIIHAPI — Emisión de tickets de entrada a SISCA (Asistencia).

Portal único (decisión 2026-09-30): INTEGRA-PI es la casa y el único lugar
donde alguien escribe una contraseña. Cuando el usuario abre Asistencia
desde el menú, esta capa le firma un ticket corto que SISCA canjea por una
sesión propia (ver SISCA/app/controllers/sso.py y app/utils/sso_ticket.py,
que implementan la otra punta con este mismo formato).

Formato:  base64url(payload_json) + "." + base64url(hmac_sha256)

El secreto es SISCA_API_TOKEN, el mismo que ya comparten las dos apps para
sus llamadas de API: si no coincide entre los dos servicios, la integración
entera ya estaba rota. No se inventa un secreto nuevo que mantener.

El ticket viaja en la URL, así que NO lleva nada sensible: ni contraseñas,
ni hashes, ni el id interno del usuario. Solo el correo (que es la clave de
correspondencia entre las dos bases), el nombre para mostrar y el rol.
"""
import base64
import hmac
import json
import time
import uuid
from hashlib import sha256

from django.conf import settings

VENTANA_S = 60


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')


def firmar_ticket(usuario, ventana_s: int = VENTANA_S) -> str:
    """Firma un ticket de un solo uso para `usuario`.

    El `jti` es lo que le permite a SISCA rechazar un segundo canje: la URL
    queda en el historial del navegador y en los logs del proxy, así que
    reusarla es fácil si no se controla.
    """
    secreto = getattr(settings, 'SISCA_API_TOKEN', '') or ''
    if not secreto:
        raise RuntimeError(
            'SISCA_API_TOKEN no está configurado: sin él no se puede firmar '
            'la entrada a Asistencia.')

    cuerpo = {
        'sub': (usuario.correo or '').lower().strip(),
        'nom': usuario.nombre or '',
        'ape': usuario.apellido or '',
        'rol': usuario.rol or '',
        'jti': uuid.uuid4().hex,
        'exp': int(time.time()) + ventana_s,
    }
    crudo = json.dumps(cuerpo, separators=(',', ':'), sort_keys=True).encode()
    firma = hmac.new(secreto.encode(), crudo, sha256).digest()
    return f'{_b64e(crudo)}.{_b64e(firma)}'


def url_entrada_sisca(usuario) -> str:
    """URL completa a la que mandar al usuario para abrir Asistencia."""
    base = (getattr(settings, 'SISCA_API_URL', '') or 'http://localhost:8080').rstrip('/')
    return f'{base}/sso/entrar?t={firmar_ticket(usuario)}'
