"""
Carga masiva de Facultad y Sede para docentes reales, desde el Excel
DOCENTES_20263T.xlsx (Fase 3, 2026-09-04).

Reglas acordadas con el usuario:
  - SEDE: solo se reconocen Calle 73 / Norte / Sur (las 3 sedes reales).
    "Asistida por Tecnologia", "Automatizada", "Practica" y "Seminario" NO
    son sedes fisicas -- esos docentes quedan SIN sede (se les asigna
    igual la facultad, si aplica).
  - FACULTAD: se corrigio el mapeo despues de revisar la tabla real de
    facultades (el set de 6 que traia el script de datos demo NUNCA se
    corrio contra esta base -- lo que hay realmente son 10 facultades con
    otros codigos). Mapeo real usado:
      EMPRENDIMIENTO -> EMP_R, HOSPITALIDAD -> HOS_R, IDIOMAS -> IDI_R,
      ENFERMERIA -> ENF_R (ya existian, se usan tal cual, NO se duplican)
      INGENIERIAS -> ING_R (elegido sobre FIS "Facultad de Ingenieria y
      Sistemas", que parece ser de otro esquema)
      SALUD -> FSA "Facultad de Salud" (elegido sobre SAL_R "SALUD",
      decision explicita del usuario)
      CVC e INVESTIGACION: no existe nada parecido -- se crean nuevas
      (CVC_R, INV_R).
  - Cedula duplicada en el Excel (ej. 1032493228): se usa solo la primera
    aparicion.
  - Docente sin correo institucional en el Excel: se omite del cargue
    (se reporta al final para completarlo a mano).
  - Docente que ya existe en el sistema (por cedula o correo) y su rol
    YA es DOCENTE: se crea/actualiza su perfil de Docente con la
    facultad/sede nuevas, sin tocar nada mas de su cuenta.
  - Docente que ya existe pero con OTRO rol (no DOCENTE): NO se toca --
    se reporta como conflicto para revisar a mano.
  - Docente que no existe en el sistema: se crea el Usuario (rol
    DOCENTE, contrasena temporal) y su perfil de Docente, con
    facultad/sede. El nombre se separa de "APELLIDOS NOMBRES" partiendo
    la lista de palabras a la mitad (heuristica) -- revisar los nombres
    de las cuentas nuevas que reporta este comando al final, un par de
    nombres compuestos raros pueden quedar mal repartidos.

Uso:
    python manage.py cargar_docentes_facultad_sede [ruta_al_excel] [--dry-run]
    (por defecto usa data_carga/DOCENTES_20263T.xlsx dentro de backend/)

--dry-run: no escribe nada en la base de datos, solo imprime que haria.
"""
import os
import unicodedata

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.autenticacion.models import Usuario
from apps.academico.models import Facultad
from apps.infraestructura.models import Sede
from apps.personal.models import Docente

TEMP_PASSWORD = 'Docente2026!'

DEFAULT_PATH = os.path.join(settings.BASE_DIR, 'data_carga', 'DOCENTES_20263T.xlsx')

# valor normalizado de SEDE (sin tildes, mayusculas) -> codigo de Sede real
SEDE_MAP = {
    'CALLE 73': 'CLL73',
    'NORTE': 'NORTE',
    'SUR': 'SUR',
}
# Todo lo demas (Asistida por Tecnologia, Automatizada, Practica,
# Seminario, ...) queda sin sede a proposito -- no son sedes fisicas.

# valor normalizado de FACULTAD -> (codigo, nombre). Las marcadas NUEVA
# se crean si todavia no existen.
FACULTAD_MAP = {
    'EMPRENDIMIENTO':  ('EMP_R', 'EMPRENDIMIENTO'),        # ya existia
    'HOSPITALIDAD':    ('HOS_R', 'HOSPITALIDAD'),          # ya existia
    'IDIOMAS':         ('IDI_R', 'IDIOMAS'),               # ya existia
    'ENFERMERIA':      ('ENF_R', 'ENFERMERIA'),            # ya existia
    'INGENIERIAS':     ('ING_R', 'INGENIERIA'),            # ya existia
    'SALUD':           ('FSA',   'Facultad de Salud'),     # ya existia
    'CVC':             ('CVC_R', 'CVC'),                   # NUEVA
    'INVESTIGACION':   ('INV_R', 'Investigacion'),         # NUEVA
}


def _norm(s):
    """Mayusculas, sin tildes, espacios de sobra colapsados."""
    if s is None:
        return ''
    s = str(s).strip()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(s.upper().split())


def _partir_nombre(nombre_completo):
    """Heuristica: 'APELLIDOS NOMBRES' -> se parte la lista de palabras a
    la mitad (la palabra impar sobrante se la lleva el apellido). Falla
    en nombres compuestos raros (ej. 'MARIA DE LOS ANGELES') -- por eso
    el comando lista todas las cuentas nuevas al final, para revisarlas."""
    partes = nombre_completo.split()
    if len(partes) <= 1:
        return nombre_completo.title(), nombre_completo.title()
    mitad = (len(partes) + 1) // 2
    apellido = ' '.join(partes[:mitad])
    nombre = ' '.join(partes[mitad:])
    return nombre.title(), apellido.title()


