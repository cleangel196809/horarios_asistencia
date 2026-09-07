"""
SIIHAPI - Corrige el catalogo de Bloques Horarios (bloques_horario) para
que coincida con las jornadas REALES del Politecnico, en vez del esquema
generico de 14 bloques de 80 minutos (6:00 a 22:00) con el que se penso
originalmente el modelo (ver docstring de Bloque en apps/horarios/models.py).

Jornadas reales (segun el usuario, 2026-09-04), cada sesion de 1 hora y
30 minutos (90 minutos):
    DIURNA    lunes a viernes  07:00 - 10:00  -> 2 bloques de 90 min
    ESPECIAL  lunes a viernes  10:00 - 13:00  -> 2 bloques de 90 min
    TARDE     lunes a viernes  14:00 - 17:00  -> 2 bloques de 90 min
    NOCHE     lunes a viernes  18:00 - 21:00  -> 2 bloques de 90 min
    SABATINA  sabado           07:00 - 13:00  -> 4 bloques de 90 min
    SABATINA  sabado           14:00 - 17:00  -> 2 bloques de 90 min

Bloque (bloques_horario) NO tiene columna de dia -- el dia vive en Horario
y en DisponibilidadDocente, cada uno con su propio campo `dia`. Por eso
los horarios de sabado NO necesitan bloques propios: sus dos ventanas
(07:00-13:00 y 14:00-17:00) caen EXACTO sobre los mismos bloques que ya
usan diurna+especial (07:00-13:00) y tarde (14:00-17:00) entre semana.
En total, la jornada institucional completa se cubre con solo 8 bloques
unicos:

    1) 07:00-08:30   5) 14:00-15:30
    2) 08:30-10:00   6) 15:30-17:00
    3) 10:00-11:30   7) 18:00-19:30
    4) 11:30-13:00   8) 19:30-21:00

Por que UPDATE en vez de borrar y crear de nuevo
--------------------------------------------------
`Horario.bloque` y `DisponibilidadDocente.bloque` son FK reales a
`bloques_horario(id)` (no al numero suelto) -- por eso este comando NUNCA
borra un Bloque existente: actualiza su hora_inicio/hora_fin/numero en su
propia fila, conservando el mismo id. Así cualquier Horario o
DisponibilidadDocente que ya apunte a ese bloque queda automáticamente
con el horario corregido, sin quedar huérfano ni perder la relación.

Como managed=False, Django jamas creo/alterara esta tabla por migracion:
todo el trabajo aqui es UPDATE/INSERT normal via el ORM (permitido sobre
tablas no administradas), no DDL.

SIEMPRE corre primero en modo diagnostico (sin --aplicar): compara lo que
hay contra lo que deberia haber y no cambia nada. Con --aplicar aplica los
cambios dentro de una transaccion (todo o nada).

Uso:
    python manage.py corregir_bloques_horario                # diagnostico
    python manage.py corregir_bloques_horario --aplicar       # aplica

Fase 3 (2026-09-04).
"""
from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.horarios.models import Bloque

# (numero, hora_inicio, hora_fin, etiqueta de jornada solo para el log)
BLOQUES_OBJETIVO = [
    (1, time(7, 0),  time(8, 30),  'Diurna 1/2 · Sabatina 1/4'),
    (2, time(8, 30), time(10, 0),  'Diurna 2/2 · Sabatina 2/4'),
    (3, time(10, 0), time(11, 30), 'Especial 1/2 · Sabatina 3/4'),
    (4, time(11, 30), time(13, 0), 'Especial 2/2 · Sabatina 4/4'),
    (5, time(14, 0), time(15, 30), 'Tarde 1/2 · Sabatina tarde 1/2'),
    (6, time(15, 30), time(17, 0), 'Tarde 2/2 · Sabatina tarde 2/2'),
    (7, time(18, 0), time(19, 30), 'Noche 1/2'),
    (8, time(19, 30), time(21, 0), 'Noche 2/2'),
]


