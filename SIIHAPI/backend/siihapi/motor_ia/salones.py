"""
Fase 1 — Restricciones de salón para la asignación de horarios.
Reglas: tipo de salón segun la materia, capacidad, sede y programas virtuales.
"""

# Palabras clave en el nombre de la materia -> tipo de salón requerido
_KEYWORDS_TIPO = [
    (('cocina', 'culinari', 'gastronom'),        ('COCINA', 'GOURMET')),
    (('reposter', 'panaderi'),                   ('REPOSTERIA', 'COCINA')),
    (('bar', 'cocteler', 'mesa'),                ('MESA_BAR', 'CATA')),
    (('enfermer', 'clinic', 'cuidado'),          ('LAB_ENF', 'LAB_SALUD')),
    (('salud', 'anatom', 'morfofisio', 'farmac'),('LAB_SALUD', 'LAB_ENF')),
    (('sistema', 'programa', 'software', 'redes', 'base de dato', 'aplicacion', 'web', 'computo', 'informatic'),
                                                 ('LAB_SIST',)),
    (('ceramic',),                               ('CERAMICA',)),
    (('yeso',),                                  ('YESOS',)),
    (('metalurg',),                              ('METALURGIA',)),
    (('colado',),                                ('COLADOS',)),
    (('acrilic',),                               ('ACRILICOS',)),
    (('ortodonc', 'dental', 'odontolog'),        ('ORTODONCIA',)),
    (('motor', 'mecanic', 'automotr'),           ('MOTORES',)),
    (('deport', 'fisic', 'gimnas'),              ('GIMNASIO',)),
]


def tipos_requeridos(materia_nombre: str, requiere_sistemas: bool = False):
    """Devuelve la lista de tipos de salón aptos para la materia (vacío = cualquiera/AULA)."""
    nom = (materia_nombre or '').lower()
    if requiere_sistemas:
        return ['LAB_SIST']
    for claves, tipos in _KEYWORDS_TIPO:
        if any(k in nom for k in claves):
            return list(tipos)
    return []  # sin requisito especial -> aula comun


def salon_apto(salon_tipo: str, materia_nombre: str, requiere_sistemas: bool = False) -> bool:
    req = tipos_requeridos(materia_nombre, requiere_sistemas)
    if not req:
        return True  # cualquier salón sirve para materia teórica
    return salon_tipo in req


def es_programa_virtual(modalidad: str, tipo_programa: str = '') -> bool:
    """True si el programa es virtual (no ocupa salón físico)."""
    return (modalidad or '').upper() == 'VIRT' or (tipo_programa or '').upper() == 'VIRT'


def elegir_salon(materia, salones, ocupados, dia, bloque_id, n_estudiantes=1):
    """Elige el primer salón APTO (tipo correcto + capacidad) y libre en (dia,bloque).
    `salones`: lista de objetos Salon. `ocupados`: set de (dia, bloque_id, salon_id).
    Devuelve un Salon o None."""
    nombre = getattr(materia, 'nombre', '')
    req_sis = bool(getattr(materia, 'requiere_sala_sistemas', False))
    # 1) salones del tipo correcto con capacidad suficiente
    aptos = [s for s in salones
             if salon_apto(getattr(s, 'tipo', 'AULA'), nombre, req_sis)
             and getattr(s, 'capacidad', 0) >= n_estudiantes]
    # 2) si ninguno por capacidad, relajar capacidad pero mantener tipo
    if not aptos:
        aptos = [s for s in salones if salon_apto(getattr(s, 'tipo', 'AULA'), nombre, req_sis)]
    # 3) último recurso: cualquier salón
    if not aptos:
        aptos = list(salones)
    for s in aptos:
        if (dia, bloque_id, s.id_salon) not in ocupados:
            return s
    return None


# ════════════════════════════════════════════════════════════
#  Fase 3 (2026-09-04) -- RF-37 extendido: tipo de salon segun la
#  FACULTAD del programa de la materia (no del docente: Docente no
#  tiene facultad en este esquema, solo 'especialidades' M2M sin FK
#  a Facultad). Requisitos confirmados con el usuario:
#    - Enfermeria y salud oral -> salones de enfermeria/salud.
#    - Ingenieria y sistemas   -> sala de sistemas (LAB_SIST).
#    - Si la materia exige computadores (requiere_sala_sistemas)  ->
#      LAB_SIST SIEMPRE, sin importar la facultad (manda por encima
#      de cualquier otra regla).
#    - Emprendimiento, Idiomas, Administracion, Educacion -> sin
#      restriccion (aulas genericas / transversales).
#    - Hospitalidad -> sin regla propia de facultad; se reutilizan
#      las palabras clave de tipos_requeridos() sobre el nombre de
#      la materia (cocina/reposteria/bar), igual que hoy.
#  Fallback general: si no hay salon libre del tipo requerido en el
#  slot (dia+bloque), se usa un aula generica de reserva en vez de
#  dejar la materia sin asignar (ver _solver_heuristico en solver.py).
# ════════════════════════════════════════════════════════════════
import unicodedata as _unicodedata


