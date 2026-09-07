"""
SIIHAPI - Genera Horario(PROPUESTO) a partir de los `grupos`/`horario_bloques`
ya cargados en la tabla unificada (compartida con Planeacion), para que
aparezcan en el panel de administrador ("Revision de propuesta",
/dashboard/revision/) listos para aprobar -- exactamente igual que si
hubieran salido del motor de IA / de una Carga Masiva por archivo.

Contexto (2026-09-06): se cargaron 631 grupos (787 bloques de horario) para
los periodos 2026-2T/2026-1T/2025-4T/2025-3T/2024-4T desde base_horarios.xlsx
directamente en las tablas `grupos`/`horario_bloques` (esquema unificado,
compartido con Planeacion), y se marcaron con origen='MOTOR_IA' y
estado='PROPUESTO_IA'. Pero SIIHAPI_HORARIO (lo que de verdad muestra la
pantalla de "Revision de propuesta") es un horario POR ESTUDIANTE, ligado a
SIIHAPI_MATRICULA (estudiante+materia+periodo) -- una tabla totalmente
separada de la `matriculas` (grupo_id) del esquema unificado, y que hoy no
tiene ningun estudiante matriculado cargado para ningun periodo.

Este comando resuelve eso reutilizando el mismo patron que ya usa
`siihapi/motor_ia/pipeline.py::_guardar_horarios_propuestos` cuando una
materia no tiene aun matriculas reales: crea (una sola vez) un estudiante
placeholder "Grupo Importado (IA)" (codigo='DOC-IMPORT') y lo matricula en
cada materia/periodo que lo necesite, solo para que la clase quede
registrada y visible para revision -- si mas adelante se cargan matriculas
reales de estudiantes, este comando las usa en su lugar automaticamente (no
hace falta volver a correrlo distinto).

Es IDEMPOTENTE: usa get_or_create tanto para las matriculas placeholder como
para cada Horario, así que correrlo varias veces no duplica nada. NO borra
ningun Horario existente de otros periodos ni de cargas anteriores (a
diferencia de `_guardar_horarios_propuestos`, que borra TODOS los PROPUESTO
sin importar el periodo -- por eso este comando es un script aparte y no una
llamada directa a esa funcion).

Uso (desde `SIIHAPI/backend`, con el venv activado):
    python manage.py generar_horarios_propuesta_desde_grupos
    python manage.py generar_horarios_propuesta_desde_grupos --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction


PERIODOS_OBJETIVO = ['2026-2T', '2026-1T', '2025-4T', '2025-3T', '2024-4T']

_DIA_MAP = {
    'LUNES': 'LU', 'MARTES': 'MA', 'MIERCOLES': 'MI',
    'JUEVES': 'JU', 'VIERNES': 'VI', 'SABADO': 'SA', 'DOMINGO': 'DO',
}


def _entidades_por_defecto():
    """Mismo patron que siihapi/motor_ia/pipeline.py::_entidades_por_defecto:
    crea (si faltan) Facultad/Programa/Usuario/Estudiante placeholder."""
    from apps.academico.models import Facultad, Programa
    from apps.matriculas.models import Estudiante
    from apps.autenticacion.models import Usuario

    fac, _ = Facultad.objects.get_or_create(
        codigo='IMP', defaults={'nombre': 'Importados (IA)'})
    prog, _ = Programa.objects.get_or_create(
        codigo='IMP', defaults={'facultad': fac, 'nombre': 'Programa Importado (IA)', 'tipo': 'TEC'})

    est = Estudiante.objects.filter(codigo='DOC-IMPORT').first()
    if not est:
        u = Usuario.objects.filter(correo='import.horarios@pi.edu.co').first()
        if not u:
            u = Usuario(correo='import.horarios@pi.edu.co', nombre='Grupo',
                        apellido='Importado (IA)', rol='ESTUDIANTE')
            try:
                u.set_password('Import_2026!')
            except Exception:
                pass
            u.save()
        est = Estudiante.objects.create(usuario=u, codigo='DOC-IMPORT', programa=prog)
    return est


class Command(BaseCommand):
    help = (
        'Crea Horario(PROPUESTO) en SIIHAPI a partir de los grupos/horario_bloques '
        'ya cargados (origen=MOTOR_IA, estado=PROPUESTO_IA) para los periodos '
        '2026-2T/2026-1T/2025-4T/2025-3T/2024-4T, para que aparezcan en /dashboard/revision/.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='No escribe nada; solo muestra cuantos Horario se crearian.')

    def handle(self, *args, **options):
        from apps.horarios.models import Horario, Bloque
        from apps.academico.models import Materia
        from apps.personal.models import Docente
        from apps.infraestructura.models import Salon
        from apps.matriculas.models import Matricula, Periodo

        dry_run = options['dry_run']

        bloques = list(Bloque.objects.order_by('numero'))
        if not bloques:
            self.stderr.write(self.style.ERROR(
                'No hay filas en bloques_horario -- no se puede mapear hora_inicio a '
                'un Bloque. Abortando (no se escribio nada).'))
            return

        def _bloque_cercano(hi_str):
            try:
                hh, mm = str(hi_str)[:5].split(':')
                t = int(hh) * 60 + int(mm)
            except Exception:
                return bloques[0]
            return min(bloques, key=lambda b: abs(
                (b.hora_inicio.hour * 60 + b.hora_inicio.minute) - t))

        placeholders = ', '.join(['%s'] * len(PERIODOS_OBJETIVO))
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT g.id, g.materia_id, g.docente_id, p.codigo
                FROM grupos g
                JOIN periodos p ON p.id = g.periodo_id
                WHERE p.codigo IN ({placeholders})
                  AND g.origen = 'MOTOR_IA' AND g.estado = 'PROPUESTO_IA'
                ORDER BY g.id
            """, PERIODOS_OBJETIVO)
            grupos_rows = cur.fetchall()

            cur.execute(f"""
                SELECT hb.grupo_id, hb.dia, hb.hora_inicio, hb.salon_id
                FROM horario_bloques hb
                JOIN grupos g ON g.id = hb.grupo_id
                JOIN periodos p ON p.id = g.periodo_id
                WHERE p.codigo IN ({placeholders})
                  AND g.origen = 'MOTOR_IA' AND g.estado = 'PROPUESTO_IA'
                ORDER BY hb.grupo_id, hb.orden
            """, PERIODOS_OBJETIVO)
            bloques_rows = cur.fetchall()

        self.stdout.write(f'Grupos en alcance: {len(grupos_rows)}. Filas de horario: {len(bloques_rows)}.')

        bloques_por_grupo = {}
        for grupo_id, dia, hi, salon_id in bloques_rows:
            bloques_por_grupo.setdefault(grupo_id, []).append((dia, hi, salon_id))

        materia_cache, docente_cache, salon_cache, periodo_cache = {}, {}, {}, {}
        est_placeholder = None

        creados = 0
        ya_existian = 0
        omitidos_sin_bloques = 0
        omitidos_sin_docente = 0
        omitidos_sin_materia = 0
        omitidos_sin_salon = 0
        omitidos_sin_periodo = 0
        matriculas_placeholder_creadas = 0

        def _run():
            nonlocal est_placeholder, creados, ya_existian, omitidos_sin_bloques
            nonlocal omitidos_sin_docente, omitidos_sin_materia, omitidos_sin_salon
            nonlocal omitidos_sin_periodo, matriculas_placeholder_creadas

            for grupo_id, materia_id, docente_id, periodo_codigo in grupos_rows:
                bloques_grupo = bloques_por_grupo.get(grupo_id, [])
                if not bloques_grupo:
                    omitidos_sin_bloques += 1
                    continue

                if materia_id not in materia_cache:
                    materia_cache[materia_id] = Materia.objects.filter(pk=materia_id).first()
                materia = materia_cache[materia_id]
                if not materia:
                    omitidos_sin_materia += 1
                    continue

                docente = None
                if docente_id:
                    if docente_id not in docente_cache:
                        docente_cache[docente_id] = Docente.objects.filter(pk=docente_id).first()
                    docente = docente_cache[docente_id]
                if not docente:
                    omitidos_sin_docente += 1
                    continue

                if periodo_codigo not in periodo_cache:
                    periodo_cache[periodo_codigo] = Periodo.objects.filter(codigo=periodo_codigo).first()
                periodo = periodo_cache[periodo_codigo]
                if not periodo:
                    omitidos_sin_periodo += 1
                    continue

                matriculas = list(Matricula.objects.filter(
                    materia=materia, periodo=periodo, estado__in=['ACTIVA', 'INSCRITA']))
                if not matriculas:
                    if est_placeholder is None:
                        est_placeholder = _entidades_por_defecto()
                    mph, mph_creada = Matricula.objects.get_or_create(
                        estudiante=est_placeholder, materia=materia, periodo=periodo,
                        defaults={'estado': 'ACTIVA'})
                    if mph_creada:
                        matriculas_placeholder_creadas += 1
                    matriculas = [mph]

                for dia_raw, hi, salon_id in bloques_grupo:
                    dia_cod = _DIA_MAP.get(str(dia_raw).upper())
                    if not dia_cod:
                        continue
                    if salon_id not in salon_cache:
                        salon_cache[salon_id] = Salon.objects.filter(pk=salon_id).first() if salon_id else None
                    salon = salon_cache[salon_id]
                    if not salon:
                        omitidos_sin_salon += 1
                        continue
                    bloque = _bloque_cercano(hi)

                    for mat in matriculas:
                        obj, created = Horario.objects.get_or_create(
                            matricula=mat, materia=materia, docente=docente,
                            salon=salon, bloque=bloque, dia=dia_cod,
                            defaults={'estado': 'PROPUESTO'})
                        if created:
                            creados += 1
                        else:
                            ya_existian += 1

            if dry_run:
                raise _DryRunRollback()

        class _DryRunRollback(Exception):
            pass

        try:
            with transaction.atomic():
                _run()
        except _DryRunRollback:
            pass

        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY-RUN] ' if dry_run else ''}Horario(PROPUESTO) creados: {creados}. "
            f"Ya existian (idempotente): {ya_existian}. "
            f"Matriculas placeholder nuevas: {matriculas_placeholder_creadas}."
        ))
        if omitidos_sin_bloques or omitidos_sin_docente or omitidos_sin_materia or omitidos_sin_salon or omitidos_sin_periodo:
            self.stdout.write(self.style.WARNING(
                f"Omitidos -- sin bloques: {omitidos_sin_bloques}, sin materia: {omitidos_sin_materia}, "
                f"sin docente: {omitidos_sin_docente}, sin salon: {omitidos_sin_salon}, "
                f"sin periodo: {omitidos_sin_periodo}."
            ))
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run: no se escribio nada en la base de datos.'))