class Command(BaseCommand):
    help = 'Corrige bloques_horario para que coincida con las jornadas reales (diurna/especial/tarde/noche/sabatina, sesiones de 90 min).'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Aplica los cambios (por defecto solo diagnostica)')

    def handle(self, *args, **opts):
        aplicar = opts['aplicar']

        existentes = list(Bloque.objects.order_by('hora_inicio', 'numero'))

        self.stdout.write(self.style.MIGRATE_HEADING('\n== Bloques actuales en la base de datos =='))
        if existentes:
            for b in existentes:
                self.stdout.write(f'  #{b.numero:<3} {b.hora_inicio:%H:%M} - {b.hora_fin:%H:%M}  (id={b.id_bloque})')
        else:
            self.stdout.write('  (ninguno)')

        self.stdout.write(self.style.MIGRATE_HEADING('\n== Bloques objetivo (jornadas reales, sesiones de 90 min) =='))
        for numero, hi, hf, etiqueta in BLOQUES_OBJETIVO:
            self.stdout.write(f'  #{numero}   {hi:%H:%M} - {hf:%H:%M}   [{etiqueta}]')

        # Empareja cada bloque objetivo con un bloque existente reutilizable:
        # 1) match exacto por horario ya correcto -> no se toca
        # 2) si no, se reutiliza el existente "libre" mas cercano en el tiempo
        # 3) si no queda ninguno libre, se creara uno nuevo
        libres = list(existentes)
        plan = []  # (accion, objetivo, bloque_existente_o_None)
        for numero, hi, hf, etiqueta in BLOQUES_OBJETIVO:
            exacto = next((b for b in libres if b.hora_inicio == hi and b.hora_fin == hf), None)
            if exacto:
                libres.remove(exacto)
                accion = 'sin_cambio' if exacto.numero == numero else 'renumerar'
                plan.append((accion, (numero, hi, hf, etiqueta), exacto))
                continue
            if libres:
                # el mas cercano por hora_inicio
                candidato = min(libres, key=lambda b: abs(
                    (b.hora_inicio.hour * 60 + b.hora_inicio.minute) - (hi.hour * 60 + hi.minute)
                ))
                libres.remove(candidato)
                plan.append(('actualizar', (numero, hi, hf, etiqueta), candidato))
            else:
                plan.append(('crear', (numero, hi, hf, etiqueta), None))

        sobrantes = libres  # bloques existentes que no se van a usar ni tocar

        self.stdout.write(self.style.MIGRATE_HEADING('\n== Plan de cambios =='))
        n_sin_cambio = n_actualizar = n_crear = 0
        for accion, (numero, hi, hf, etiqueta), existente in plan:
            if accion == 'sin_cambio':
                n_sin_cambio += 1
                self.stdout.write(f'  = #{numero} {hi:%H:%M}-{hf:%H:%M} ya esta correcto (id={existente.id_bloque})')
            elif accion == 'renumerar':
                n_actualizar += 1
                self.stdout.write(self.style.WARNING(
                    f'  ~ id={existente.id_bloque}: horario ya correcto ({hi:%H:%M}-{hf:%H:%M}) pero '
                    f'numero {existente.numero} -> {numero}'
                ))
            elif accion == 'actualizar':
                n_actualizar += 1
                self.stdout.write(self.style.WARNING(
                    f'  ~ id={existente.id_bloque}: #{existente.numero} {existente.hora_inicio:%H:%M}-'
                    f'{existente.hora_fin:%H:%M}  ->  #{numero} {hi:%H:%M}-{hf:%H:%M}  [{etiqueta}]'
                ))
            else:
                n_crear += 1
                self.stdout.write(self.style.WARNING(f'  + crear #{numero} {hi:%H:%M}-{hf:%H:%M}  [{etiqueta}]'))

        if sobrantes:
            self.stdout.write(self.style.ERROR(
                f'\n  OJO: {len(sobrantes)} bloque(s) existente(s) NO corresponden a ninguna jornada nueva y '
                f'NO se van a tocar ni a borrar (podrían estar en uso en otro contexto -- revísalos a mano):'
            ))
            for b in sobrantes:
                self.stdout.write(f'    - id={b.id_bloque} #{b.numero} {b.hora_inicio:%H:%M}-{b.hora_fin:%H:%M}')

        if not aplicar:
            self.stdout.write(self.style.SUCCESS(
                f'\n[Solo diagnóstico] {n_sin_cambio} sin cambio, {n_actualizar} para actualizar, '
                f'{n_crear} para crear. Nada se modificó. Corre con --aplicar para aplicar este plan.'
            ))
            return

        with transaction.atomic():
            # Paso 1: a los que hay que renumerar/actualizar, primero ponerles
            # un numero temporal negativo para no chocar con la restriccion
            # UNIQUE de `numero` mientras se reordenan.
            a_tocar = [(obj, existente) for accion, obj, existente in plan
                       if accion in ('renumerar', 'actualizar') and existente is not None]
            for i, (_, existente) in enumerate(a_tocar, start=1):
                existente.numero = -i
                existente.save(update_fields=['numero'])

            # Paso 2: asignar horario y numero definitivos.
            for accion, (numero, hi, hf, etiqueta), existente in plan:
                if accion in ('renumerar', 'actualizar'):
                    existente.numero = numero
                    existente.hora_inicio = hi
                    existente.hora_fin = hf
                    existente.save(update_fields=['numero', 'hora_inicio', 'hora_fin'])
                elif accion == 'crear':
                    Bloque.objects.create(numero=numero, hora_inicio=hi, hora_fin=hf)

        self.stdout.write(self.style.SUCCESS(
            f'\nAplicado: {n_sin_cambio} sin cambio, {n_actualizar} actualizado(s), {n_crear} creado(s). '
            f'Los Horario y DisponibilidadDocente que ya apuntaban a un bloque actualizado quedan '
            f'automáticamente con el horario corregido (se conservó el mismo id_bloque).'
        ))
        if sobrantes:
            self.stdout.write(self.style.WARNING(
                f'Quedaron {len(sobrantes)} bloque(s) sin usar sin tocar -- revísalos a mano si ya no aplican.'
            ))
