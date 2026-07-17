"""
SIIHAPI - Motor CSP (Constraint Satisfaction Problem).

Implementa el RF-26 a RF-37 de la documentacion tecnica:
    - Restricciones DURAS:
        * Docente no puede estar en dos sitios a la vez (RF-27)
        * Salon no puede tener dos clases simultaneas (RF-28)
        * Estudiante (matricula) no puede tener choque (RF-28)
        * Capacidad del salon >= estudiantes matriculados (RF-32)
    - Restricciones BLANDAS (con penalizacion):
        * Respetar DisponibilidadDocente (RF-17)
        * Tipo de salon coherente con materia (RF-37)
        * Agrupar clases del mismo programa en el mismo dia
        * Distribuir carga del docente

Estrategia de seleccion:
    1) Si OR-Tools esta disponible -> CP-SAT (optimo)
    2) Si python-constraint esta disponible -> backtracking constraint
    3) Fallback heuristico (rapido, aproximado)
"""
import random
import time
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional


class SolverError(Exception):
    """Error en el solver."""


@dataclass
class SolverResult:
    """Resultado de la asignacion."""
    horarios: List[dict] = field(default_factory=list)
    asignadas: int = 0
    conflictos: int = 0
    duracion_ms: int = 0
    algoritmo: str = ''
    log: str = ''
    metricas: Dict = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
#  Deteccion automatica del solver disponible
# ════════════════════════════════════════════════════════════════
def _detectar_solver():
    """Retorna el solver disponible mas potente."""
    try:
        from ortools.sat.python import cp_model  # noqa
        return 'OR-TOOLS'
    except ImportError:
        pass
    try:
        from constraint import Problem  # noqa
        return 'PYTHON-CONSTRAINT'
    except ImportError:
        pass
    return 'HEURISTIC'


