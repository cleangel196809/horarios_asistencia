"""SIIHAPI · apps.decano -- comando manual del motor de reglas (Sprint 4,
2026-09-06). Mismo patron de --dry-run ya usado en Sprint 2
(recalcular_alertas_riesgo) y recomendado explicitamente por la
especificacion antes de activar el envio real de correos.

Uso:
    python manage.py evaluar_reglas_intervencion --dry-run
    python manage.py evaluar_reglas_intervencion
    python manage.py evaluar_reglas_intervencion --regla 3   # solo una regla
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Evalua todas las ReglaIntervencion activas y dispara correos (Entregable 4).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Solo muestra que se dispararia, sin crear LogIntervencion ni enviar correos.')
        parser.add_argument('--regla', type=int, default=None, help='Evalua solo la ReglaIntervencion con este id_regla.')

    def handle(self, *args, **options):
        from apps.decano.tasks import evaluar_reglas_intervencion_sync

        resultado = evaluar_reglas_intervencion_sync(dry_run=options['dry_run'], solo_regla_id=options['regla'])

        if options['dry_run']:
            for nombre_regla, objeto_tipo, objeto_id, valor, destinatarios in resultado:
                self.stdout.write(f'{nombre_regla}: {objeto_tipo}#{objeto_id} = {valor} -> {len(destinatarios)} destinatario(s)')
            self.stdout.write(self.style.SUCCESS(f'{len(resultado)} intervencion(es) se dispararian.'))
        else:
            enviados = sum(1 for log in resultado if log.estado == 'ENVIADO')
            fallidos = sum(1 for log in resultado if log.estado == 'FALLIDO')
            self.stdout.write(self.style.SUCCESS(
                f'{len(resultado)} LogIntervencion creados ({enviados} enviados, {fallidos} fallidos).'
            ))
