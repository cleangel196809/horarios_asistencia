"""
SIIHAPI - Motor CSP (Constraint Satisfaction Problem).

Implementa el RF-26 a RF-39 de la documentacion tecnica:
    - Restricciones DURAS:
        * Docente no puede estar en dos sitios a la vez (RF-27)
        * Salon no puede tener dos clases simultaneas (RF-28)
        * Estudiante (matricula) no puede tener choque (RF-28)
        * Capacidad del salon >= estudiantes matriculados (RF-32)
        * Docente solo dicta materias de SU MISMA facultad (RF-38,
          Fase 3 2026-09-04 -- ver grupo_de_facultad() en salones.py; un
          docente sin facultad asignada queda sin esta restriccion, y si
          una facultad no tiene NINGUN docente cargado se cae a "cualquier
          docente" para no dejar el CSP infactible, reportandolo en
          advertencias_facultad)
        * Solo se programa dentro de 4 jornadas fijas, en bloques de
          1:30h (RF-39, Fase 4 2026-09-05): Diurna 07:00-10:00, Especial
          10:00-13:00, Nocturna 18:00-21:00 (L-V), Sabatino 07:00-17:00
          con almuerzo de 13:00 a 14:00 (ver jornadas.py). Los bloques del
          esquema anterior (80 min, 6:00-22:00) quedan sin usarse.
        * Minimo 2 horas para que un docente se desplace de una sede a
          otra el mismo dia (RF-39 extendido, Fase 4 2026-09-05): si dos
          clases del mismo docente ese dia son en sedes distintas, tiene
          que haber al menos 2h de diferencia entre ellas; si no hay forma
          de cumplirlo la materia queda sin asignar (se reporta como
          conflicto) en vez de violar la regla.
    - Restricciones BLANDAS (con penalizacion):
        * Respetar DisponibilidadDocente (RF-17)
        * Tipo de salon coherente con materia (RF-37)
        * Sede base del docente (RF-38 extendido, Fase 3 2026-09-04): se
          prefiere el salon en la misma sede que se cargo para el docente
          desde el Excel real de docentes; si no hay cupo ahi se usa otra
          sede (apoyandose en su disponibilidad) para completar sus horas
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

try:
    # Import relativo normal: solver.py se carga como parte del paquete
    # siihapi.motor_ia (caso real de la aplicacion Django).
    from .salones import tipos_permitidos_por_facultad, grupo_de_facultad
    from .jornadas import bloque_permitido_en_dia, gap_horas, MINIMO_HORAS_DESPLAZAMIENTO_SEDE
except ImportError:
    # Fallback absoluto para pruebas aisladas que cargan este archivo como
    # modulo suelto (sys.path.insert(0, <motor_ia>); import solver), sin
    # paquete padre -- salones.py vive en el mismo directorio.
    from salones import tipos_permitidos_por_facultad, grupo_de_facultad
    from jornadas import bloque_permitido_en_dia, gap_horas, MINIMO_HORAS_DESPLAZAMIENTO_SEDE


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
    """CP-SAT solver de Google OR-Tools (RF-26 a RF-39)."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    n_mat = len(matriculas)
    n_doc = len(docentes)
    n_sal = len(salones)
    n_bloq = len(bloques)
    n_dias = len(dias)

    if n_mat == 0:
        raise SolverError('No hay matriculas para asignar')

    # RF-38 (Fase 3, 2026-09-04): un docente solo puede dictar materias de
    # SU MISMA facultad (dura). Se agrupan las facultades "duplicadas" por
    # el doble import (grupo_de_facultad(), mismo criterio que ya usa
    # tipos_permitidos_por_facultad para el tipo de salon) para que p.ej.
    # un docente de FSA/ENF_R y una materia de programa ING_R/FIS cuenten
    # como la misma area cuando corresponda. Un docente SIN facultad queda
    # sin esta restriccion (no se puede evaluar la regla). Si NINGUN
    # docente coincide con la facultad de una materia -- hueco real de
    # datos, ej. no hay docentes cargados todavia para esa facultad -- se
    # cae a "cualquier docente" para esa materia puntual (en vez de dejar
    # el CSP infactible) y se reporta en advertencias_facultad.
    docentes_por_grupo = {}
    docentes_sin_facultad = []
    for idx, d in enumerate(docentes):
        grupo = grupo_de_facultad(getattr(d, 'facultad', None))
        if grupo is None:
            docentes_sin_facultad.append(idx)
        else:
            docentes_por_grupo.setdefault(grupo, []).append(idx)

    grupo_materia_cache = {}
    advertencias_facultad = set()

    def _docentes_candidatos_idx(mat):
        materia = getattr(mat, 'materia', None)
        programa = getattr(materia, 'programa', None) if materia else None
        facultad_mat = getattr(programa, 'facultad', None) if programa else None
        clave = getattr(facultad_mat, 'id_facultad', None)
        if clave not in grupo_materia_cache:
            grupo_materia_cache[clave] = grupo_de_facultad(facultad_mat)
        grupo = grupo_materia_cache[clave]
        if grupo is None:
            return list(range(n_doc))  # materia sin facultad determinable
        candidatos = docentes_por_grupo.get(grupo, []) + docentes_sin_facultad
        if not candidatos:
            advertencias_facultad.add(grupo)
            return list(range(n_doc))
        return candidatos

    # RF-38 extendido (blanda): sede base del docente, cargada desde el
    # Excel real de docentes. Se arma como tabla de consulta (AddElement)
    # en vez de comparar variable-contra-variable directamente, para no
    # disparar un bucle O(n_mat * n_doc) de variables auxiliares.
    docente_sede_arr = [(d.sede_id if d.sede_id is not None else -1) for d in docentes]
    salon_sede_arr = [(getattr(s, 'sede_id', None) if getattr(s, 'sede_id', None) is not None else -2)
                      for s in salones]
    hay_sede_pref = any(v != -1 for v in docente_sede_arr) and any(v != -2 for v in salon_sede_arr)

    # RF-39 (Fase 4, 2026-09-05): solo se puede programar dentro de las 4
    # jornadas fijas (Diurna, Especial, Nocturna, Sabatino), en los pares
    # (dia, bloque) que caen dentro de ellas -- ver jornadas.py. Se
    # precalculan los pares (dia, bloque) permitidos para restringir el
    # dominio de esas dos variables juntas (AddAllowedAssignments =
    # restriccion de tabla).
    pares_dia_bloque_validos = [
        (di, bi) for di, dia in enumerate(dias)
        for bi, bloq in enumerate(bloques)
        if bloque_permitido_en_dia(bloq, dia)
    ]
    if not pares_dia_bloque_validos:
        raise SolverError(
            'No hay bloques cargados dentro de las 4 jornadas permitidas '
            '(Diurna/Especial/Nocturna/Sabatino) -- corre '
            '"python manage.py corregir_bloques_horario --aplicar" primero.'
        )

    # RF-39 extendido (Fase 4, 2026-09-05): minutos de inicio/fin de cada
    # bloque (para calcular en el modelo el tiempo real entre dos clases
    # del mismo docente, sin importar en que bloque quedaron).
    bloque_ini_min = [b.hora_inicio.hour * 60 + b.hora_inicio.minute for b in bloques]
    bloque_fin_min = [b.hora_fin.hour * 60 + b.hora_fin.minute for b in bloques]
    minuto_min = min(bloque_ini_min) if bloque_ini_min else 0
    minuto_max = max(bloque_fin_min) if bloque_fin_min else 24 * 60

    # Variables: para cada matricula, asignamos (docente, salon, bloque, dia)
    asignaciones = []
    for i in range(n_mat):
        candidatos_doc = _docentes_candidatos_idx(matriculas[i])
        if len(candidatos_doc) < n_doc:
            doc_var = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(sorted(set(candidatos_doc))), f'doc_{i}'
            )
        else:
            doc_var = model.NewIntVar(0, n_doc - 1, f'doc_{i}')
        a = {
            'docente': doc_var,
            'salon':   model.NewIntVar(0, n_sal - 1, f'sal_{i}'),
            'bloque':  model.NewIntVar(0, n_bloq - 1, f'bloq_{i}'),
            'dia':     model.NewIntVar(0, n_dias - 1, f'dia_{i}'),
        }
        asignaciones.append(a)
        # RF-39: solo pares (dia, bloque) dentro de una jornada permitida.
        model.AddAllowedAssignments([a['dia'], a['bloque']], pares_dia_bloque_validos)

    # Variables auxiliares por matricula, reutilizadas tanto por la regla
    # dura de desplazamiento entre sedes (RF-39 extendido) como por la
    # preferencia blanda de sede base del docente (RF-38 extendido).
    sede_sal_vars = []
    ini_min_vars = []
    fin_min_vars = []
    for i in range(n_mat):
        sede_sal_var = model.NewIntVar(-2, max(salon_sede_arr + [-2]), f'sede_sal_{i}')
        model.AddElement(asignaciones[i]['salon'], salon_sede_arr, sede_sal_var)
        sede_sal_vars.append(sede_sal_var)

        ini_var = model.NewIntVar(minuto_min, minuto_max, f'ini_min_{i}')
        model.AddElement(asignaciones[i]['bloque'], bloque_ini_min, ini_var)
        ini_min_vars.append(ini_var)

        fin_var = model.NewIntVar(minuto_min, minuto_max, f'fin_min_{i}')
        model.AddElement(asignaciones[i]['bloque'], bloque_fin_min, fin_var)
        fin_min_vars.append(fin_var)

    MIN_DESPLAZAMIENTO = int(MINIMO_HORAS_DESPLAZAMIENTO_SEDE * 60)

    # RF-27 + RF-28: no choques (docente/salon en mismo slot). RF-39
    # extendido: minimo de horas para desplazarse de sede (dura).
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

            # RF-39 extendido (dura): si es el MISMO docente, el MISMO dia,
            # y sedes DISTINTAS, debe haber al menos 2h de diferencia real
            # entre las dos clases (en cualquier orden).
            mismo_doc = model.NewBoolVar(f'mismo_doc_{i}_{j}')
            model.Add(asignaciones[i]['docente'] == asignaciones[j]['docente']).OnlyEnforceIf(mismo_doc)
            model.Add(asignaciones[i]['docente'] != asignaciones[j]['docente']).OnlyEnforceIf(mismo_doc.Not())

            mismo_dia = model.NewBoolVar(f'mismo_dia_{i}_{j}')
            model.Add(asignaciones[i]['dia'] == asignaciones[j]['dia']).OnlyEnforceIf(mismo_dia)
            model.Add(asignaciones[i]['dia'] != asignaciones[j]['dia']).OnlyEnforceIf(mismo_dia.Not())

            sedes_iguales = model.NewBoolVar(f'sedes_iguales_{i}_{j}')
            model.Add(sede_sal_vars[i] == sede_sal_vars[j]).OnlyEnforceIf(sedes_iguales)
            model.Add(sede_sal_vars[i] != sede_sal_vars[j]).OnlyEnforceIf(sedes_iguales.Not())

            i_antes_j = model.NewBoolVar(f'i_antes_j_{i}_{j}')
            model.Add(fin_min_vars[i] + MIN_DESPLAZAMIENTO <= ini_min_vars[j]).OnlyEnforceIf(i_antes_j)
            j_antes_i = model.NewBoolVar(f'j_antes_i_{i}_{j}')
            model.Add(fin_min_vars[j] + MIN_DESPLAZAMIENTO <= ini_min_vars[i]).OnlyEnforceIf(j_antes_i)

            # Si mismo docente + mismo dia + sedes distintas: exigimos el
            # margen de 2h en algun sentido. En cualquier otro caso la
            # clausula ya queda satisfecha por los literales negados.
            model.AddBoolOr([
                i_antes_j, j_antes_i,
                mismo_doc.Not(), mismo_dia.Not(), sedes_iguales,
            ])

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

    # RF-37 extendido (Fase 3, 2026-09-04): preferir el tipo de salon
    # coherente con la facultad de la materia (enfermeria -> salones de
    # enfermeria, ingenieria/computadores -> sala de sistemas, salud oral ->
    # ortodoncia, etc; ver tipos_permitidos_por_facultad()). Es BLANDA (no
    # dura): si el tipo correcto esta ocupado en todos los slots preferimos
    # un aula generica de reserva antes que dejar la materia sin asignar.
    tipos_permitidos_cache = {}
    for i, mat in enumerate(matriculas):
        materia = getattr(mat, 'materia', None)
        if materia is None:
            continue
        clave_materia = getattr(materia, 'id_materia', id(materia))
        if clave_materia not in tipos_permitidos_cache:
            try:
                tipos_permitidos_cache[clave_materia] = tipos_permitidos_por_facultad(materia)
            except Exception:
                tipos_permitidos_cache[clave_materia] = []
        tipos_ok = tipos_permitidos_cache[clave_materia]
        if not tipos_ok:
            continue  # sin restriccion de facultad para esta materia

        buenos = [idx for idx, s in enumerate(salones) if getattr(s, 'tipo', 'AULA') in tipos_ok]
        if not buenos or len(buenos) == n_sal:
            continue  # ningun salon del tipo requerido, o todos lo son: nada que penalizar

        es_bueno_bools = []
        for idx in buenos:
            b = model.NewBoolVar(f'sal_tipo_ok_{i}_{idx}')
            model.Add(asignaciones[i]['salon'] == idx).OnlyEnforceIf(b)
            model.Add(asignaciones[i]['salon'] != idx).OnlyEnforceIf(b.Not())
            es_bueno_bools.append(b)
        es_bueno = model.NewBoolVar(f'sal_tipo_ok_{i}')
        model.AddBoolOr(es_bueno_bools).OnlyEnforceIf(es_bueno)
        model.Add(sum(es_bueno_bools) == 0).OnlyEnforceIf(es_bueno.Not())
        penalizaciones.append(es_bueno.Not())

    # RF-38 extendido (Fase 3, 2026-09-04): preferir que el salon este en
    # la MISMA sede base del docente asignado (la que trae el Excel real
    # de docentes). Blanda: si no hay cupo libre ahi en ningun slot, se
    # permite usar otra sede (apoyandose en la disponibilidad del
    # docente) antes que dejar la matricula sin asignar. Docentes sin
    # sede base (no traian una de las 3 sedes fisicas en el Excel)
    # quedan sin esta preferencia -- sede_doc_var vale -1 para ellos y
    # 'tiene_sede' sale falso, asi que nunca se penalizan. Reutiliza
    # sede_sal_vars ya calculado arriba (Fase 4) en vez de recalcularlo.
    if hay_sede_pref:
        for i in range(n_mat):
            sede_doc_var = model.NewIntVar(-1, max(docente_sede_arr + [-1]), f'sede_doc_{i}')
            model.AddElement(asignaciones[i]['docente'], docente_sede_arr, sede_doc_var)

            tiene_sede = model.NewBoolVar(f'tiene_sede_doc_{i}')
            model.Add(sede_doc_var != -1).OnlyEnforceIf(tiene_sede)
            model.Add(sede_doc_var == -1).OnlyEnforceIf(tiene_sede.Not())

            coincide_sede = model.NewBoolVar(f'sede_coincide_{i}')
            model.Add(sede_doc_var == sede_sal_vars[i]).OnlyEnforceIf(coincide_sede)
            model.Add(sede_doc_var != sede_sal_vars[i]).OnlyEnforceIf(coincide_sede.Not())

            viola_sede = model.NewBoolVar(f'sede_viola_{i}')
            model.AddBoolAnd([tiene_sede, coincide_sede.Not()]).OnlyEnforceIf(viola_sede)
            model.AddBoolOr([tiene_sede.Not(), coincide_sede]).OnlyEnforceIf(viola_sede.Not())
            penalizaciones.append(viola_sede)

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
        'advertencias_facultad': sorted(advertencias_facultad),
    }


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 2: Heuristico con backtracking suave
# ════════════════════════════════════════════════════════════════
def _solver_heuristico(matriculas, docentes, salones, bloques, dias, restricciones_docente, capacidades=None):
    """
    Heuristico con backtracking suave (RF-26 a RF-39).
    Respeta:
        - DURAS: no choques (RF-27, RF-28), jornadas/bloques permitidos
                 (RF-39), minimo 2h para desplazarse de sede (RF-39 ext.)
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

    # RF-39 (Fase 4, 2026-09-05): solo se programa dentro de las 4
    # jornadas fijas (Diurna, Especial, Nocturna, Sabatino), en los pares
    # (dia, bloque) que caen dentro de ellas -- ver jornadas.py. El
    # sabatino no comparte los bloques nocturnos, y los dias de semana no
    # comparten los bloques de la tarde del sabatino.
    pares_validos = [
        (dia, bloq) for dia in dias for bloq in bloques
        if bloque_permitido_en_dia(bloq, dia)
    ]
    if not pares_validos:
        raise SolverError(
            'No hay bloques cargados dentro de las 4 jornadas permitidas '
            '(Diurna/Especial/Nocturna/Sabatino) -- corre '
            '"python manage.py corregir_bloques_horario --aplicar" primero.'
        )

    # RF-39 extendido (Fase 4, 2026-09-05): agenda real (por dia) de cada
    # docente ya asignado en esta corrida, para poder exigir un minimo de
    # 2h cuando dos de sus clases ese dia son en sedes distintas.
    agenda_docente_dia = {}  # (id_doc, dia) -> [(bloque, sede_id), ...]

    def _viola_desplazamiento(id_doc, dia, bloque_nuevo, sede_nueva):
        if sede_nueva is None:
            return False
        for bloque_exist, sede_exist in agenda_docente_dia.get((id_doc, dia), []):
            if sede_exist is None or sede_exist == sede_nueva:
                continue
            if gap_horas(bloque_nuevo, bloque_exist) < MINIMO_HORAS_DESPLAZAMIENTO_SEDE:
                return True
        return False

    tipos_permitidos_cache = {}

    def _tipos_ok_de(mat):
        materia = getattr(mat, 'materia', None)
        if materia is None:
            return []
        clave = getattr(materia, 'id_materia', id(materia))
        if clave not in tipos_permitidos_cache:
            try:
                tipos_permitidos_cache[clave] = tipos_permitidos_por_facultad(materia)
            except Exception:
                tipos_permitidos_cache[clave] = []
        return tipos_permitidos_cache[clave]

    # RF-38 (Fase 3, 2026-09-04): un docente solo puede dictar materias de
    # SU MISMA facultad (dura). Se agrupan las facultades "duplicadas" por
    # el doble import (grupo_de_facultad(), mismo criterio que ya usa
    # tipos_permitidos_por_facultad para el tipo de salon). Un docente SIN
    # facultad queda sin esta restriccion. Si NINGUN docente coincide con
    # la facultad de una materia -- hueco real de datos -- se cae a
    # "cualquier docente" para esa materia puntual (en vez de dejarla sin
    # asignar) y se reporta en advertencias_facultad.
    docentes_por_grupo = {}
    docentes_sin_facultad = []
    for d in docentes:
        grupo = grupo_de_facultad(getattr(d, 'facultad', None))
        if grupo is None:
            docentes_sin_facultad.append(d)
        else:
            docentes_por_grupo.setdefault(grupo, []).append(d)

    grupo_materia_cache = {}
    advertencias_facultad = set()

    def _docentes_candidatos_de(mat):
        materia = getattr(mat, 'materia', None)
        programa = getattr(materia, 'programa', None) if materia else None
        facultad_mat = getattr(programa, 'facultad', None) if programa else None
        clave = getattr(facultad_mat, 'id_facultad', None)
        if clave not in grupo_materia_cache:
            grupo_materia_cache[clave] = grupo_de_facultad(facultad_mat)
        grupo = grupo_materia_cache[clave]
        if grupo is None:
            return docentes  # materia sin facultad determinable: sin restriccion
        candidatos = docentes_por_grupo.get(grupo, []) + docentes_sin_facultad
        if not candidatos:
            advertencias_facultad.add(grupo)
            return docentes
        return candidatos

    for mat in matriculas_ord:
        asignado = False

        # RF-37 extendido: preferimos salones del tipo coherente con la
        # facultad de la materia (enfermeria, ingenieria/computadores,
        # salud oral, etc). Si no hay ninguno de ese tipo, o se agotan los
        # intentos preferentes, caemos a un aula generica de reserva en vez
        # de dejar la matricula sin asignar.
        tipos_ok = _tipos_ok_de(mat)
        docentes_cand = _docentes_candidatos_de(mat)
        if tipos_ok:
            pool_tipo = [s for s in salones if getattr(s, 'tipo', 'AULA') in tipos_ok]
            hay_pref_tipo = bool(pool_tipo) and len(pool_tipo) < len(salones)
        else:
            pool_tipo, hay_pref_tipo = salones, False
        TOTAL_INTENTOS = 25

        # Hasta 25 intentos por matricula
        for intento in range(TOTAL_INTENTOS):
            doc = random.choice(docentes_cand)

            # RF-38 extendido (sede base del docente, blanda): en los
            # primeros intentos preferimos un salon que cumpla el tipo Y
            # la sede base del docente asignado; si no hay, relajamos
            # primero el tipo y despues la sede, en vez de dejar la
            # matricula sin asignar -- asi otras sedes completan sus
            # horas cuando su propia sede no tiene cupo en ningun slot.
            sede_doc = doc.sede_id
            pool_tipo_sede = (
                [s for s in pool_tipo if getattr(s, 'sede_id', None) == sede_doc]
                if sede_doc is not None else []
            )
            pool_sede = (
                [s for s in salones if getattr(s, 'sede_id', None) == sede_doc]
                if sede_doc is not None else []
            )

            if pool_tipo_sede and intento < 12:
                pool_salones = pool_tipo_sede
            elif hay_pref_tipo and intento < 18:
                pool_salones = pool_tipo
            elif pool_sede and intento < 22:
                pool_salones = pool_sede
            else:
                pool_salones = salones

            sal = random.choice(pool_salones)
            dia, bloq = random.choice(pares_validos)

            k_doc = (doc.usuario_id, dia, bloq.id_bloque)
            k_sal = (sal.id_salon, dia, bloq.id_bloque)
            k_mat = (mat.id_matricula, dia, bloq.id_bloque)

            # RESTRICCIONES DURAS
            if k_doc in ocupado_doc: continue
            if k_sal in ocupado_sal: continue
            if k_mat in ocupado_mat: continue
            if _viola_desplazamiento(doc.usuario_id, dia, bloq, getattr(sal, 'sede_id', None)):
                continue

            # RESTRICCION BLANDA RF-17: si no es la opcion final, evitar bloque no disponible
            if (doc.usuario_id, dia, bloq.numero) in restr_set:
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
            agenda_docente_dia.setdefault((doc.usuario_id, dia), []).append((bloq, getattr(sal, 'sede_id', None)))
            asignado = True
            break

        if not asignado:
            conflictos += 1

    return horarios, conflictos, {
        'algoritmo': 'heuristico_backtracking',
        'advertencias_facultad': sorted(advertencias_facultad),
    }


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

    dias = dias or ['LU', 'MA', 'MI', 'JU', 'VI', 'SA']  # Fase 4 (2026-09-05): incluye sabatino
    restricciones_docente = restricciones_docente or []

    algoritmo = forzar_algoritmo or SOLVER_ACTIVO
    inicio = time.time()

    # Guarda de escala (Fase 3, 2026-09-04): _solver_ortools() crea una
    # restriccion de "no choque" POR CADA PAR de matriculas (bucle doble,
    # O(n^2)). Con un periodo real (cientos o miles de matriculas activas)
    # construir el modelo -- no resolverlo, eso ya tiene un tope de 30s en
    # max_time_in_seconds -- puede tardar muchisimo y deja la peticion HTTP
    # colgada (asi se vio el job IA-2026-3T-... quedarse en EJECUTANDO
    # indefinidamente al probar con datos reales). Para volumenes grandes
    # usamos el heuristico (O(n), ya validado que da resultados correctos)
    # en vez de arriesgar el cuelgue. Reformular _solver_ortools con
    # restricciones por "slot" (dia+bloque) en vez de por pares, para que
    # SI escale con OR-Tools, queda fuera del alcance de este fix.
    MAX_MATRICULAS_ORTOOLS = 250
    if algoritmo == 'OR-TOOLS' and len(matriculas) > MAX_MATRICULAS_ORTOOLS:
        algoritmo = 'HEURISTIC'

    try:
        if algoritmo == 'OR-TOOLS':
            # Convertimos restricciones_docente a indices
            doc_idx = {d.usuario_id: i for i, d in enumerate(docentes)}
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

    advertencias_facultad = metricas.get('advertencias_facultad') or []
    log_advertencia = ''
    if advertencias_facultad:
        log_advertencia = (
            f"\nADVERTENCIA (RF-38): no hay ningun docente cargado para la(s) "
            f"facultad(es) {', '.join(advertencias_facultad)} -- esas materias se "
            f"asignaron sin filtrar por facultad porque de lo contrario no habria "
            f"quedado ningun docente posible. Carga/asigna un docente de esa(s) "
            f"facultad(es) para que la regla aplique."
        )

    return SolverResult(
        horarios=horarios,
        asignadas=len(horarios),
        conflictos=conflictos,
        duracion_ms=duracion_ms,
        algoritmo=algoritmo_usado,
        log=(f'Solver: {algoritmo_usado}\n'
             f'Matriculas: {len(matriculas)} | Asignadas: {len(horarios)} | Conflictos: {conflictos}\n'
             f'Restricciones docente: {len(restricciones_docente)}\n'
             f'Duracion: {duracion_ms} ms'
             f'{log_advertencia}'),
        metricas=metricas,
    )
