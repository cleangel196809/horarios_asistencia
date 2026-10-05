"""
SIIHAPI · Helper de esquemas de PostgreSQL (modularización, 2026-10-05).

Los módulos nuevos no escriben en `public` (donde ya conviven SIIHAPI,
planeación y las tablas `managed=False` compartidas): cada uno vive en su
propio esquema de la MISMA base — `aula_virtual`, `evaluacion_docente` —
para que dos migraciones corriendo en paralelo nunca compitan por el mismo
namespace de tablas.

Django soporta el esquema directamente en `db_table` cuando el valor viene
entrecomillado (`'"aula_virtual"."canales"'`): `quote_name()` lo deja tal
cual y el SQL sale con el esquema calificado. El problema es que ese mismo
valor en SQLite (la base que usa `siihapi.settings_test_sqlite` para correr
la suite sin Postgres) se interpreta como `base.tabla` y falla con "unknown
database aula_virtual".

Por eso la calificación se decide en tiempo de importación del modelo según
el motor configurado:

    class Meta:
        db_table = tabla('aula_virtual', 'canales')

    · PostgreSQL → '"aula_virtual"."canales"'   (esquema real)
    · cualquier otro motor → 'aula_virtual_canales'  (tabla plana, tests)

Los nombres quedan igual de únicos en los dos casos, así que ningún test
depende de en qué motor corre.
"""
from django.conf import settings


def tabla(esquema: str, nombre: str) -> str:
    """Nombre de tabla calificado por esquema en Postgres, plano en el resto."""
    engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
    if 'postgresql' in engine or 'postgis' in engine:
        return f'"{esquema}"."{nombre}"'
    return f'{esquema}_{nombre}'
