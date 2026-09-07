"""
Crea (o actualiza) una cuenta de prueba por cada rol de SIIHAPI, con una
contrasena conocida, para poder probar el login uno a uno tras el fix de
equivalencias de rol (ADMIN/DECANO/SECRETARIA_ACADEMICA).

No toca ninguna cuenta real existente (admin@pi.edu.co, pedro.ramirez@..., etc.):
usa correos dedicados prueba.<rol>@pi.edu.co, aparte de los datos reales.

Uso:
    python manage.py crear_cuentas_prueba
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.autenticacion.models import Usuario

PASSWORD_PRUEBA = 'Prueba2026!'

CUENTAS = [
    ('ADMIN',                'prueba.admin@pi.edu.co',       'Prueba', 'Admin'),
    ('COORDINADOR',          'prueba.coordinador@pi.edu.co', 'Prueba', 'Coordinador'),
    ('DECANO',               'prueba.decano@pi.edu.co',      'Prueba', 'Decano'),
    ('SECRETARIA_ACADEMICA', 'prueba.secretaria@pi.edu.co',  'Prueba', 'Secretaria'),
    ('DOCENTE',              'prueba.docente@pi.edu.co',     'Prueba', 'Docente'),
    ('ESTUDIANTE',           'prueba.estudiante@pi.edu.co',  'Prueba', 'Estudiante'),
]


class Command(BaseCommand):
    help = 'Crea/actualiza una cuenta de prueba por rol con contrasena conocida.'

    def handle(self, *args, **options):
        self.stdout.write('')
        self.stdout.write(f"{'ROL':<23} | {'CORREO':<31} | CONTRASENA")
        self.stdout.write('-' * 78)
        for rol, correo, nombre, apellido in CUENTAS:
            usuario, creado = Usuario.objects.get_or_create(
                correo=correo,
                defaults={
                    'nombre': nombre,
                    'apellido': apellido,
                    'rol': rol,
                    'acepta_terminos': True,
                    'fecha_aceptacion_habeas_data': timezone.now(),
                    'is_active': True,
                },
            )
            if not creado:
                usuario.rol = rol
                usuario.is_active = True
            usuario.set_password(PASSWORD_PRUEBA)
            usuario.save()
            estado = 'creada' if creado else 'actualizada'
            self.stdout.write(f'{rol:<23} | {correo:<31} | {PASSWORD_PRUEBA}   ({estado})')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            'Listo. En /login/ selecciona el tile del rol correspondiente y usa el correo + esta contrasena.'
        ))
