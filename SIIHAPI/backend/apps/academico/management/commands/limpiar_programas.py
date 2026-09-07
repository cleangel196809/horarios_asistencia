"""
SIIHAPI - Diagnostico y limpieza del catalogo de Programas.

Por que existe: el modulo Admin > "Programas y Materias" mostraba los 4
tiles de tipo (Tecnico Laboral / Profesional / Tecnologia / Curso de
Ingles) siempre en 0, aunque la tabla de abajo sí trae filas -- porque en
la tabla 'programas' hay filas con el campo `tipo` guardado como texto
libre ("INGLES", "PROFESIONAL", "TECNOLOGIA", ...) en vez del código que
Django espera (ING/PROF/TEC/TL). get_tipo_display() no reconoce esos
valores y los muestra tal cual; el conteo por tipo (que sí filtra por
código) los ignora por completo.

Además hay programas que no tienen ninguna Materia ni ningún Estudiante
asociado -- probablemente entradas duplicadas/placeholder del catálogo
original, no programas reales en uso.

Este comando SIEMPRE corre en modo diagnóstico (solo imprime lo que
encuentra). Con --aplicar, además:
  1. Normaliza los valores de `tipo` reconocidos a su código canónico.
  2. Desactiva (activo=False, NO borra) los programas sin ninguna Materia
     ni ningún Estudiante asociado -- incluye los de tipo "profesional"
     detectados como huérfanos.

No se hace DELETE de ningún Programa: `Materia.programa` y
`Estudiante.programa` usan on_delete=PROTECT, así que un programa con
datos reales no se puede borrar de todos modos: solo se desactiva lo que
está realmente huérfano, siguiendo el mismo criterio no-destructivo que
se usó para limpiar 'sedes'.

Uso:
    python manage.py limpiar_programas                 # solo diagnóstico
    python manage.py limpiar_programas --aplicar        # aplica los cambios

Fase 3 (2026-09-04).
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from apps.academico.models import Programa

# Variantes de texto libre -> código canónico de Programa.TIPO_CHOICES.
# Solo se tocan estas variantes conocidas; cualquier otro valor raro se
# reporta pero se deja intacto (mejor no adivinar).
NORMALIZACION_TIPO = {
    'TECNICO LABORAL': 'TL', 'TÉCNICO LABORAL': 'TL', 'TECNICO': 'TL',
    'TECNICO_LABORAL': 'TL', 'TÉCNICO_LABORAL': 'TL',
    # "Técnico Profesional" es, en rigor, un nivel académico distinto de
    # "Técnico Laboral", pero el catálogo actual solo tiene 4 códigos
    # (TL/PROF/TEC/ING) -- por decisión del usuario (2026-09-04) se agrupa
    # junto con Técnico Laboral bajo TL.
    'TECNICO_PROFESIONAL': 'TL', 'TÉCNICO_PROFESIONAL': 'TL',
    'TECNICO PROFESIONAL': 'TL', 'TÉCNICO PROFESIONAL': 'TL',
    'PROFESIONAL': 'PROF',
    'TECNOLOGIA': 'TEC', 'TECNOLOGÍA': 'TEC', 'TECNOLOGO': 'TEC', 'TECNÓLOGO': 'TEC',
    'INGLES': 'ING', 'INGLÉS': 'ING', 'CURSO DE INGLES': 'ING', 'CURSO DE INGLÉS': 'ING',
}
CODIGOS_VALIDOS = {c for c, _ in Programa.TIPO_CHOICES}


class Command(BaseCommand):
    help = 'Diagnostica y limpia el catálogo de Programas (tipos con texto libre + programas huérfanos).'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Aplica los cambios (por defecto solo diagnostica)')

    def handle(self, *args, **opts):
        aplicar = opts['aplicar']

        # ── 1. Diagnóstico de `tipo` ──────────────────────────────────
        qs = Programa.objects.filter(activo=True)
        tipos_crudos = {}
        for p in qs.only('id_programa', 'tipo'):
            tipos_crudos.setdefault(p.tipo, 0)
            tipos_crudos[p.tipo] += 1

        self.stdout.write(self.style.MIGRATE_HEADING('\n== Valores de "tipo" encontrados en programas activos ==') if hasattr(self.style, 'MIGRATE_HEADING') else '\n== Valores de "tipo" encontrados ==')
        a_normalizar = {}
        sin_reconocer = {}
        for valor, n in sorted(tipos_crudos.items(), key=lambda kv: -kv[1]):
            if valor in CODIGOS_VALIDOS:
                self.stdout.write(f'  {valor!r:22} {n:5}  (código válido, no se toca)')
            elif valor in NORMALIZACION_TIPO:
                destino = NORMALIZACION_TIPO[valor]
                a_normalizar[valor] = destino
                self.stdout.write(self.style.WARNING(f'  {valor!r:22} {n:5}  -> se normaliza a {destino!r}'))
            else:
                sin_reconocer[valor] = n
                self.stdout.write(self.style.ERROR(f'  {valor!r:22} {n:5}  -> NO reconocido, se deja igual (revisar a mano)'))

        # ── 2. Programas huérfanos (sin Materia ni Estudiante) ────────
        huerfanos = list(
            qs.annotate(
                n_materias=Count('materias', distinct=True),
                n_estudiantes=Count('estudiante', distinct=True),
            ).filter(n_materias=0, n_estudiantes=0).select_related('facultad')
        )
        huerfanos_prof = [p for p in huerfanos if NORMALIZACION_TIPO.get(p.tipo, p.tipo) == 'PROF']

        self.stdout.write(f'\n== Programas activos sin ninguna Materia ni Estudiante asociado: {len(huerfanos)} ==')
        for p in huerfanos[:40]:
            self.stdout.write(f'  [{p.tipo:12}] {p.codigo:10} {p.nombre[:70]}')
        if len(huerfanos) > 40:
            self.stdout.write(f'  ... y {len(huerfanos) - 40} más')

        self.stdout.write(self.style.WARNING(
            f'\n  De esos, {len(huerfanos_prof)} son de tipo "profesional" (huérfanos también).'
        ))

        con_datos_prof = [
            p for p in qs.filter(tipo__in=list({k for k, v in NORMALIZACION_TIPO.items() if v == 'PROF'} | {'PROF'}))
            if p not in huerfanos
        ]
        if con_datos_prof:
            self.stdout.write(self.style.WARNING(
                f'\n  OJO: hay {len(con_datos_prof)} programa(s) "profesional" que SÍ tienen Materias o '
                f'Estudiantes asociados -- estos NO se tocan (tienen datos reales):'))
            for p in con_datos_prof[:20]:
                self.stdout.write(f'    - {p.codigo} {p.nombre[:70]}')

        if not aplicar:
            self.stdout.write(self.style.SUCCESS(
                '\n[Solo diagnóstico] Nada se cambió. Corre con --aplicar para normalizar tipos y '
                'desactivar los programas huérfanos listados arriba.'
            ))
            return

        # ── 3. Aplicar ─────────────────────────────────────────────────
        with transaction.atomic():
            total_normalizados = 0
            for valor, destino in a_normalizar.items():
                total_normalizados += Programa.objects.filter(tipo=valor).update(tipo=destino)

            ids_huerfanos = [p.id_programa for p in huerfanos]
            total_desactivados = Programa.objects.filter(id_programa__in=ids_huerfanos).update(activo=False)

        self.stdout.write(self.style.SUCCESS(
            f'\nAplicado: {total_normalizados} programa(s) con tipo normalizado, '
            f'{total_desactivados} programa(s) huérfano(s) desactivados (activo=False, no borrados).'
        ))
