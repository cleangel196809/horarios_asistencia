"""
Fase 2 — Reglas de docentes: creditos->horas, cargas (10/20/40) y disponibilidad.
"""

def horas_materia(creditos, horas_semanales=None):
    """1 credito = 1.5 horas de clase. Si no hay creditos, usa horas_semanales."""
    try:
        c = int(creditos or 0)
    except (TypeError, ValueError):
        c = 0
    if c > 0:
        return round(c * 1.5, 1)
    try:
        return float(horas_semanales or 3)
    except (TypeError, ValueError):
        return 3.0


def cargar_disponibilidad():
    """Devuelve {docente_id: set((dia_cod, bloque_numero))}.
    Si un docente NO tiene registros, se considera disponible siempre (fallback)."""
    disp = {}
    try:
        from apps.personal.models import DisponibilidadDocente
        for d in DisponibilidadDocente.objects.select_related('bloque').all():
            disp.setdefault(d.docente_id, set()).add((d.dia, d.bloque.numero))
    except Exception:
        pass
    return disp


def docente_disponible(disp, docente_id, dia_cod, bloque_numero):
    """True si el docente puede dictar en ese (dia, bloque).
    Sin registros de disponibilidad => disponible (no bloquea la generacion)."""
    s = disp.get(docente_id)
    if not s:
        return True
    return (dia_cod, bloque_numero) in s


def carga_max(docente):
    """Carga maxima semanal del docente (10/20/40). Default 20 si no esta definida."""
    v = getattr(docente, 'carga_horaria_max', None)
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else 20