class Command(BaseCommand):
    help = 'Carga Facultad y Sede de docentes reales desde un Excel (DOCENTES_20263T.xlsx).'

    def add_arguments(self, parser):
        parser.add_argument('ruta', nargs='?', default=DEFAULT_PATH)
        parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                             help='No escribe en la base de datos, solo reporta que haria.')

    def handle(self, *args, **options):
        ruta = options['ruta']
        dry_run = options['dry_run']
        if not os.path.exists(ruta):
            raise CommandError(f'No se encontro el archivo: {ruta}')

        try:
            import openpyxl
        except ImportError:
            raise CommandError('Falta openpyxl (deberia estar en requirements.txt).')

        wb = openpyxl.load_workbook(ruta, data_only=True)
        if 'DOCENTES' not in wb.sheetnames:
            raise CommandError(f'El archivo no tiene una hoja "DOCENTES" (hojas: {wb.sheetnames})')
        ws = wb['DOCENTES']
        filas = list(ws.iter_rows(min_row=2, values_only=True))

        if dry_run:
            self.stdout.write(self.style.WARNING('--- DRY RUN: no se escribe nada en la base de datos ---\n'))

        # 1) Asegurar las facultades (crea las 3 nuevas si hacen falta)
        facultades_cache = {}
        for clave, (cod, nom) in FACULTAD_MAP.items():
            if dry_run:
                fac = Facultad.objects.filter(codigo=cod).first()
                creada = fac is None
            else:
                fac, creada = Facultad.objects.get_or_create(codigo=cod, defaults={'nombre': nom})
            facultades_cache[clave] = fac
            if creada:
                self.stdout.write(self.style.WARNING(f'  + Facultad nueva: {nom} ({cod})'))

        sedes_cache = {cod: Sede.objects.filter(codigo=cod).first() for cod in set(SEDE_MAP.values())}

        vistas_cedula = set()
        creados, actualizados, sin_correo = [], [], []
        conflicto_rol, sede_no_reconocida = [], []

        def _procesar():
            for fila in filas:
                if not fila or all(v is None for v in fila):
                    continue
                datos = (list(fila) + [None] * 5)[:5]
                nit_cc, nombre_completo, correo, facultad_raw, sede_raw = datos

                if nit_cc is None or str(nit_cc).strip() == '':
                    continue
                cedula = str(nit_cc).strip()
                if cedula in vistas_cedula:
                    continue  # cedula duplicada -- se usa solo la primera vez
                vistas_cedula.add(cedula)

                nombre_completo = (nombre_completo or '').strip()
                correo = (correo or '').strip().lower()
                if not correo:
                    sin_correo.append(nombre_completo or cedula)
                    continue

                facultad_obj = facultades_cache.get(_norm(facultad_raw))
                sede_cod = SEDE_MAP.get(_norm(sede_raw))
                sede_obj = sedes_cache.get(sede_cod) if sede_cod else None
                if sede_cod is None and _norm(sede_raw):
                    sede_no_reconocida.append((nombre_completo, sede_raw))

                usuario = (Usuario.objects.filter(cedula=cedula).first()
                           or Usuario.objects.filter(correo__iexact=correo).first())

                if usuario is None:
                    nombre, apellido = _partir_nombre(nombre_completo)
                    if not dry_run:
                        usuario = Usuario.objects.create_user(
                            correo=correo, password=TEMP_PASSWORD, rol='DOCENTE',
                            nombre=nombre, apellido=apellido, cedula=cedula, is_active=True,
                        )
                        Docente.objects.update_or_create(
                            usuario=usuario, defaults={'facultad': facultad_obj, 'sede': sede_obj},
                        )
                    creados.append((f'{nombre} {apellido}', correo))
                else:
                    if usuario.rol != 'DOCENTE':
                        conflicto_rol.append((nombre_completo, correo, usuario.rol))
                        continue
                    if not dry_run:
                        Docente.objects.update_or_create(
                            usuario=usuario, defaults={'facultad': facultad_obj, 'sede': sede_obj},
                        )
                    actualizados.append((nombre_completo, correo))

        if dry_run:
            _procesar()
        else:
            with transaction.atomic():
                _procesar()

        # ---- reporte ----
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Docentes actualizados (ya existian, rol DOCENTE): {len(actualizados)}'))
        self.stdout.write(self.style.SUCCESS(
            f'Docentes creados (cuenta nueva, contrasena temporal "{TEMP_PASSWORD}"): {len(creados)}'
        ))
        if creados:
            for nom, correo in creados:
                self.stdout.write(f'    + {nom}  <{correo}>')
        if sin_correo:
            self.stdout.write(self.style.WARNING(f'\nOmitidos por falta de correo institucional en el Excel ({len(sin_correo)}):'))
            for nom in sin_correo:
                self.stdout.write(f'    - {nom}')
        if conflicto_rol:
            self.stdout.write(self.style.WARNING(f'\nYa existen con OTRO rol (no se tocaron) ({len(conflicto_rol)}):'))
            for nom, correo, rol in conflicto_rol:
                self.stdout.write(f'    - {nom} <{correo}> (rol actual: {rol})')
        if sede_no_reconocida:
            valores = sorted(set(_norm(s) for _, s in sede_no_reconocida))
            self.stdout.write(self.style.WARNING(
                f'\nSin sede fisica reconocida -- quedaron sin sede ({len(sede_no_reconocida)} docentes, '
                f'valores del Excel: {valores}):'
            ))
        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING('--- DRY RUN: nada de esto se guardo. Corre sin --dry-run para aplicarlo. ---'))
        else:
            self.stdout.write(self.style.SUCCESS('Listo.'))
