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
            if request.user.rol not in roles:
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
    return user.is_authenticated and user.rol == 'ADMINISTRADOR'


def es_coordinador(user):
    return user.is_authenticated and user.rol == 'COORDINADOR'


def es_staff(user):
    """Admin o Coordinador."""
    return user.is_authenticated and user.rol in ('ADMINISTRADOR', 'COORDINADOR')


def es_docente(user):
    return user.is_authenticated and user.rol == 'DOCENTE'


def es_estudiante(user):
    return user.is_authenticated and user.rol == 'ESTUDIANTE'
