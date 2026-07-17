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
