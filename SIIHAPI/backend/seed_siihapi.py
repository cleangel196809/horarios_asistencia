"""
SIIHAPI — Carga de datos demo (facultades, programas, materias, docentes,
estudiantes y personal administrativo) a partir de los CSV de ejemplo en
SIIHAPI/csv_prueba/. Analogo a SISCA/seed_data.py.

Uso:
    cd SIIHAPI/backend
    python seed_siihapi.py

Es idempotente: se puede correr varias veces sin duplicar filas
(usa get_or_create / update_or_create en todo).
"""
import csv
import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siihapi.settings')
import django  # noqa: E402
django.setup()

from apps.academico.models import Facultad, Programa, Materia  # noqa: E402
from apps.personal.models import Docente  # noqa: E402
from apps.matriculas.models import Estudiante  # noqa: E402
from apps.autenticacion.models import Usuario  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = BASE_DIR.parent / 'csv_prueba'


def bar(t=''):
    print('-' * 55)
    if t:
        print(f'  {t}')


def ok(msg):
    print(f'  [OK] {msg}')


def clave_por_defecto(apellido: str) -> str:
    """Mismo patrón de contraseña demo usado en SISCA/seed_data.py."""
    return f"{apellido.split()[0].capitalize()}2026!"


# ════════════════════════════════════════════════════════════
# 1) Facultades y Programas
# ════════════════════════════════════════════════════════════
bar('Creando Facultades y Programas')

FACULTADES = {
    'SALUD': 'Facultad de Ciencias de la Salud',
    'GAST':  'Facultad de Gastronomía y Turismo',
    'NEG':   'Facultad de Administración y Negocios',
    'TEC':   'Facultad de Tecnología',
    'IDIOM': 'Facultad de Idiomas',
}
facultades = {}
for codigo, nombre in FACULTADES.items():
    fac, creada = Facultad.objects.get_or_create(codigo=codigo, defaults={'nombre': nombre})
    facultades[codigo] = fac
    ok(f'Facultad {"creada" if creada else "ya existe"}: {nombre}')

# programa_codigo (del CSV) -> (nombre, tipo, facultad)
PROGRAMAS = {
    'TL01': ('Técnico Laboral en Enfermería',                 'TL',   'SALUD'),
    'TL03': ('Técnico Laboral en Mecánica Dental',             'TL',   'SALUD'),
    'TL06': ('Técnico Laboral en Bar y Coctelería',            'TL',   'GAST'),
    'TL07': ('Técnico Laboral en Gastronomía',                 'TL',   'GAST'),
    'TL08': ('Técnico Laboral en Administración',              'TL',   'NEG'),
    'TL09': ('Técnico Laboral en Mercadeo',                    'TL',   'NEG'),
    'TL11': ('Técnico Laboral en Contabilidad',                'TL',   'NEG'),
    'PR01': ('Profesional en Comercio Exterior',                'PROF', 'NEG'),
    'PR06': ('Profesional en Hotelería y Turismo',              'PROF', 'GAST'),
    'TE01': ('Tecnología en Seguridad y Salud en el Trabajo',   'TEC',  'SALUD'),
    'TE02': ('Tecnología en Desarrollo de Software',            'TEC',  'TEC'),
    'TE03': ('Tecnología en Gestión Empresarial',               'TEC',  'NEG'),
    'IN01': ('Curso de Inglés',                                 'ING',  'IDIOM'),
}
programas = {}
for codigo, (nombre, tipo, fac_codigo) in PROGRAMAS.items():
    prog, creado = Programa.objects.get_or_create(
        codigo=codigo,
        defaults={'nombre': nombre, 'tipo': tipo, 'facultad': facultades[fac_codigo]},
    )
    programas[codigo] = prog
    ok(f'Programa {"creado" if creado else "ya existe"}: {codigo} · {nombre}')