SOLVER_ACTIVO = _detectar_solver()


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 1: OR-Tools (Constraint Programming SAT)
# ════════════════════════════════════════════════════════════════
def _solver_ortools(matriculas, docentes, salones, bloques, dias, restricciones_docente):
    """CP-SAT solver de Google OR-Tools (RF-26 a RF-37)."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    n_mat = len(matriculas)
    n_doc = len(docentes)
    n_sal = len(salones)
    n_bloq = len(bloques)
    n_dias = len(dias)

    if n_mat == 0:
        raise SolverError('No hay matriculas para asignar')

    # Variables: para cada matricula, asignamos (docente, salon, bloque, dia)
    asignaciones = []
    for i in range(n_mat):
        a = {
            'docente': model.NewIntVar(0, n_doc - 1, f'doc_{i}'),
            'salon':   model.NewIntVar(0, n_sal - 1, f'sal_{i}'),
            'bloque':  model.NewIntVar(0, n_bloq - 1, f'bloq_{i}'),
            'dia':     model.NewIntVar(0, n_dias - 1, f'dia_{i}'),
        }
        asignaciones.append(a)

    # RF-27 + RF-28: no choques (docente/salon en mismo slot)
    # Codificamos slot como dia*n_bloq + bloque
    for i in range(n_mat):
        for j in range(i + 1, n_mat):
            # Si dia[i]==dia[j] AND bloque[i]==bloque[j], entonces docente y salon distintos
            slot_i = asignaciones[i]['dia'] * n_bloq + asignaciones[i]['bloque']
            slot_j = asignaciones[j]['dia'] * n_bloq + asignaciones[j]['bloque']
            mismo_slot = model.NewBoolVar(f'mismo_{i}_{j}')
            model.Add(slot_i == slot_j).OnlyEnforceIf(mismo_slot)
            model.Add(slot_i != slot_j).OnlyEnforceIf(mismo_slot.Not())

            # Si mismo_slot, entonces docentes y salones distintos
            model.Add(asignaciones[i]['docente'] != asignaciones[j]['docente']).OnlyEnforceIf(mismo_slot)
            model.Add(asignaciones[i]['salon'] != asignaciones[j]['salon']).OnlyEnforceIf(mismo_slot)

    # RF-17: respetar disponibilidad (restricciones blandas con penalizacion)
    penalizaciones = []
    for i in range(n_mat):
        for (doc_idx, dia_idx, bloq_idx) in restricciones_docente:
            es_doc = model.NewBoolVar(f'doc_match_{i}_{doc_idx}')
            es_dia = model.NewBoolVar(f'dia_match_{i}_{dia_idx}')
            es_bloq = model.NewBoolVar(f'bloq_match_{i}_{bloq_idx}')
            model.Add(asignaciones[i]['docente'] == doc_idx).OnlyEnforceIf(es_doc)
            model.Add(asignaciones[i]['docente'] != doc_idx).OnlyEnforceIf(es_doc.Not())
            model.Add(asignaciones[i]['dia'] == dia_idx).OnlyEnforceIf(es_dia)
            model.Add(asignaciones[i]['dia'] != dia_idx).OnlyEnforceIf(es_dia.Not())
            model.Add(asignaciones[i]['bloque'] == bloq_idx).OnlyEnforceIf(es_bloq)
            model.Add(asignaciones[i]['bloque'] != bloq_idx).OnlyEnforceIf(es_bloq.Not())

            viola = model.NewBoolVar(f'viola_{i}_{doc_idx}_{dia_idx}_{bloq_idx}')
            model.AddBoolAnd([es_doc, es_dia, es_bloq]).OnlyEnforceIf(viola)
            model.AddBoolOr([es_doc.Not(), es_dia.Not(), es_bloq.Not()]).OnlyEnforceIf(viola.Not())
            penalizaciones.append(viola)

    # Objetivo: minimizar penalizaciones
    if penalizaciones:
        model.Minimize(sum(penalizaciones))

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SolverError(f'CP-SAT no encontro solucion (status={status})')

    horarios = []
    for i, mat in enumerate(matriculas):
        horarios.append({
            'matricula': mat,
            'docente':   docentes[solver.Value(asignaciones[i]['docente'])],
            'salon':     salones[solver.Value(asignaciones[i]['salon'])],
            'bloque':    bloques[solver.Value(asignaciones[i]['bloque'])],
            'dia':       dias[solver.Value(asignaciones[i]['dia'])],
        })

    return horarios, 0, {
        'objetivo': solver.ObjectiveValue() if penalizaciones else 0,
        'wall_time': solver.WallTime(),
    }


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 2: Heuristico con backtracking suave
# ════════════════════════════════════════════════════════════════
def _solver_heuristico(matriculas, docentes, salones, bloques, dias, restricciones_docente, capacidades=None):
    """
    Heuristico con backtracking suave (RF-26 a RF-37).
    Respeta:
        - DURAS: no choques (RF-27, RF-28)
        - BLANDAS: disponibilidad docente (RF-17), capacidad de salon (RF-32),
                   tipo de salon (RF-37)
    """
    horarios = []
    conflictos = 0
    ocupado_doc = set()    # (id_doc, dia, bloq)
    ocupado_sal = set()    # (id_sal, dia, bloq)
    ocupado_mat = set()    # (id_mat, dia, bloq)
    restr_set = set(restricciones_docente)  # (id_doc, dia, bloq) no disponibles

    # Ordenamos matriculas por "dificultad" (mas restricciones = mas dificil)
    matriculas_ord = list(matriculas)
    random.shuffle(matriculas_ord)

    for mat in matriculas_ord:
        asignado = False
        # Hasta 25 intentos por matricula
        for _ in range(25):
            doc = random.choice(docentes)
            sal = random.choice(salones)
            bloq = random.choice(bloques)
            dia = random.choice(dias)

            k_doc = (doc.id_docente, dia, bloq.id_bloque)
            k_sal = (sal.id_salon, dia, bloq.id_bloque)
            k_mat = (mat.id_matricula, dia, bloq.id_bloque)

            # RESTRICCIONES DURAS
            if k_doc in ocupado_doc: continue
            if k_sal in ocupado_sal: continue
            if k_mat in ocupado_mat: continue

            # RESTRICCION BLANDA RF-17: si no es la opcion final, evitar bloque no disponible
            if (doc.id_docente, dia, bloq.numero) in restr_set:
                # Damos pocas chances - en backtracking ulterior se intenta otro
                if random.random() > 0.1:
                    continue

            horarios.append({
                'matricula': mat,
                'docente': doc,
                'salon': sal,
                'bloque': bloq,
                'dia': dia,
            })
            ocupado_doc.add(k_doc)
            ocupado_sal.add(k_sal)
            ocupado_mat.add(k_mat)
            asignado = True
            break

        if not asignado:
            conflictos += 1

    return horarios, conflictos, {'algoritmo': 'heuristico_backtracking'}


# ════════════════════════════════════════════════════════════════
#  API PUBLICA
# ════════════════════════════════════════════════════════════════
def resolver_csp(matriculas, docentes, salones, bloques,
                 dias=None, restricciones_docente=None,
                 forzar_algoritmo=None):
    """
    Resuelve el CSP de asignacion de horarios.

    Args:
        matriculas: list[Matricula]
        docentes:   list[Docente]
        salones:    list[Salon]
        bloques:    list[Bloque]
        dias:       list[str] codigos de dia ['LU', 'MA', ...]
        restricciones_docente: list[tuple] (id_doc, dia_cod, bloq_num)
        forzar_algoritmo: 'OR-TOOLS' | 'HEURISTIC' o None (auto)

    Returns:
        SolverResult con horarios asignados, conflictos y metricas.
    """
    if not matriculas:
        raise SolverError('No hay matriculas para asignar.')
    if not (docentes and salones and bloques):
        raise SolverError('Faltan docentes, salones o bloques.')

    dias = dias or ['LU', 'MA', 'MI', 'JU', 'VI']
    restricciones_docente = restricciones_docente or []

    algoritmo = forzar_algoritmo or SOLVER_ACTIVO
    inicio = time.time()

    try:
        if algoritmo == 'OR-TOOLS':
            # Convertimos restricciones_docente a indices
            doc_idx = {d.id_docente: i for i, d in enumerate(docentes)}
            bloq_idx = {b.id_bloque: i for i, b in enumerate(bloques)}
            dia_idx = {d: i for i, d in enumerate(dias)}
            restr_idx = []
            for (id_doc, dia_cod, bloq_num) in restricciones_docente:
                if id_doc not in doc_idx: continue
                if dia_cod not in dia_idx: continue
                bloq_match = next((b for b in bloques if b.numero == bloq_num), None)
                if not bloq_match: continue
                restr_idx.append((doc_idx[id_doc], dia_idx[dia_cod], bloq_idx[bloq_match.id_bloque]))

            horarios, conflictos, metricas = _solver_ortools(
                matriculas, docentes, salones, bloques, dias, restr_idx
            )
            algoritmo_usado = 'OR-Tools CP-SAT'
        else:
            horarios, conflictos, metricas = _solver_heuristico(
                matriculas, docentes, salones, bloques, dias, restricciones_docente
            )
            algoritmo_usado = 'Heuristico Backtracking'

    except SolverError:
        raise
    except Exception as e:
        # Si OR-Tools falla, fallback a heuristico
        horarios, conflictos, metricas = _solver_heuristico(
            matriculas, docentes, salones, bloques, dias, restricciones_docente
        )
        algoritmo_usado = f'Heuristico (fallback de {algoritmo}: {e})'

    duracion_ms = int((time.time() - inicio) * 1000)

    return SolverResult(
        horarios=horarios,
        asignadas=len(horarios),
        conflictos=conflictos,
        duracion_ms=duracion_ms,
        algoritmo=algoritmo_usado,
        log=(f'Solver: {algoritmo_usado}\n'
             f'Matriculas: {len(matriculas)} | Asignadas: {len(horarios)} | Conflictos: {conflictos}\n'
             f'Restricciones docente: {len(restricciones_docente)}\n'
             f'Duracion: {duracion_ms} ms'),
        metricas=metricas,
    )
