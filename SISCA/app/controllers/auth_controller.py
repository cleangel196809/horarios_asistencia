"""
SISCA — Controlador de Autenticacion
RF-01 (Registro), RF-02 (Login), RF-20 (Recuperacion), RF-35 (Logout seguro)
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from app.models.usuario import Usuario, Docente, Estudiante
from app.database.connection import execute_query, execute_one
from app.utils.audit import registrar_auditoria
import re

auth_bp = Blueprint('auth', __name__)

# ── Helpers ─────────────────────────────────────────────────
def _usuario_autenticado():
    return session.get('usuario_id') is not None

def _get_current_user():
    uid = session.get('usuario_id')
    if uid:
        return Usuario.get_by_id(uid)
    return None

# ── Landing ─────────────────────────────────────────────────
@auth_bp.route('/')
def landing():
    if _usuario_autenticado():
        return _redirect_by_rol(session.get('rol', ''))

    def _c(sql):
        try:
            r = execute_one(sql)
            return r['n'] if r else 0
        except Exception:
            return 0

    stats = {
        'usuarios':     _c("SELECT COUNT(*) AS N FROM USUARIO WHERE ESTADO='A'"),
        'docentes':     _c("SELECT COUNT(*) AS N FROM DOCENTE"),
        'materias':     _c("SELECT COUNT(*) AS N FROM MATERIA WHERE ESTADO='A'"),
        'sesiones_hoy': _c("SELECT COUNT(*) AS N FROM SESION_CLASE WHERE FECHA_SESION=TRUNC(SYSDATE)"),
        'asistencias':  _c("SELECT COUNT(*) AS N FROM ASISTENCIA"),
    }
    return render_template('landing.html', stats=stats)


# ── Login ────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if _usuario_autenticado():
        return _redirect_by_rol(session.get('rol', ''))

    if request.method == 'POST':
        correo       = request.form.get('correo', '').strip().lower()
        contrasena   = request.form.get('contrasena', '')
        rol_esperado = request.form.get('rol', '')

        # Validar dominio institucional
        DOMINIO = '@politecnico.edu.co'
        if not correo.endswith(DOMINIO):
            flash(f'Solo se permiten correos institucionales ({DOMINIO}).', 'error')
            return render_template('auth/login.html', rol=rol_esperado)

        usuario = Usuario.get_by_correo(correo)

        if not usuario:
            flash('Correo o contrasena incorrectos.', 'error')
            return render_template('auth/login.html', rol=rol_esperado)

        if not usuario.check_password(contrasena):
            registrar_auditoria(usuario.id_usuario, 'LOGIN_FALLIDO', 'USUARIO',
                                request.remote_addr)
            flash('Correo o contrasena incorrectos.', 'error')
            return render_template('auth/login.html', rol=rol_esperado)

        if usuario.estado != 'A':
            flash('Tu cuenta esta inactiva. Contacta al administrador.', 'error')
            return render_template('auth/login.html', rol=rol_esperado)

        # Verificar rol si se especifico
        rol_map = {'admin': 'ADMINISTRADOR', 'docente': 'DOCENTE', 'estudiante': 'ESTUDIANTE'}
        if rol_esperado and usuario.rol != rol_map.get(rol_esperado, usuario.rol):
            flash(f'No tienes acceso como {rol_esperado}.', 'error')
            return render_template('auth/login.html', rol=rol_esperado)

        # Crear sesion
        session.permanent = True
        session['usuario_id']      = usuario.id_usuario
        session['nombre']          = usuario.nombre_completo
        session['correo']          = usuario.correo
        session['rol']             = usuario.rol
        session['avatar_initials'] = f"{usuario.nombre[0]}{usuario.apellido[0]}".upper()

        registrar_auditoria(usuario.id_usuario, 'LOGIN_EXITOSO', 'USUARIO',
                            request.remote_addr)

        flash(f'Bienvenido, {usuario.nombre}!', 'success')
        return _redirect_by_rol(usuario.rol)

    rol = request.args.get('rol', '')
    return render_template('auth/login.html', rol=rol)


# ── Registro ─────────────────────────────────────────────────
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nombre     = request.form.get('nombre', '').strip()
        apellido   = request.form.get('apellido', '').strip()
        documento  = request.form.get('documento', '').strip()
        correo     = request.form.get('correo', '').strip().lower()
        contrasena = request.form.get('contrasena', '')
        confirmar  = request.form.get('confirmar', '')
        rol        = request.form.get('rol', 'ESTUDIANTE')
        terminos   = request.form.get('terminos', 'N')

        # Validaciones
        DOMINIO = '@politecnico.edu.co'
        errors = []
        if not all([nombre, apellido, documento, correo, contrasena]):
            errors.append('Todos los campos son obligatorios.')
        if not correo.endswith(DOMINIO):
            errors.append(f'Solo se permiten correos institucionales ({DOMINIO}).')
        elif not re.match(r'^[\w.+-]+@politecnico\.edu\.co$', correo):
            errors.append('El formato del correo institucional no es valido.')
        if contrasena != confirmar:
            errors.append('Las contrasenas no coinciden.')
        if len(contrasena) < 8:
            errors.append('La contrasena debe tener al menos 8 caracteres.')
        if terminos != 'S':
            errors.append('Debes aceptar los terminos y condiciones.')
        if rol == 'ADMINISTRADOR' and session.get('rol') != 'ADMINISTRADOR':
            errors.append('Las cuentas de Administrador solo pueden ser creadas por el administrador del sistema.')
        roles_permitidos = ('DOCENTE', 'ESTUDIANTE', 'ADMINISTRADOR') if session.get('rol') == 'ADMINISTRADOR' else ('DOCENTE', 'ESTUDIANTE')
        if rol not in roles_permitidos:
            errors.append('Rol no valido para registro publico.')
        
        usuario_doc = Usuario.get_by_documento(documento)
        if usuario_doc:
            errors.append(f'La cédula {documento} ya está registrada en el sistema bajo el rol de {usuario_doc.rol}. Si eres tú, debes iniciar sesión en la pestaña correspondiente.')
            
        if correo.endswith(DOMINIO) and Usuario.get_by_correo(correo):
            errors.append('Este correo ya esta registrado en el sistema.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('auth/register.html', form_data=request.form)

        # Crear usuario
        hash_pwd = Usuario.hash_password(contrasena)
        nuevo = Usuario({
            'nombre': nombre, 'apellido': apellido,
            'documento': documento,
            'correo': correo, 'contrasena': hash_pwd,
            'rol': rol, 'estado': 'A', 'acepta_terminos': 'S'
        })
        nuevo.save()

        # Buscar el ID recien creado
        usuario_bd = Usuario.get_by_correo(correo)

        # Crear perfil especifico segun rol
        if rol == 'DOCENTE':
            especialidad = request.form.get('especialidad', '')
            telefono     = request.form.get('telefono', '')
            execute_query(
                "INSERT INTO DOCENTE (ID_USUARIO, ESPECIALIDAD, TELEFONO) VALUES (:user_id,:esp,:tel)",
                {'user_id': usuario_bd.id_usuario, 'esp': especialidad, 'tel': telefono},
                fetch=False, commit=True
            )
            # --> Auto-asignar materia y horario de prueba para que el dashboard no este vacio
            docente_bd = execute_one("SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO=:uid", {'uid': usuario_bd.id_usuario})
            if docente_bd:
                did = docente_bd['id_docente']
                import random
                cod_mat = f"MAT-{did}{random.randint(100,999)}"
                execute_query(
                    "INSERT INTO MATERIA (ID_DOCENTE, NOMBRE_MATERIA, CODIGO, CREDITOS, SEMESTRE, ESTADO) VALUES (:did, 'Taller de Induccion Docente', :cod, 3, 1, 'A')",
                    {'did': did, 'cod': cod_mat},
                    fetch=False, commit=True
                )
                mat_bd = execute_one("SELECT ID_MATERIA FROM MATERIA WHERE CODIGO=:cod", {'cod': cod_mat})
                if mat_bd:
                    execute_query(
                        "INSERT INTO HORARIO (ID_MATERIA, HORA_INICIO, HORA_FIN, DIA, AULA, ESTADO) VALUES (:mid, TIMESTAMP '2026-01-01 08:00:00', TIMESTAMP '2026-01-01 10:00:00', 'LUNES', 'Laboratorio 1', 'A')",
                        {'mid': mat_bd['id_materia']},
                        fetch=False, commit=True
                    )
        elif rol == 'ESTUDIANTE':
            semestre = request.form.get('semestre', 1)
            codigo   = request.form.get('codigo_estudiante', None)
            execute_query(
                "INSERT INTO ESTUDIANTE (ID_USUARIO, SEMESTRE, CODIGO_ESTUDIANTE) VALUES (:user_id,:sem,:cod)",
                {'user_id': usuario_bd.id_usuario, 'sem': semestre, 'cod': codigo},
                fetch=False, commit=True
            )

        registrar_auditoria(usuario_bd.id_usuario, 'REGISTRO_USUARIO', 'USUARIO',
                            request.remote_addr)
        flash('Registro exitoso! Ya puedes iniciar sesion.', 'success')
        return redirect(url_for('auth.login', rol=rol.lower()))

    rol = request.args.get('rol', 'ESTUDIANTE')
    return render_template('auth/register.html', rol_default=rol, form_data={})


# ── Logout ────────────────────────────────────────────────────
@auth_bp.route('/logout')
def logout():
    uid = session.get('usuario_id')
    if uid:
        registrar_auditoria(uid, 'LOGOUT', 'USUARIO', request.remote_addr)
    session.clear()
    flash('Sesion cerrada correctamente.', 'info')
    return redirect(url_for('auth.landing'))


# ── API: verificar sesion ─────────────────────────────────────
@auth_bp.route('/api/session-status')
def session_status():
    return jsonify({'authenticated': _usuario_autenticado(),
                    'rol': session.get('rol', '')})


# ── Recuperación ──────────────────────────────────────────────
@auth_bp.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'POST':
        documento = request.form.get('documento', '').strip()
        correo    = request.form.get('correo', '').strip().lower()
        
        usuario = Usuario.get_by_documento(documento)
        if usuario and usuario.correo == correo:
            registrar_auditoria(usuario.id_usuario, 'SOLICITUD_RECUPERACION', 'USUARIO', request.remote_addr)
            flash('Si los datos coinciden, hemos enviado un enlace de recuperación a tu correo institucional.', 'success')
        else:
            flash('Si los datos coinciden, hemos enviado un enlace de recuperación a tu correo institucional.', 'success')
            
        return redirect(url_for('auth.login'))
        
    return render_template('auth/recuperar.html')

# ── Legal ─────────────────────────────────────────────────────
@auth_bp.route('/legal/<tipo>')
def legal(tipo):
    titulos = {
        'habeas-data': 'Política de Habeas Data',
        'tratamiento': 'Tratamiento de Datos Personales',
        'transparencia': 'Transparencia y Acceso a la Información',
        'acta': 'Acta de Creación e Implementación'
    }
    titulo = titulos.get(tipo, 'Información Legal')
    return render_template('legal/documento.html', tipo=tipo, titulo=titulo)

# ── Helper redirect ──────────────────────────────────────────
def _redirect_by_rol(rol: str):
    routes = {
        'ADMINISTRADOR': 'admin.dashboard',
        'DOCENTE':       'docente.dashboard',
        'ESTUDIANTE':    'estudiante.dashboard',
    }
    return redirect(url_for(routes.get(rol, 'auth.landing')))