# ════════════════════════════════════════════════════════════
# 2) Materias
# ════════════════════════════════════════════════════════════
bar('Creando Materias (03_materias.csv)')
n_materias = 0
with open(CSV_DIR / '03_materias.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        programa = programas.get(row['programa_codigo'])
        if not programa:
            print(f"  [!!] Programa desconocido '{row['programa_codigo']}', se omite {row['codigo']}")
            continue
        _, creada = Materia.objects.get_or_create(
            codigo=row['codigo'],
            programa=programa,
            defaults={
                'nombre': row['nombre'],
                'ciclo': int(row['ciclo']),
                'creditos': int(row['creditos']),
                'horas_semanales': int(row['horas_semanales']),
            },
        )
        n_materias += creada
ok(f'{n_materias} materias nuevas creadas')


# ════════════════════════════════════════════════════════════
# 3) Docentes (01_docentes.csv)
# ════════════════════════════════════════════════════════════
bar('Creando Docentes (01_docentes.csv)')
credenciales_docentes = []
with open(CSV_DIR / '01_docentes.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        clave = clave_por_defecto(row['apellido'])
        usuario, creado = Usuario.objects.get_or_create(
            correo=row['correo'],
            defaults={
                'nombre': row['nombre'],
                'apellido': row['apellido'],
                'cedula': row['cedula'],
                'rol': 'DOCENTE',
            },
        )
        if creado:
            usuario.set_password(clave)
            usuario.save()
        Docente.objects.get_or_create(
            usuario=usuario,
            defaults={
                'tipo_contrato': row['tipo_contrato'],
                'carga_horaria_max': int(row['carga_horaria_max']),
            },
        )
        if creado:
            credenciales_docentes.append((row['correo'], clave))
ok(f'{len(credenciales_docentes)} docentes nuevos creados')


# ════════════════════════════════════════════════════════════
# 4) Estudiantes (02_estudiantes.csv)
# ════════════════════════════════════════════════════════════
bar('Creando Estudiantes (02_estudiantes.csv)')
credenciales_estudiantes = []
n_omitidos = 0
with open(CSV_DIR / '02_estudiantes.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        programa = programas.get(row['programa_codigo'])
        if not programa:
            n_omitidos += 1
            continue
        clave = clave_por_defecto(row['apellido'])
        usuario, creado = Usuario.objects.get_or_create(
            correo=row['correo'],
            defaults={
                'nombre': row['nombre'],
                'apellido': row['apellido'],
                'cedula': row['cedula'],
                'rol': 'ESTUDIANTE',
            },
        )
        if creado:
            usuario.set_password(clave)
            usuario.save()
        Estudiante.objects.get_or_create(
            usuario=usuario,
            defaults={
                'codigo': row['cedula'],
                'programa': programa,
                'semestre_actual': int(row['semestre']),
            },
        )
        if creado:
            credenciales_estudiantes.append((row['correo'], clave))
ok(f'{len(credenciales_estudiantes)} estudiantes nuevos creados'
   + (f' ({n_omitidos} omitidos por programa desconocido)' if n_omitidos else ''))


# ════════════════════════════════════════════════════════════
# 5) Personal administrativo / coordinadores (04_personal.csv)
# ════════════════════════════════════════════════════════════
bar('Creando Personal administrativo (04_personal.csv)')
credenciales_personal = []
with open(CSV_DIR / '04_personal.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        clave = clave_por_defecto(row['apellido'])
        usuario, creado = Usuario.objects.get_or_create(
            correo=row['correo'],
            defaults={
                'nombre': row['nombre'],
                'apellido': row['apellido'],
                'cedula': row['cedula'],
                'rol': row['rol'],
            },
        )
        if creado:
            usuario.set_password(clave)
            usuario.save()
            credenciales_personal.append((row['correo'], clave, row['rol']))
ok(f'{len(credenciales_personal)} usuarios de personal nuevos creados')


# ════════════════════════════════════════════════════════════
# Resumen
# ════════════════════════════════════════════════════════════
print('\n' + '=' * 55)
print('  DATOS DEMO CARGADOS')
print('=' * 55)
print(f'  Facultades : {len(facultades)}')
print(f'  Programas  : {len(programas)}')
print(f'  Materias   : {Materia.objects.count()} en total')
print(f'  Docentes   : {Docente.objects.count()} en total')
print(f'  Estudiantes: {Estudiante.objects.count()} en total')

if credenciales_docentes:
    print('\n  DOCENTES (nuevos):')
    for correo, clave in credenciales_docentes[:5]:
        print(f'    {correo:<40}/ {clave}')
    if len(credenciales_docentes) > 5:
        print(f'    ... y {len(credenciales_docentes) - 5} más')

if credenciales_estudiantes:
    print('\n  ESTUDIANTES (muestra):')
    for correo, clave in credenciales_estudiantes[:5]:
        print(f'    {correo:<40}/ {clave}')
    if len(credenciales_estudiantes) > 5:
        print(f'    ... y {len(credenciales_estudiantes) - 5} más')

if credenciales_personal:
    print('\n  PERSONAL / COORDINADORES (nuevos):')
    for correo, clave, rol in credenciales_personal:
        print(f'    {correo:<40}/ {clave:<15} ({rol})')

print('\n  Todas las contraseñas siguen el patrón Apellido2026! — solo para')
print('  demo/desarrollo. Rótalas o fuerza cambio en primer login si esto')
print('  llega a un entorno compartido.')
print('=' * 55)
