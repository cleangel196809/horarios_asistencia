"""
Diagnostico de solo lectura (Fase 4b, 2026-09-05): "horario_bloques" es
una tabla del esquema compartido de la base de datos que NO tiene modelo
Django (no aparece en ningun apps/*/models.py) -- probablemente
pertenece a SISCA (la otra aplicacion que usa esta misma base de datos)
o es una tabla de un esquema anterior. Este comando SOLO LEE:

  1) Que columnas tiene esa tabla.
  2) Cuantas filas de esa tabla apuntan a un salon de las 3 sedes que
     se quieren borrar (id_sede 1, 2, 6), y una muestra de esas filas.
  3) Cuantas filas en TOTAL tiene la tabla (para saber si es una tabla
     grande/activa o si son solo estos datos de prueba/demo).

No borra ni modifica nada.

Uso:
    python manage.py inspeccionar_horario_bloques
"""
from django.core.management.base import BaseCommand
from django.db import connection

IDS_SEDES = [1, 2, 6]


class Command(BaseCommand):
    help = 'Inspecciona (solo lectura) la tabla huerfana horario_bloques y su relacion con salones.'

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            self.stdout.write(self.style.MIGRATE_HEADING('\n== Columnas de horario_bloques =='))
            cols = connection.introspection.get_table_description(cur, 'horario_bloques')
            nombres_col = [c.name for c in cols]
            for c in cols:
                self.stdout.write(f'  {c.name:20} {c.type_code}')

            self.stdout.write(self.style.MIGRATE_HEADING('\n== Total de filas en horario_bloques =='))
            cur.execute('SELECT COUNT(*) FROM horario_bloques')
            total = cur.fetchone()[0]
            self.stdout.write(f'  {total} fila(s) en total en toda la tabla')

            if 'salon_id' not in nombres_col:
                self.stdout.write(self.style.WARNING(
                    '\n  Esta tabla no tiene columna "salon_id" -- revisa el listado de columnas de arriba, '
                    'puede que la FK use otro nombre.'
                ))
                return

            self.stdout.write(self.style.MIGRATE_HEADING(
                '\n== Filas de horario_bloques que apuntan a salones de las sedes 1, 2, 6 =='
            ))
            cur.execute('''
                SELECT COUNT(*)
                FROM horario_bloques hb
                JOIN salones s ON s.id = hb.salon_id
                WHERE s.sede_id = ANY(%s)
            ''', [IDS_SEDES])
            afectadas = cur.fetchone()[0]
            self.stdout.write(f'  {afectadas} fila(s) de horario_bloques quedarian huerfanas si se borran esos salones')

            if afectadas:
                cur.execute('''
                    SELECT hb.*
                    FROM horario_bloques hb
                    JOIN salones s ON s.id = hb.salon_id
                    WHERE s.sede_id = ANY(%s)
                    LIMIT 10
                ''', [IDS_SEDES])
                muestra = cur.fetchall()
                self.stdout.write(self.style.MIGRATE_HEADING('\n  Muestra (hasta 10 filas):'))
                self.stdout.write('  ' + ' | '.join(nombres_col))
                for fila in muestra:
                    self.stdout.write('  ' + ' | '.join(str(v) for v in fila))

        self.stdout.write('')
