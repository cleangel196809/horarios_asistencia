"""
SIIHAPI - Context processor global: ciclos de formacion (Periodo).

Expone en TODAS las plantillas (via TEMPLATES.OPTIONS.context_processors)
la lista de ciclos de formacion disponibles y cual es el actual, para el
selector del topbar (base.html). Todos los roles autenticados lo ven;
solo Admin/Decano/Secretaria Academica pueden crear uno nuevo (ver
siihapi.permisos.puede_gestionar_periodos).
"""
from .models import Periodo
from .periodo_utils import get_periodo_seleccionado


def periodos_ctx(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    from siihapi.permisos import puede_gestionar_periodos, es_solo_consulta

    periodos = list(Periodo.objects.order_by('-fecha_inicio', '-id_periodo'))
    # Fase 3 (2026-09-04): "actual" ahora es el ciclo que el usuario eligio
    # en el topbar (sesion), no siempre el marcado activo=True en la BD.
    seleccionado = get_periodo_seleccionado(request)
    actual = seleccionado or (periodos[0] if periodos else None)

    return {
        'periodos_disponibles': periodos,
        'periodo_actual_global': actual,
        'puede_crear_periodo': puede_gestionar_periodos(user),
        # Fase 3 (2026-09-04): Bienestar Academico y Mentorias -- ocultan en
        # las plantillas los botones/enlaces que ejecutan el Motor IA,
        # aprueban/editan/publican horarios, hacen carga masiva o integran
        # con SISCA (el backend tambien los bloquea, ver permisos.py).
        'es_solo_consulta': es_solo_consulta(user),
    }
