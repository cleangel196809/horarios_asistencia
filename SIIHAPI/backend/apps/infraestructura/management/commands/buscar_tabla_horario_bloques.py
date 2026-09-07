"""
Diagnostico (Fase 4b, 2026-09-05): encuentra que modelo de Django
corresponde a la tabla "horario_bloques" -- la que bloqueo el borrado de
salones con el error:

    IntegrityError: update o delete en <<salones>> viola la llave
    foranea <<horario_bloques_salon_id_fkey>> en la tabla
    <<horario_bloques>>

Esa tabla NO es el modelo Horario (su tabla real es SIIHAPI_HORARIO,
segun apps/horarios/models.py) -- es otra tabla del esquema compartido
que tambien apunta a salones.id. Este comando no toca la base de datos,
solo recorre los modelos ya registrados en Django e imprime cual de
ellos usa esa tabla, y cuales de sus campos son ForeignKey hacia Salon.

No requiere conexion a la base de datos.

Uso:
    python manage.py buscar_tabla_horario_bloques
"""
from django.apps import apps
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Busca en todos los modelos registrados cual usa la tabla "horario_bloques" (diagnostico, no toca la BD).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Buscando modelo(s) con db_table = horario_bloques =='))
        encontrado = False
        for model in apps.get_models():
            tabla = model._meta.db_table
            if tabla.lower() == 'horario_bloques':
                encontrado = True
                self.stdout.write(self.style.SUCCESS(
                    f'\n  Modelo: {model._meta.app_label}.{model.__name__}  (tabla: {tabla})'
                ))
                for f in model._meta.get_fields():
                    if f.is_relation and getattr(f, 'many_to_one', False):
                        destino = f.related_model._meta.label if f.related_model else '?'
                        self.stdout.write(f'      campo FK: {f.name}  -> {destino}')
        if not encontrado:
            self.stdout.write(self.style.WARNING(
                '\n  Ningun modelo registrado en Django usa esa tabla -- es una tabla "huerfana" '
                '(probablemente de SISCA o de un esquema anterior) que no tiene modelo Django. '
                'Para poder borrarla seria necesario hacerlo con SQL directo, no con el ORM.'
            ))

        self.stdout.write(self.style.MIGRATE_HEADING('\n== Todas las tablas que referencian infraestructura_salon/salones =='))
        for model in apps.get_models():
            for f in model._meta.get_fields():
                if f.is_relation and getattr(f, 'many_to_one', False) and f.related_model:
                    if f.related_model.__name__ == 'Salon':
                        self.stdout.write(
                            f'  {model._meta.app_label}.{model.__name__} (tabla: {model._meta.db_table})  '
                            f'campo: {f.name}'
                        )
        self.stdout.write('')
