"""
Diagnostico de solo lectura (Fase 4c, 2026-09-05): mapea TODA la cadena
de tablas que dependen (via llave foranea) de los salones de las sedes
1, 2 y 6, sin importar si tienen modelo Django o no. Se hizo necesario
porque cada intento de borrado encontraba una tabla huerfana nueva
bloqueando el paso anterior:

    salones <- horario_bloques <- sesiones_clase <- (?)

En vez de seguir descubriendo una tabla a la vez con cada error, este
comando recorre pg_constraint (el catalogo de Postgres) para encontrar
TODAS las tablas que referencian, directa o indirectamente, a salones,
y cuenta cuantas filas de cada una quedarian huerfanas -- hasta 6
niveles de profundidad. No borra ni modifica nada.

Uso:
    python manage.py mapa_dependencias_salones
"""
from django.core.management.base import BaseCommand
from django.db import connection

IDS_SEDES = [1, 2, 6]
MAX_PROFUNDIDAD = 6


def _hijos_de(cur, tabla):
    """Devuelve [(tabla_hija, columna_hija, columna_padre_referenciada)]
    para toda FK de Postgres cuyo destino (confrelid) sea `tabla`."""
    cur.execute('''
        SELECT
            hijo.relname AS tabla_hija,
            col_hija.attname AS columna_hija,
            col_padre.attname AS columna_padre
        FROM pg_constraint con
        JOIN pg_class hijo ON hijo.oid = con.conrelid
        JOIN pg_class padre ON padre.oid = con.confrelid
        JOIN unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ord) ON true
        JOIN unnest(con.confkey) WITH ORDINALITY AS pk(attnum, ord) ON pk.ord = ck.ord
        JOIN pg_attribute col_hija ON col_hija.attrelid = hijo.oid AND col_hija.attnum = ck.attnum
        JOIN pg_attribute col_padre ON col_padre.attrelid = padre.oid AND col_padre.attnum = pk.attnum
        WHERE con.contype = 'f' AND padre.relname = %s
    ''', [tabla])
    return cur.fetchall()


def _pk_de(cur, tabla):
    """Nombre de la columna PK de `tabla` (asume PK de una sola columna).
    Usa relname en vez de un cast ::regclass porque algunas tablas (ej.
    SIIHAPI_HORARIO) tienen mayusculas en el nombre -- el cast a regclass
    las pasa a minusculas y ya no encuentra la tabla."""
    cur.execute('''
        SELECT a.attname
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
        WHERE con.contype = 'p' AND c.relname = %s
        LIMIT 1
    ''', [tabla])
    row = cur.fetchone()
    return row[0] if row else 'id'


class Command(BaseCommand):
    help = 'Mapea (solo lectura) toda la cadena de tablas que dependen de los salones de las sedes 1, 2 y 6.'

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            cur.execute('SELECT id FROM salones WHERE sede_id = ANY(%s)', [IDS_SEDES])
            ids_raiz = [r[0] for r in cur.fetchall()]
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'\n== Raiz: salones de las sedes 1, 2, 6 -> {len(ids_raiz)} salon(es) =='
            ))

            nivel = [('salones', ids_raiz)]
            visitadas = {'salones'}
            profundidad = 0

            while nivel and profundidad < MAX_PROFUNDIDAD:
                profundidad += 1
                siguiente_nivel = []
                for tabla, ids in nivel:
                    if not ids:
                        continue
                    hijos = _hijos_de(cur, tabla)
                    for tabla_hija, col_hija, col_padre in hijos:
                        cur.execute(
                            f'SELECT COUNT(*) FROM "{tabla_hija}" WHERE "{col_hija}" = ANY(%s)',
                            [ids],
                        )
                        n = cur.fetchone()[0]
                        etiqueta = ' (YA VISITADA -- posible ciclo, no se sigue)' if tabla_hija in visitadas else ''
                        self.stdout.write(
                            f'  [{profundidad}] {tabla}.{col_padre}  <-  {tabla_hija}.{col_hija}: {n} fila(s){etiqueta}'
                        )
                        if n and tabla_hija not in visitadas:
                            visitadas.add(tabla_hija)
                            pk_hija = _pk_de(cur, tabla_hija)
                            cur.execute(
                                f'SELECT "{pk_hija}" FROM "{tabla_hija}" WHERE "{col_hija}" = ANY(%s)',
                                [ids],
                            )
                            ids_hija = [r[0] for r in cur.fetchall()]
                            siguiente_nivel.append((tabla_hija, ids_hija))
                nivel = siguiente_nivel

            if profundidad >= MAX_PROFUNDIDAD and nivel:
                self.stdout.write(self.style.WARNING(
                    f'\n(se detuvo en {MAX_PROFUNDIDAD} niveles de profundidad -- puede haber mas)'
                ))

        self.stdout.write(self.style.SUCCESS('\nListo. Ninguna fila fue borrada ni modificada.'))
