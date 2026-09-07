"""
SIIHAPI - Motor IA: jornadas y bloques horarios permitidos (Fase 4, 2026-09-05).

RF-39: a partir de esta fase el Motor IA SOLO programa clases dentro de 4
jornadas fijas, en bloques de 1:30h (90 min), para que las horas de cada
materia se completen en un numero entero de bloques segun sus creditos:

    Diurna    07:00 - 10:00   (2 bloques)  -- Lunes a Viernes y Sabado
    Especial  10:00 - 13:00   (2 bloques)  -- Lunes a Viernes y Sabado
    Noche     18:00 - 21:00   (2 bloques)  -- SOLO Lunes a Viernes
    Sabatino  07:00 - 17:00                -- SOLO Sabado: reutiliza los
              mismos bloques de Diurna+Especial (07:00-13:00) y suma 2
              bloques mas en la tarde (14:00-15:30 y 15:30-17:00), tras
              un almuerzo de 13:00 a 14:00.

Confirmado con el usuario (2026-09-05): NO existe jornada "Tarde" entre
semana -- el tramo 14:00-17:00 es EXCLUSIVO del sabatino. (Una version
anterior del catalogo de bloques, ver corregir_bloques_horario.py,
contemplaba tambien una jornada Tarde L-V; se descarto por esta
decision.)

Los bloques de 1:30h de este esquema ya deberian existir en la tabla
bloques_horario -- se cargan/corrigen con:

    python manage.py corregir_bloques_horario           # diagnostico
    python manage.py corregir_bloques_horario --aplicar # aplica

Ese comando actualiza los bloques EN SU MISMO id (no borra ni crea
duplicados), asi que cualquier Horario o DisponibilidadDocente que ya
apuntara a un bloque del esquema anterior (14 bloques de 80 min,
6:00-22:00) queda automaticamente con el horario correcto. Los bloques
"sobrantes" que ese comando no reasigna simplemente dejan de usarse aqui
(bloques_validos_para_ia los filtra), sin necesidad de borrarlos.
"""
from datetime import date, datetime, time

# ---- Bloques de 1:30h de cada jornada -------------------------------
BLOQUE_DIURNA_1   = (time(7, 0),  time(8, 30))
BLOQUE_DIURNA_2   = (time(8, 30), time(10, 0))
BLOQUE_ESPECIAL_1 = (time(10, 0), time(11, 30))
BLOQUE_ESPECIAL_2 = (time(11, 30), time(13, 0))
BLOQUE_NOCTURNA_1 = (time(18, 0), time(19, 30))
BLOQUE_NOCTURNA_2 = (time(19, 30), time(21, 0))
BLOQUE_SABATINO_1 = (time(14, 0), time(15, 30))
BLOQUE_SABATINO_2 = (time(15, 30), time(17, 0))

# Bloques permitidos por dia. El sabatino NO incluye Noche (termina a las
# 17:00); los dias de semana NO incluyen los bloques de la tarde
# (14:00-17:00 es EXCLUSIVO del sabado, confirmado 2026-09-05).
HORARIOS_LUNES_VIERNES = {
    BLOQUE_DIURNA_1, BLOQUE_DIURNA_2,
    BLOQUE_ESPECIAL_1, BLOQUE_ESPECIAL_2,
    BLOQUE_NOCTURNA_1, BLOQUE_NOCTURNA_2,
}
HORARIOS_SABADO = {
    BLOQUE_DIURNA_1, BLOQUE_DIURNA_2,
    BLOQUE_ESPECIAL_1, BLOQUE_ESPECIAL_2,
    BLOQUE_SABATINO_1, BLOQUE_SABATINO_2,
}
TODOS_LOS_BLOQUES_PERMITIDOS = HORARIOS_LUNES_VIERNES | HORARIOS_SABADO

# Minimo de horas de descanso que necesita un docente para desplazarse de
# una sede a otra el mismo dia (regla nueva, DURA -- confirmada con el
# usuario 2026-09-05: si no se puede cumplir, la materia queda sin
# asignar en vez de violar la regla).
MINIMO_HORAS_DESPLAZAMIENTO_SEDE = 2.0


def bloque_permitido_en_dia(bloque, dia_cod):
    """True si el (hora_inicio, hora_fin) de `bloque` cae dentro de
    alguna jornada permitida para el dia `dia_cod` ('LU'..'SA')."""
    par = (bloque.hora_inicio, bloque.hora_fin)
    permitidos = HORARIOS_SABADO if dia_cod == 'SA' else HORARIOS_LUNES_VIERNES
    return par in permitidos


def bloques_validos_para_ia(bloques):
    """Filtra una lista de Bloque a los que pertenecen a alguna jornada
    permitida (en cualquier dia). Bloques de esquemas anteriores que no
    calzan con ninguna jornada quedan excluidos automaticamente, sin
    necesidad de borrarlos de la base de datos."""
    return [b for b in bloques if (b.hora_inicio, b.hora_fin) in TODOS_LOS_BLOQUES_PERMITIDOS]


def gap_horas(bloque_a, bloque_b):
    """Horas reales de diferencia entre dos bloques del MISMO dia (no
    importa el orden). 0.0 si se solapan (no deberia pasar, ya lo evita
    la regla de choques del docente)."""
    hoy = date(2000, 1, 1)
    ini_a = datetime.combine(hoy, bloque_a.hora_inicio)
    fin_a = datetime.combine(hoy, bloque_a.hora_fin)
    ini_b = datetime.combine(hoy, bloque_b.hora_inicio)
    fin_b = datetime.combine(hoy, bloque_b.hora_fin)
    if fin_a <= ini_b:
        return (ini_b - fin_a).total_seconds() / 3600
    if fin_b <= ini_a:
        return (ini_a - fin_b).total_seconds() / 3600
    return 0.0
