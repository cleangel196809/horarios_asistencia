"""
SISCA — Entrada desde INTEGRA-PI (SIIHAPI).

El usuario hace clic en "Asistencia" dentro del portal, SIIHAPI le firma un
ticket y lo manda acá. Este blueprint lo canjea por una sesión de SISCA,
creando el usuario espejo si es la primera vez.
"""
import os
import secrets

import bcrypt
from flask import Blueprint, current_app, flash, redirect, request, session, url_for

from app.database.connection import execute_dml, execute_one
from app.utils.audit import registrar_auditoria
from app.utils.sso_ticket import TicketInvalido, verificar

sso_bp = Blueprint('sso', __name__)

# ── Equivalencia de roles ────────────────────────────────────────────
# SIIHAPI maneja 9 roles; SISCA solo 3, y su tabla USUARIO tiene un CHECK
# que no acepta otra cosa. El criterio es NO otorgar de más:
#
#   - Los roles con autoridad de escritura en SIIHAPI (Administrador,
#     Coordinador, Decano, Secretaria Académica) entran como ADMINISTRADOR,
#     que es el único rol de SISCA con capacidad de gestión.
#   - Docente y Estudiante son equivalentes exactos.
#   - BIENESTAR_ACADEMICO y MENTORIAS son de SOLO CONSULTA en SIIHAPI
#     (ver permisos.ROLES_SOLO_CONSULTA). SISCA no tiene modo lectura: el
#     rol más bajo que podría darles igual permite marcar asistencia. Antes
#     que escalarles privilegios en silencio, se les niega la entrada.
#     Si en algún momento SISCA gana un rol de consulta, se mapean ahí.
ROLES = {
    'ADMINISTRADOR':        'ADMINISTRADOR',
    'ADMIN':                'ADMINISTRADOR',
    'COORDINADOR':          'ADMINISTRADOR',
    'DECANO':               'ADMINISTRADOR',
    'SECRETARIA_ACADEMICA': 'ADMINISTRADOR',
    'DOCENTE':              'DOCENTE',
    'ESTUDIANTE':           'ESTUDIANTE',
}
ROLES_SIN_ACCESO = ('BIENESTAR_ACADEMICO', 'MENTORIAS')


def _clave_inutilizable() -> str:
    """Hash bcrypt de un secreto aleatorio que nadie conoce.

    Los usuarios espejo no tienen contraseña en SISCA: entran por el
    portal. Pero la columna CONTRASENA es NOT NULL y el login compara con
    bcrypt.checkpw, que revienta si el valor no es un hash válido. Un hash
    real de datos aleatorios deja la fila consistente y la cuenta
    imposible de usar por contraseña.
    """
    return bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode()


def _espejar_usuario(datos: dict, rol_sisca: str) -> dict | None:
    """Crea o actualiza la fila local del usuario y su fila hija.

    La clave de correspondencia es el CORREO, que es UNIQUE en las dos
    bases. Los datos de identidad los manda siempre SIIHAPI: si allá
    cambian el apellido o el rol, acá se refleja en la siguiente entrada.
    """
    correo = datos['sub'].lower().strip()
    nombre = (datos.get('nom') or correo.split('@')[0])[:100]
    apellido = (datos.get('ape') or '-')[:100]

    existente = execute_one(
        "SELECT ID_USUARIO FROM USUARIO WHERE CORREO = :c", {'c': correo})

    if existente:
        execute_dml(
            """UPDATE USUARIO
                  SET NOMBRE = :n, APELLIDO = :a, ROL = :r, ESTADO = 'A'
                WHERE CORREO = :c""",
            {'n': nombre, 'a': apellido, 'r': rol_sisca, 'c': correo})
    else:
        execute_dml(
            """INSERT INTO USUARIO
                   (ESTADO, NOMBRE, APELLIDO, CORREO, CONTRASENA, ROL, ACEPTA_TERMINOS)
               VALUES ('A', :n, :a, :c, :p, :r, 'S')""",
            {'n': nombre, 'a': apellido, 'c': correo,
             'p': _clave_inutilizable(), 'r': rol_sisca})

    fila = execute_one(
        "SELECT ID_USUARIO, NOMBRE, APELLIDO, CORREO, ROL FROM USUARIO WHERE CORREO = :c",
        {'c': correo})
    if not fila:
        return None
    uid = fila['id_usuario']

    # Las FK de SISCA cuelgan de DOCENTE/ESTUDIANTE, no de USUARIO: sin la
    # fila hija, un docente no puede abrir sesión de clase y un estudiante
    # no puede marcar asistencia.
    if rol_sisca == 'DOCENTE':
        if not execute_one("SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO = :u", {'u': uid}):
            execute_dml("INSERT INTO DOCENTE (ID_USUARIO) VALUES (:u)", {'u': uid})
    elif rol_sisca == 'ESTUDIANTE':
        if not execute_one("SELECT ID_ESTUDIANTE FROM ESTUDIANTE WHERE ID_USUARIO = :u", {'u': uid}):
            execute_dml("INSERT INTO ESTUDIANTE (ID_USUARIO) VALUES (:u)", {'u': uid})
    elif rol_sisca == 'ADMINISTRADOR':
        if not execute_one("SELECT ID_ADMINISTRADOR FROM ADMINISTRADOR WHERE ID_USUARIO = :u", {'u': uid}):
            execute_dml("INSERT INTO ADMINISTRADOR (ID_USUARIO) VALUES (:u)", {'u': uid})

    return fila


