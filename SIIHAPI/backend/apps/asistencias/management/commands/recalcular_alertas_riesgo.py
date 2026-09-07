"""
SIIHAPI · apps/asistencias (Sprint 2, 2026-09-06).

RF 2.3 -- recálculo batch nocturno de AlertaRiesgo. El umbral usado aquí
es FIJO (>= 3 materias con >= 30% de inasistencia en los últimos 30 días);
en el Sprint 4 esto se vuelve configurable vía decano.ReglaIntervencion
(métrica INASISTENCIA_ESTUDIANTE_MULTIMATERIA) sin cambiar esta lógica de
cálculo, solo el origen del umbral.

Uso:
    python manage.py recalcular_alertas_riesgo            # aplica cambios
    python manage.py recalcular_alertas_riesgo --dry-run   # solo reporta

Pensado para correr vía cron/Task Scheduler cada noche (no depende de
Celery -- ver restricción técnica de "sin Redis" hasta el Sprint 4).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

UMBRAL_PCT_INASISTENCIA = 30
MIN_MATERIAS_AFECTADAS = 3
VENTANA_DIAS = 30


class Command(BaseCommand):
    help = 'Recalcula asistencias.AlertaRiesgo para estudiantes con inasistencia alta en 3+ materias (RF 2.3).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Solo muestra qué alertas se crearían, sin escribir en la base.')

    def handle(self, *args, **options):
        from apps.asistencias.models import AsistenciaEstudiante, AlertaRiesgo
        from apps.bienestar.models import CasoBienestar
        from apps.autenticacion.models import Usuario

        dry_run = options['dry_run']
        desde = timezone.localdate() - timedelta(days=VENTANA_DIAS)

        por_estudiante_materia = (
            AsistenciaEstudiante.objects.filter(fecha__gte=desde)
            .values('matricula__estudiante', 'matricula__materia')
            .annotate(total=Count('id_asistencia'), ausentes=Count('id_asistencia', filter=Q(estado='AUSENTE')))
        )

        materias_por_estudiante = {}
        for row in por_estudiante_materia:
            if not row['total']:
                continue
            pct = (row['ausentes'] / row['total']) * 100
            if pct >= UMBRAL_PCT_INASISTENCIA:
                materias_por_estudiante.setdefault(row['matricula__estudiante'], []).append(
                    (row['matricula__materia'], pct)
                )

        creadas = 0
        for estudiante_id, materias in materias_por_estudiante.items():
            if len(materias) < MIN_MATERIAS_AFECTADAS:
                continue

            pct_prom = sum(p for _, p in materias) / len(materias)
            nivel = 'ALTO' if (pct_prom >= 50 or len(materias) >= 4) else 'MEDIO'

            ya_abierta = AlertaRiesgo.objects.filter(
                estudiante_id=estudiante_id, estado__in=['ABIERTA', 'EN_SEGUIMIENTO']
            ).exists()
            if ya_abierta:
                # Idempotente: no duplicar mientras la alerta anterior siga abierta.
                continue

            self.stdout.write(
                f'Estudiante {estudiante_id}: {len(materias)} materias afectadas, '
                f'{pct_prom:.1f}% inasistencia promedio -> nivel {nivel}'
            )
            if dry_run:
                creadas += 1
                continue

            alerta = AlertaRiesgo.objects.create(
                estudiante_id=estudiante_id, nivel=nivel, pct_inasistencia_calculado=round(pct_prom, 2),
            )
            alerta.materias_afectadas.set([materia_id for materia_id, _ in materias])
            creadas += 1

            if nivel == 'ALTO':
                bienestar_user = Usuario.objects.filter(rol='BIENESTAR_ACADEMICO', is_active=True).first()
                if bienestar_user:
                    CasoBienestar.objects.create(
                        estudiante_id=estudiante_id, alerta_origen=alerta,
                        origen='ALERTA_AUTOMATICA', asignado_a=bienestar_user,
                    )
                else:
                    self.stdout.write(self.style.WARNING(
                        f'No hay usuario BIENESTAR_ACADEMICO activo -- CasoBienestar no creado '
                        f'para estudiante {estudiante_id} (alerta #{alerta.id_alerta} sí quedó creada).'
                    ))

        verbo = 'se crearían' if dry_run else 'creadas'
        self.stdout.write(self.style.SUCCESS(f'{creadas} alertas de riesgo {verbo}.'))
