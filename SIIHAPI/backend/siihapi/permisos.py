"""
SIIHAPI - Decoradores y helpers de control de acceso por rol (RBAC).

Refleja la matriz de permisos de la documentacion tecnica:
    ADMINISTRADOR : acceso total a todos los modulos
    COORDINADOR   : academico, motor IA, horarios, SISCA, reportes
    DOCENTE       : mi horario, disponibilidad, mis materias, mi asistencia
    ESTUDIANTE    : mi horario, mis materias, mis asistencias, mis notas
"""
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def rol_requerido(*roles):
    """
    Decorador que exige que el usuario tenga uno de los roles indicados.

    Uso:
        @rol_requerido('ADMINISTRADOR', 'COORDINADOR')
        def mi_vista(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.rol_efectivo not in roles:
                messages.error(request,
                    f'Acceso denegado. Esta seccion requiere rol: {", ".join(roles)}.')
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# Atajos comunes
admin_required = rol_requerido('ADMINISTRADOR')
staff_required = rol_requerido('ADMINISTRADOR', 'COORDINADOR')
docente_required = rol_requerido('DOCENTE')
estudiante_required = rol_requerido('ESTUDIANTE')


def es_admin(user):
    return user.is_authenticated and user.rol_efectivo == 'ADMINISTRADOR'


def es_coordinador(user):
    return user.is_authenticated and user.rol_efectivo == 'COORDINADOR'


def es_staff(user):
    """Admin o Coordinador."""
    return user.is_authenticated and user.rol_efectivo in ('ADMINISTRADOR', 'COORDINADOR')


def es_docente(user):
    return user.is_authenticated and user.rol_efectivo == 'DOCENTE'


def es_estudiante(user):
    return user.is_authenticated and user.rol_efectivo == 'ESTUDIANTE'


# ── Roles de "solo consulta" (Fase 3, 2026-09-04) ──
# Bienestar Academico y Mentorias comparten el nivel de acceso de
# Coordinador (rol_efectivo == 'COORDINADOR': ven horarios, docentes,
# estudiantes, programas y sedes) pero NUNCA deben poder ejecutar el
# Motor IA, aprobar/editar/publicar horarios, hacer carga masiva ni
# tocar la integracion SISCA. Se usa el rol CRUDO (no rol_efectivo) a
# proposito, igual que ROLES_GESTION_PERIODOS mas abajo.
ROLES_SOLO_CONSULTA = ('BIENESTAR_ACADEMICO', 'MENTORIAS')


def es_solo_consulta(user):
    return user.is_authenticated and user.rol in ROLES_SOLO_CONSULTA


def operacion_required(view_func):
    """Como @staff_required (exige ADMINISTRADOR/COORDINADOR), pero ademas
    bloquea a los roles de solo consulta (Bienestar Academico, Mentorias).
    Usar en las vistas que ejecutan el Motor IA, aprueban/editan/publican
    horarios, hacen carga masiva o integran con SISCA."""
    @wraps(view_func)
    @staff_required
    def wrapper(request, *args, **kwargs):
        if es_solo_consulta(request.user):
            messages.error(request,
                'Tu perfil tiene acceso de solo consulta a este modulo.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def bloquear_solo_consulta(view_func):
    """Como @login_required, pero ademas bloquea a los roles de solo
    consulta (Bienestar Academico, Mentorias) sin restringir a nadie que
    ya tuviera acceso a esta vista (Integracion SISCA hoy solo exige
    login, no rol especifico)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if es_solo_consulta(request.user):
            messages.error(request,
                'Tu perfil tiene acceso de solo consulta a este modulo.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── Ciclos de formacion (periodos academicos) — Fase 2 (2026-09-03) ──
# Solo Admin, Decano y Secretaria Academica pueden crear ciclos nuevos.
# OJO: aqui se usa el rol CRUDO (no rol_efectivo) a proposito, porque
# Coordinador (que rol_efectivo tambien mapea a 'COORDINADOR' junto con
# Decano/Secretaria) NO debe poder crear ciclos, solo verlos.
ROLES_GESTION_PERIODOS = ('ADMIN', 'ADMINISTRADOR', 'DECANO', 'SECRETARIA_ACADEMICA')


def puede_gestionar_periodos(user):
    return user.is_authenticated and user.rol in ROLES_GESTION_PERIODOS


def gestion_periodos_required(view_func):
    """Exige que el usuario pueda crear/gestionar ciclos de formacion."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not puede_gestionar_periodos(request.user):
            messages.error(request, 'No tienes permiso para crear ciclos de formación.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── Roles crudos nuevos (Sprint 2, 2026-09-06 -- adelantado desde el
# Entregable 5 de la especificación Roles+Decano porque el dashboard de
# Bienestar de este Sprint ya lo necesita) ──
# ROL_EQUIVALENCIAS NO se toca: cambiar DECANO/SECRETARIA_ACADEMICA para
# que dejen de mapear a 'COORDINADOR' rompería el módulo de Reportes ya
# entregado (rol_ef == 'ADMINISTRADOR'/@staff_required). En su lugar, estos
# decoradores nuevos revisan el rol CRUDO (mismo patrón que
# ROLES_GESTION_PERIODOS/ROLES_SOLO_CONSULTA de arriba) y se COMPONEN con
# los existentes -- nunca los reemplazan.
def rol_crudo_requerido(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.rol not in roles:
                messages.error(request, 'Acceso denegado a este módulo.')
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


decano_required = rol_crudo_requerido('DECANO', 'ADMIN', 'ADMINISTRADOR')
secretaria_required = rol_crudo_requerido('SECRETARIA_ACADEMICA', 'ADMIN', 'ADMINISTRADOR')
bienestar_required = rol_crudo_requerido('BIENESTAR_ACADEMICO', 'ADMIN', 'ADMINISTRADOR')
mentoria_required = rol_crudo_requerido('MENTORIAS', 'ADMIN', 'ADMINISTRADOR')