def _norm_facultad(texto: str) -> str:
    """Normaliza nombre/codigo de facultad: mayusculas, sin acentos/espacios extra."""
    txt = (texto or '').strip().upper()
    txt = _unicodedata.normalize('NFKD', txt)
    return ''.join(c for c in txt if not _unicodedata.combining(c))


# Los dos "generos" de nombre que coexisten en la BD real para la MISMA
# facultad conceptual (import antiguo en mayusculas + import nuevo con
# nombre completo) se fusionan en un solo grupo, tal como confirmo el
# usuario ("Si, fusionar cada par").
_GRUPO_ENFERMERIA = {'ENFERMERIA', 'FACULTAD DE SALUD'}
_GRUPO_INGENIERIA = {'INGENIERIA', 'FACULTAD DE INGENIERIA Y SISTEMAS'}
_GRUPO_GENERICO = {
    'EMPRENDIMIENTO',
    'IDIOMAS',
    'FACULTAD DE ADMINISTRACION',
    'FACULTAD DE EDUCACION',
}

# Dentro de la facultad mixta "SALUD" (codigo/nombre corto), solo los
# programas de salud oral / mecanica dental van a salones ORTODONCIA;
# el resto (Seguridad en el Trabajo, Primera Infancia, etc.) queda
# generico -- confirmado con el usuario ("Separar por programa").
_PROGRAMAS_SALUD_ORAL = {'362', '421', '422'}


def grupo_de_facultad(facultad):
    """Identificador de 'grupo' de facultad que fusiona los pares de import
    duplicados de la BD real (mismo criterio de _GRUPO_ENFERMERIA /
    _GRUPO_INGENIERIA que ya usa tipos_permitidos_por_facultad), para poder
    comparar si dos facultades son la misma area academica aunque sean
    filas distintas (codigo/nombre distinto) en la tabla facultades.
    None si no se puede determinar (facultad ausente).

    Fase 3 (2026-09-04) -- RF-38: se reutiliza para la regla "un docente
    solo dicta materias de su propia facultad" (ver motor_ia/solver.py),
    asi un docente con facultad FSA/ENF_R y una materia de programa
    ING_R/FIS cuentan correctamente como la misma area cuando aplica."""
    if facultad is None:
        return None
    cod_fac = _norm_facultad(getattr(facultad, 'codigo', ''))
    nom_fac = _norm_facultad(getattr(facultad, 'nombre', ''))
    if cod_fac in _GRUPO_ENFERMERIA or nom_fac in _GRUPO_ENFERMERIA:
        return 'ENFERMERIA'
    if cod_fac in _GRUPO_INGENIERIA or nom_fac in _GRUPO_INGENIERIA:
        return 'INGENIERIA'
    # Cualquier otra facultad (SALUD sola, EMPRENDIMIENTO, IDIOMAS,
    # HOSPITALIDAD, CVC, INVESTIGACION, FAD, FED, etc.): su propio codigo
    # normalizado es su grupo -- no se fusiona con nada mas.
    return cod_fac or nom_fac or None


def tipos_permitidos_por_facultad(materia):
    """Tipos de Salon.tipo aceptables para `materia` segun la facultad de
    su programa. Lista vacia = sin restriccion (cualquier salon sirve).

    El requisito de computadores (requiere_sala_sistemas) tiene prioridad
    absoluta sobre la regla de facultad, para CUALQUIER carrera."""
    if getattr(materia, 'requiere_sala_sistemas', False):
        return ['LAB_SIST']

    programa = getattr(materia, 'programa', None)
    if programa is None:
        return []
    facultad = getattr(programa, 'facultad', None)
    if facultad is None:
        return []

    cod_fac = _norm_facultad(getattr(facultad, 'codigo', ''))
    nom_fac = _norm_facultad(getattr(facultad, 'nombre', ''))
    cod_prog = str(getattr(programa, 'codigo', '') or '').strip()

    if cod_fac in _GRUPO_ENFERMERIA or nom_fac in _GRUPO_ENFERMERIA:
        return ['LAB_ENF', 'LAB_SALUD']

    if cod_fac in _GRUPO_INGENIERIA or nom_fac in _GRUPO_INGENIERIA:
        return ['LAB_SIST']

    if cod_fac == 'SALUD' or nom_fac == 'SALUD':
        if cod_prog in _PROGRAMAS_SALUD_ORAL:
            return ['ORTODONCIA']
        return []  # otros programas de la facultad SALUD -> generico

    if cod_fac in _GRUPO_GENERICO or nom_fac in _GRUPO_GENERICO:
        return []

    if cod_fac == 'HOSPITALIDAD' or nom_fac == 'HOSPITALIDAD':
        # Sin regla propia: reutilizamos las palabras clave ya existentes
        # sobre el nombre de la materia, con fallback a generico.
        return tipos_requeridos(getattr(materia, 'nombre', ''))

    # Facultad no reconocida / nueva -> nunca bloquear, sin restriccion.
    return []
