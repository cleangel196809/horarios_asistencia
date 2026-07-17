"""SIIHAPI - Middleware de auto-cierre por inactividad (RF-05)."""
from datetime import timedelta
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone


class AutoCierreInactividadMiddleware:
    """
    RF-05 - Cierra automaticamente la sesion tras N minutos de inactividad.

    Verifica el campo `ultima_actividad` del usuario en cada request autenticado.
    Si supera N minutos sin actividad:
        - Si es API (path empieza con /api/) -> 401 JSON
        - Si es navegacion web -> redirige a /login/

    Proteccion: si la sesion es muy reciente (last_login < 1 min), NO cierra
    (evita falsos positivos justo despues de iniciar sesion).
    """

    INACTIVIDAD_MAX_MINUTOS = 30
    THROTTLE_UPDATE_SEC = 60  # cada cuanto guardamos ultima_actividad
    GRACIA_LOGIN_SEC = 60     # margen tras login antes de evaluar inactividad

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip paths que no necesitan check
        path = request.path
        if (path.startswith('/static/') or path.startswith('/media/') or
            path == '/login/' or path == '/logout/' or path == '/' or
            path.startswith('/admin/login/')):
            return self.get_response(request)

        if hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user
            ahora = timezone.now()

            # Periodo de gracia: si acabas de loguearte hace < 60s,
            # NO evaluamos inactividad (evita falsos cierres).
            sesion_es_reciente = (
                user.last_login and
                (ahora - user.last_login) < timedelta(seconds=self.GRACIA_LOGIN_SEC)
            )

            # Evaluar inactividad solo si la sesion NO es reciente
            if not sesion_es_reciente and user.ultima_actividad:
                inactivo = ahora - user.ultima_actividad
                if inactivo > timedelta(minutes=self.INACTIVIDAD_MAX_MINUTOS):
                    from django.contrib.auth import logout as django_logout
                    django_logout(request)
                    if path.startswith('/api/'):
                        return JsonResponse(
                            {'success': False, 'error': 'Sesion cerrada por inactividad'},
                            status=401
                        )
                    else:
                        return redirect('login')

            # Actualizar ultima_actividad con throttle
            try:
                if (not user.ultima_actividad or
                    (ahora - user.ultima_actividad) > timedelta(seconds=self.THROTTLE_UPDATE_SEC)):
                    user.ultima_actividad = ahora
                    user.save(update_fields=['ultima_actividad'])
            except Exception:
                pass  # No queremos que un error de BD rompa el sitio

        return self.get_response(request)
