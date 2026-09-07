"""
SIIHAPI - Ciclo de formacion "seleccionado" por el usuario en el topbar.

Antes, cada vista que necesitaba "el periodo actual" usaba directamente
Periodo.objects.filter(activo=True).first() -- es decir, el selector del
topbar (base.html) era solo decorativo: cambiar de ciclo ahi no afectaba
ninguna consulta.

Con esto, get_periodo_seleccionado(request) es la unica fuente de verdad:
1) si el usuario eligio un ciclo en el topbar (guardado en su sesion), se
   usa ese: request.session['periodo_id'].
2) si no ha elegido ninguno (o eligio uno que ya no existe), se cae al
   ciclo marcado activo=True en la base de datos (comportamiento anterior).

Fase 3 (2026-09-04).
"""
from .models import Periodo

SESSION_KEY = 'periodo_id'


def get_periodo_seleccionado(request):
    """Devuelve el objeto Periodo que esta vista debe usar para filtrar."""
    periodo_id = request.session.get(SESSION_KEY) if hasattr(request, 'session') else None
    if periodo_id:
        periodo = Periodo.objects.filter(id_periodo=periodo_id).first()
        if periodo:
            return periodo
        # El periodo guardado en sesion ya no existe: limpiar y caer al activo.
        request.session.pop(SESSION_KEY, None)
    return Periodo.objects.filter(activo=True).first()


def set_periodo_seleccionado(request, periodo):
    """Guarda en la sesion el ciclo que el usuario eligio en el topbar."""
    request.session[SESSION_KEY] = periodo.id_periodo if periodo else None
