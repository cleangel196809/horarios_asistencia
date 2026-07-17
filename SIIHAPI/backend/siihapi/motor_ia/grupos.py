"""
Fase 1 — Generación automática de GRUPOS por asignatura.

Regla:  grupos = techo(num_estudiantes / capacidad_grupo)
 - Virtual:    8 a 30 estudiantes por grupo
 - Presencial: máximo según capacidad del salón (default 35)
 - Se balancean los grupos para no sobrecargar uno.
"""
import math

VIRT_MIN, VIRT_MAX = 8, 30
PRES_CAP_DEFAULT = 35


def calcular_grupos(num_estudiantes, modalidad='PRES', capacidad_salon=None):
    """Devuelve dict: {num_grupos, estudiantes_por_grupo, capacidad_usada}."""
    n = max(0, int(num_estudiantes or 0))
    if n == 0:
        return {'num_grupos': 0, 'estudiantes_por_grupo': 0, 'capacidad_usada': 0}

    es_virtual = (modalidad or '').upper() == 'VIRT'
    if es_virtual:
        cap = VIRT_MAX
        grupos = max(1, math.ceil(n / cap))
        # Si quedan grupos con menos del mínimo, reducir nº de grupos
        while grupos > 1 and (n / grupos) < VIRT_MIN:
            grupos -= 1
    else:
        cap = int(capacidad_salon) if capacidad_salon else PRES_CAP_DEFAULT
        cap = max(1, cap)
        grupos = max(1, math.ceil(n / cap))

    por_grupo = math.ceil(n / grupos)  # balanceado
    return {'num_grupos': grupos, 'estudiantes_por_grupo': por_grupo, 'capacidad_usada': cap}


def plan_de_grupos(periodo_codigo=None):
    """Genera el plan de grupos a partir de las matriculas ACTIVAS:
    cuenta estudiantes por (programa, ciclo, asignatura) y calcula los grupos.
    Devuelve lista de dicts (salida intermedia de la Fase 1)."""
    from apps.matriculas.models import Matricula, Periodo
    from collections import defaultdict

    per = None
    if periodo_codigo:
        per = Periodo.objects.filter(codigo=periodo_codigo).first()
    if not per:
        per = Periodo.objects.filter(activo=True).first()

    qs = Matricula.objects.filter(estado='ACTIVA').select_related(
        'materia__programa', 'estudiante')
    if per:
        qs = qs.filter(periodo=per)

    # contar estudiantes por (materia)
    conteo = defaultdict(set)        # materia_id -> set(estudiante_id)
    info = {}                        # materia_id -> (materia, programa, ciclo)
    for m in qs:
        mat = m.materia
        conteo[mat.id_materia].add(m.estudiante_id)
        if mat.id_materia not in info:
            prog = getattr(mat, 'programa', None)
            info[mat.id_materia] = (mat, prog)

    salida = []
    for mid, estudiantes in conteo.items():
        mat, prog = info[mid]
        n = len(estudiantes)
        modalidad = getattr(prog, 'modalidad', 'PRES') if prog else 'PRES'
        g = calcular_grupos(n, modalidad)
        salida.append({
            'programa': getattr(prog, 'nombre', '—') if prog else '—',
            'programa_codigo': getattr(prog, 'codigo', '') if prog else '',
            'modalidad': 'Virtual' if (modalidad or '').upper() == 'VIRT' else 'Presencial',
            'ciclo': getattr(mat, 'ciclo', 1),
            'asignatura': f"[{mat.codigo}] {mat.nombre}",
            'codigo_materia': mat.codigo,
            'estudiantes': n,
            'num_grupos': g['num_grupos'],
            'estudiantes_por_grupo': g['estudiantes_por_grupo'],
        })
    salida.sort(key=lambda x: (x['programa'], x['ciclo'], x['asignatura']))
    return salida