def _destino(rol_sisca: str) -> str:
    return {
        'ADMINISTRADOR': 'admin.dashboard',
        'DOCENTE':       'docente.dashboard',
        'ESTUDIANTE':    'estudiante.dashboard',
    }[rol_sisca]


@sso_bp.route('/entrar')
def entrar():
    """Canjea el ticket de INTEGRA-PI por una sesión de SISCA."""
    secreto = current_app.config.get('SISCA_API_TOKEN') or os.getenv('SISCA_API_TOKEN', '')
    try:
        datos = verificar(request.args.get('t', ''), secreto)
    except TicketInvalido as exc:
        # Al usuario no se le dan detalles de por qué falló la firma; al
        # log sí, que es donde hace falta para diagnosticar.
        print(f'[SISCA] SSO rechazado: {exc}')
        flash('El enlace de acceso no es válido o ya venció. Volvé a entrar desde INTEGRA-PI.', 'error')
        return redirect(url_for('auth.login'))

    # Un solo uso: el jti se guarda al canjearlo. Si el mismo ticket vuelve
    # (alguien copió la URL del historial, del Referer o de un log), la
    # clave única de la tabla lo rebota.
    jti = datos['jti'][:64]
    if execute_one("SELECT 1 FROM SSO_TICKET_USADO WHERE JTI = :j", {'j': jti}):
        print(f'[SISCA] SSO rechazado: ticket ya usado ({jti})')
        flash('Ese enlace de acceso ya se usó. Volvé a entrar desde INTEGRA-PI.', 'error')
        return redirect(url_for('auth.login'))
    execute_dml("INSERT INTO SSO_TICKET_USADO (JTI) VALUES (:j)", {'j': jti})

    rol_origen = (datos.get('rol') or '').upper()
    if rol_origen in ROLES_SIN_ACCESO:
        flash('Tu rol es de solo consulta en INTEGRA-PI y Asistencia no tiene ese modo todavía.', 'error')
        return redirect(url_for('auth.login'))
    rol_sisca = ROLES.get(rol_origen)
    if not rol_sisca:
        print(f'[SISCA] SSO rechazado: rol desconocido {rol_origen!r}')
        flash('Tu rol no tiene acceso a Asistencia.', 'error')
        return redirect(url_for('auth.login'))

    fila = _espejar_usuario(datos, rol_sisca)
    if not fila:
        flash('No se pudo preparar tu cuenta en Asistencia. Intentá de nuevo.', 'error')
        return redirect(url_for('auth.login'))

    session.permanent = True
    session['usuario_id']      = fila['id_usuario']
    session['nombre']          = f"{fila['nombre']} {fila['apellido']}"
    session['correo']          = fila['correo']
    session['rol']             = rol_sisca
    session['avatar_initials'] = f"{fila['nombre'][:1]}{fila['apellido'][:1]}".upper()
    session['desde_portal']    = True

    registrar_auditoria(fila['id_usuario'], 'LOGIN_SSO_INTEGRA_PI', 'USUARIO',
                        request.remote_addr)
    return redirect(url_for(_destino(rol_sisca)))
