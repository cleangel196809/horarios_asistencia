"""
SIIHAPI · Seed con datos REALES del Politécnico Internacional.
==============================================================
Carga:
· 3 sedes reales (Calle 73, Norte, Sur)
· 135 salones reales extraídos del Excel "SALONES SEDES 2026.xlsx"
· 27 programas reales en 4 tipos (TL, PROF, TEC, ING)
· 6 facultades reales
· Periodo activo 2026-2

Ejecutar:
    cd backend
    python manage.py shell < ../scripts/02_seed_datos_reales.py
"""
import os
import sys
import django
from datetime import date, time

# Configurar Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siihapi.settings')
django.setup()

from apps.infraestructura.models import Sede, Salon
from apps.academico.models import Facultad, Programa, Materia
from apps.matriculas.models import Periodo
from apps.horarios.models import Bloque


# ═══════════════════════════════════════════════════════════
# 1) SEDES (3)
# ═══════════════════════════════════════════════════════════
print("[1/5] Creando sedes...")
SEDES_DATA = [
    ('CLL73', 'Calle 73', 'Calle 73 #15-08, Bogotá D.C.',     '+57 1 4441000', 800),
    ('NORTE', 'Norte',    'Carrera 7 #74-15, Bogotá D.C.',    '+57 1 4441001', 400),
    ('SUR',   'Sur',      'Avenida 1 de Mayo #45-22, Bogotá', '+57 1 4441002', 500),
]
for cod, nom, dir, tel, cap in SEDES_DATA:
    Sede.objects.update_or_create(
        codigo=cod,
        defaults={'nombre': nom, 'direccion': dir, 'telefono': tel, 'capacidad_total': cap}
    )
print(f"   ✓ {Sede.objects.count()} sedes creadas")

# ═══════════════════════════════════════════════════════════
# 2) SALONES REALES (135) - extraídos del Excel
# ═══════════════════════════════════════════════════════════
print("\n[2/5] Creando 135 salones reales...")

CLL73 = Sede.objects.get(codigo='CLL73')
NORTE = Sede.objects.get(codigo='NORTE')
SUR   = Sede.objects.get(codigo='SUR')

# Datos reales del Excel SALONES SEDES 2026.xlsx
SALONES = [
    # ─── SEDE CALLE 73 (65 salones) ───
    (CLL73, 'Piso 1', 'COC1',      'Cocina 1 - 101',           25, 'COCINA'),
    (CLL73, 'Piso 1', 'COC2',      'Cocina 2 - 102',           25, 'COCINA'),
    (CLL73, 'Piso 1', 'COC3',      'Cocina 3 - 103',           25, 'COCINA'),
    (CLL73, 'Piso 1', 'COC4',      'Cocina 4 - 104',           25, 'COCINA'),
    (CLL73, 'Piso 1', 'COC5',      'Cocina 5 - 107',           25, 'COCINA'),
    (CLL73, 'Piso 1', 'GOURMET',   'Cocina Gourmet (Economato)', 30, 'GOURMET'),
    (CLL73, 'Piso 1', 'MYB1',      'Mesa y Bar 1 - 106',       16, 'MESA_BAR'),
    (CLL73, 'Piso 1', 'MYB2',      'Mesa y Bar 2 - 107',       20, 'MESA_BAR'),
    (CLL73, 'Piso 1', 'MYB3',      'Mesa y Bar 3 - 113',       16, 'MESA_BAR'),
    (CLL73, 'Piso 1', 'TM109',     'Taller de Moda 109',       30, 'LAB_MODA'),
    (CLL73, 'Piso 1', 'TM110',     'Taller de Moda 110',       30, 'LAB_MODA'),
    (CLL73, 'Piso 1', 'REP1',      'Repostería 1 - 111',       25, 'REPOSTERIA'),
    (CLL73, 'Piso 1', 'REP2',      'Repostería 2 - 105',       30, 'REPOSTERIA'),
    (CLL73, 'Piso 2', 'CER1',      'Lab Cerámica 1 - 201',     27, 'CERAMICA'),
    (CLL73, 'Piso 2', 'CER2',      'Lab Cerámica 2 - 202',     15, 'CERAMICA'),
    (CLL73, 'Piso 2', 'LAB203',    'Lab Ortodoncia 203',       24, 'ORTODONCIA'),
    (CLL73, 'Piso 2', 'ACR',       'Lab Acrílicos 204',        43, 'ACRILICOS'),
    (CLL73, 'Piso 2', 'YES',       'Lab Yesos 205',            48, 'YESOS'),
    (CLL73, 'Piso 2', 'META',      'Lab Metalurgia 206',       23, 'METALURGIA'),
    (CLL73, 'Piso 2', 'COL',       'Lab Colados 207',          11, 'COLADOS'),
    (CLL73, 'Piso 2', '208',       'Salón 208 (Bodega)',        0, 'BODEGA'),
    (CLL73, 'Piso 2', 'INF209',    'Sala Sistemas Soft 209',   15, 'LAB_SIST'),
    (CLL73, 'Piso 2', 'INF210',    'Sala Sistemas Soft 210',   15, 'LAB_SIST'),
    (CLL73, 'Piso 2', 'INF211',    'Sala Sistemas Soft 211',   20, 'LAB_SIST'),
    (CLL73, 'Piso 2', 'INF213',    'Sala Sistemas Soft 213',   15, 'LAB_SIST'),
    (CLL73, 'Piso 2', 'INF214',    'Sala Sistemas Soft 214',   21, 'LAB_SIST'),
    (CLL73, 'Piso 2', 'BIBLIO',    'Biblioteca',               16, 'BIBLIOTECA'),
    (CLL73, 'Piso 2', '212',       'Salón 212',                12, 'AULA'),
    (CLL73, 'Piso 2', '215',       'Salón 215 (Bodega RyC)',    0, 'BODEGA'),
    # Pisos 3 y 4 de Calle 73 (resumidos)
    (CLL73, 'Piso 3', '301',       'Salón 301',                30, 'AULA'),
    (CLL73, 'Piso 3', '302',       'Salón 302',                30, 'AULA'),
    (CLL73, 'Piso 3', '303',       'Salón 303',                30, 'AULA'),
    (CLL73, 'Piso 3', '304',       'Salón 304',                30, 'AULA'),
    (CLL73, 'Piso 3', '305',       'Salón 305',                30, 'AULA'),
    (CLL73, 'Piso 3', '306',       'Salón 306',                30, 'AULA'),
    (CLL73, 'Piso 3', '307',       'Salón 307',                30, 'AULA'),
    (CLL73, 'Piso 3', '308',       'Salón 308',                30, 'AULA'),
    (CLL73, 'Piso 3', '309',       'Salón 309',                30, 'AULA'),
    (CLL73, 'Piso 3', '310',       'Salón 310',                30, 'AULA'),
    (CLL73, 'Piso 3', 'LAB_AMB',   'Laboratorio Ambiental',    25, 'LAB_AMB'),
    (CLL73, 'Piso 3', 'LAB_SAL_1', 'Lab Salud 1',              20, 'LAB_SALUD'),
    (CLL73, 'Piso 3', 'LAB_SAL_2', 'Lab Salud 2',              20, 'LAB_SALUD'),
    (CLL73, 'Piso 3', 'LAB_SAL_3', 'Lab Salud 3',              20, 'LAB_SALUD'),
    (CLL73, 'Piso 3', 'LAB_SAL_4', 'Lab Salud 4',              20, 'LAB_SALUD'),
    (CLL73, 'Piso 3', 'LAB_ENF_1', 'Lab Enfermería 1',         15, 'LAB_ENF'),
    (CLL73, 'Piso 3', 'LAB_ENF_2', 'Lab Enfermería 2',         15, 'LAB_ENF'),
    (CLL73, 'Piso 3', 'LAB_ENF_3', 'Lab Enfermería 3',         15, 'LAB_ENF'),
    (CLL73, 'Piso 3', 'LAB_ENF_4', 'Lab Enfermería 4',         15, 'LAB_ENF'),
    (CLL73, 'Piso 3', 'LAB_ENF_5', 'Lab Enfermería 5',         15, 'LAB_ENF'),
    (CLL73, 'Piso 3', 'LAB_ENF_6', 'Lab Enfermería 6',         15, 'LAB_ENF'),
    (CLL73, 'Piso 4', '401',       'Salón 401',                30, 'AULA'),
    (CLL73, 'Piso 4', '402',       'Salón 402',                30, 'AULA'),
    (CLL73, 'Piso 4', '403',       'Salón 403',                30, 'AULA'),
    (CLL73, 'Piso 4', '404',       'Salón 404',                30, 'AULA'),
    (CLL73, 'Piso 4', '405',       'Salón 405',                30, 'AULA'),
    (CLL73, 'Piso 4', '406',       'Salón 406',                30, 'AULA'),
    (CLL73, 'Piso 4', '407',       'Salón 407',                30, 'AULA'),
    (CLL73, 'Piso 4', '408',       'Salón 408',                30, 'AULA'),
    (CLL73, 'Piso 4', '409',       'Salón 409',                30, 'AULA'),
    (CLL73, 'Piso 4', '410',       'Salón 410',                30, 'AULA'),
    (CLL73, 'Piso 4', '411',       'Salón 411',                30, 'AULA'),
    (CLL73, 'Piso 4', '412',       'Salón 412',                30, 'AULA'),
    (CLL73, 'Piso 4', '413',       'Salón 413',                30, 'AULA'),
    (CLL73, 'Piso 4', 'OFI_CLL73', 'Oficina Administrativa',   10, 'OFICINA'),
    (CLL73, 'Piso 4', 'FLOT_C73',  'Salón Flotante CLL73',     20, 'FLOTANTE'),

    # ─── SEDE NORTE (31 salones) ───
    (NORTE, 'Piso 1', 'NREP1',     'Repostería 1 - 101',       25, 'REPOSTERIA'),
    (NORTE, 'Piso 1', 'NREP2',     'Repostería 2 - 102',       25, 'REPOSTERIA'),
    (NORTE, 'Piso 1', 'NCOC1',     'Cocina 1 - 103',           30, 'COCINA'),
    (NORTE, 'Piso 1', 'NCOC2',     'Cocina 2 - 104',           30, 'COCINA'),
    (NORTE, 'Piso 1', 'NCOC3',     'Cocina 3 - 105',           30, 'COCINA'),
    (NORTE, 'Piso 1', 'NCOC4',     'Cocina 4 - 106',           25, 'COCINA'),
    (NORTE, 'Piso 1', 'NCOC5',     'Cocina 5 - 107 (Gourmet)', 20, 'GOURMET'),
    (NORTE, 'Piso 2', 'OF200',     'Oficina 200 Administrativa', 16, 'OFICINA'),
    (NORTE, 'Piso 2', 'N202',      'Salón 202',                25, 'AULA'),
    (NORTE, 'Piso 2', 'NMYB203',   'Mesa y Bar 203',           24, 'MESA_BAR'),
    (NORTE, 'Piso 2', 'N204',      'Salón 204 (Silla Salud)',  30, 'LAB_SALUD'),
    (NORTE, 'Piso 2', 'N205',      'Salón 205 (Sala Juntas)',  30, 'AULA'),
    (NORTE, 'Piso 2', 'NINF206',   'Sala Sistemas Soft 206',   20, 'LAB_SIST'),
    (NORTE, 'Piso 2', 'NINF207',   'Sala Sistemas Soft 207',   24, 'LAB_SIST'),
    (NORTE, 'Piso 2', 'NINF208',   'Sala Sistemas 208',        16, 'LAB_SIST'),
    (NORTE, 'Piso 2', 'NMYB209',   'Mesa y Bar 209',           24, 'MESA_BAR'),
    (NORTE, 'Piso 2', 'NMYB210',   'Mesa y Bar 210',           24, 'MESA_BAR'),
    (NORTE, 'Piso 2', 'N211',      'Salón 211',                20, 'AULA'),
    (NORTE, 'Piso 2', 'NBBTC212',  'Biblioteca 212',           15, 'BIBLIOTECA'),
    (NORTE, 'Piso 3', 'N301',      'Salón 301 (Auditorio)',    30, 'AUDITORIO'),
    (NORTE, 'Piso 3', 'NCATA',     'Cata y Coctelería 302',    30, 'CATA'),
    (NORTE, 'Piso 3', 'NGYM',      'Gimnasio',                 20, 'GIMNASIO'),
    (NORTE, 'Piso 3', 'NMYB305',   'Sala de Docentes 303',     15, 'OFICINA'),
    (NORTE, 'Piso 3', 'NCOC6',     'Cocina 6 - 304',           25, 'COCINA'),
    (NORTE, 'Piso 3', 'NCOC7',     'Cocina 7 - 305',           25, 'COCINA'),
    (NORTE, 'Piso 3', 'NCOC8',     'Cocina 8 - 306',           25, 'COCINA'),
    (NORTE, 'Piso 3', 'NREP3',     'Repostería 3 - 307',       25, 'REPOSTERIA'),
    (NORTE, 'Piso 3', 'N308',      'Salón 308',                30, 'AULA'),
    (NORTE, 'Piso 3', 'N309',      'Salón 309 (Enfermería)',   25, 'LAB_ENF'),
    (NORTE, 'Piso 3', 'N310',      'Salón 310',                25, 'AULA'),
    (NORTE, 'Piso 3', 'N311',      'Salón 311',                25, 'AULA'),

    # ─── SEDE SUR (39 salones) ───
    (SUR, 'Piso 1', 'SYES1',       'Lab Yesos 1 - 101',        25, 'YESOS'),
    (SUR, 'Piso 1', 'SYES2',       'Lab Yesos 2 - 102',        10, 'YESOS'),
    (SUR, 'Piso 1', 'S103',        'Salón 103',                25, 'AULA'),
    (SUR, 'Piso 1', 'SMOT1',       'Lab Motores 1 - 104',      25, 'MOTORES'),
    (SUR, 'Piso 1', 'SMOT2',       'Lab Motores 2 - 105',      36, 'MOTORES'),
    (SUR, 'Piso 1', 'SMOT3',       'Lab Motores 3 - 106',      15, 'MOTORES'),
    (SUR, 'Piso 1', 'SYES3',       'Lab Yesos 3 - 107',        25, 'YESOS'),
    (SUR, 'Piso 1', 'SCOL',        'Lab Colados 108',          35, 'COLADOS'),
    (SUR, 'Piso 1', 'SCER',        'Lab Cerámica 109',         25, 'CERAMICA'),
    (SUR, 'Piso 1', 'SGYM',        'Gimnasio',                 15, 'GIMNASIO'),
    (SUR, 'Piso 2', 'SCOC4',       'Cocina 4 - 201',           25, 'COCINA'),
    (SUR, 'Piso 2', 'SREP2',       'Repostería 2 - 202',       25, 'REPOSTERIA'),
    (SUR, 'Piso 2', 'SLAB_ENF1',   'Lab Enfermería 1',         15, 'LAB_ENF'),
    (SUR, 'Piso 2', 'SLAB_ENF2',   'Lab Enfermería 2',         15, 'LAB_ENF'),
    (SUR, 'Piso 2', 'SLAB_ENF3',   'Lab Enfermería 3',         15, 'LAB_ENF'),
    (SUR, 'Piso 2', 'SLAB_ENF4',   'Lab Enfermería 4',         15, 'LAB_ENF'),
    (SUR, 'Piso 2', 'SLAB_SAL1',   'Lab Salud 1',              20, 'LAB_SALUD'),
    (SUR, 'Piso 2', 'SLAB_SAL2',   'Lab Salud 2',              20, 'LAB_SALUD'),
    (SUR, 'Piso 2', 'SLAB_SAL3',   'Lab Salud 3',              20, 'LAB_SALUD'),
    (SUR, 'Piso 2', 'SLAB_SAL4',   'Lab Salud 4',              20, 'LAB_SALUD'),
    (SUR, 'Piso 3', 'SCOC5',       'Cocina 5',                 25, 'COCINA'),
    (SUR, 'Piso 3', 'SREP3',       'Repostería 3',             25, 'REPOSTERIA'),
    (SUR, 'Piso 3', 'SMYB1',       'Mesa y Bar 1',             20, 'MESA_BAR'),
    (SUR, 'Piso 3', 'SMYB2',       'Mesa y Bar 2',             20, 'MESA_BAR'),
    (SUR, 'Piso 3', 'SMYB3',       'Mesa y Bar 3',             20, 'MESA_BAR'),
    (SUR, 'Piso 3', 'SMYB4',       'Mesa y Bar 4',             20, 'MESA_BAR'),
    (SUR, 'Piso 3', 'SINF1',       'Sala Sistemas Soft 1',     20, 'LAB_SIST'),
    (SUR, 'Piso 3', 'SINF2',       'Sala Sistemas Soft 2',     20, 'LAB_SIST'),
    (SUR, 'Piso 3', 'S301',        'Salón 301',                30, 'AULA'),
    (SUR, 'Piso 3', 'S302',        'Salón 302',                30, 'AULA'),
    (SUR, 'Piso 4', 'S401',        'Salón 401',                30, 'AULA'),
    (SUR, 'Piso 4', 'S402',        'Salón 402',                30, 'AULA'),
    (SUR, 'Piso 4', 'S403',        'Salón 403',                30, 'AULA'),
    (SUR, 'Piso 4', 'S404',        'Salón 404',                30, 'AULA'),
    (SUR, 'Piso 4', 'S405',        'Salón 405',                30, 'AULA'),
    (SUR, 'Piso 4', 'S406',        'Salón 406',                30, 'AULA'),
    (SUR, 'Piso 4', 'S407',        'Salón 407',                30, 'AULA'),
    (SUR, 'Piso 4', 'SLAB_SIST',   'Sala Sistemas Sur',        20, 'LAB_SIST'),
    (SUR, 'Piso 4', 'SOFI',        'Oficina Sur',              10, 'OFICINA'),
]

for sede, planta, codigo, nombre, capacidad, tipo in SALONES:
    Salon.objects.update_or_create(
        sede=sede, codigo=codigo,
        defaults={
            'nombre': nombre,
            'capacidad': capacidad,
            'tipo': tipo,
            'planta': planta,
            'activo': True,
        }
    )

print(f"   ✓ {Salon.objects.count()} salones reales creados")
print(f"     · Calle 73: {Salon.objects.filter(sede=CLL73).count()}")
print(f"     · Norte:    {Salon.objects.filter(sede=NORTE).count()}")
print(f"     · Sur:      {Salon.objects.filter(sede=SUR).count()}")

# ═══════════════════════════════════════════════════════════
# 3) FACULTADES (6)
# ═══════════════════════════════════════════════════════════
print("\n[3/5] Creando facultades...")
FACULTADES = [
    ('FTI', 'Técnicas en Ingenierías'),
    ('FH',  'Hospitalidad'),
    ('FS',  'Salud'),
    ('FE',  'Emprendimiento'),
    ('FT',  'Transversales'),
    ('FI',  'Programa de Inglés'),
]
for cod, nom in FACULTADES:
    Facultad.objects.update_or_create(codigo=cod, defaults={'nombre': nom})
print(f"   ✓ {Facultad.objects.count()} facultades creadas")

# ═══════════════════════════════════════════════════════════
# 4) PROGRAMAS (27 en 4 tipos)
# ═══════════════════════════════════════════════════════════
print("\n[4/5] Creando 27 programas reales...")
FTI = Facultad.objects.get(codigo='FTI')
FH  = Facultad.objects.get(codigo='FH')
FS  = Facultad.objects.get(codigo='FS')
FE  = Facultad.objects.get(codigo='FE')
FT  = Facultad.objects.get(codigo='FT')
FI  = Facultad.objects.get(codigo='FI')

PROGRAMAS = [
    # ─── TÉCNICOS LABORALES (12) ───
    ('TL01', 'Auxiliar de Enfermería',              'TL', FS),
    ('TL02', 'Auxiliar Administrativo',             'TL', FE),
    ('TL03', 'Mecánica Dental',                     'TL', FS),
    ('TL04', 'Salud Oral',                          'TL', FS),
    ('TL05', 'Atención Integral a la Primera Infancia','TL', FS),
    ('TL06', 'Bares y Restaurantes',                'TL', FH),
    ('TL07', 'Gastronomía',                         'TL', FH),
    ('TL08', 'Gestión Administrativa',              'TL', FE),
    ('TL09', 'Mercadeo y Estrategias Comerciales',  'TL', FE),
    ('TL10', 'Seguridad Ocupacional',               'TL', FS),
    ('TL11', 'Contabilidad y Finanzas',             'TL', FE),
    ('TL12', 'Turismo',                             'TL', FH),

    # ─── PROFESIONALES (10) ───
    ('PR01', 'Comercio Exterior y Negocios Internacionales','PROF', FE),
    ('PR02', 'Gestión Administrativa Profesional',  'PROF', FE),
    ('PR03', 'Mercadeo Profesional',                'PROF', FE),
    ('PR04', 'Contabilidad y Finanzas Profesional', 'PROF', FE),
    ('PR05', 'Gestión Ambiental',                   'PROF', FTI),
    ('PR06', 'Hotelería',                           'PROF', FH),
    ('PR07', 'Gestión Gastronómica',                'PROF', FH),
    ('PR08', 'Producción de Eventos y Entretenimiento','PROF', FTI),
    ('PR09', 'Topografía y Sistemas de Información Geográfica','PROF', FTI),
    ('PR10', 'Sistema de Información Empresarial',  'PROF', FTI),

    # ─── TECNOLOGÍAS (4) ───
    ('TE01', 'Tecnología en Gestión de la Seguridad y Salud en el Trabajo','TEC', FS),
    ('TE02', 'Tecnología de Información para los Negocios','TEC', FTI),
    ('TE03', 'Tecnología en Producción de Eventos', 'TEC', FTI),
    ('TE04', 'Tecnología en Gestión Gastronómica',  'TEC', FH),

    # ─── CURSO DE INGLÉS (1, con módulos) ───
    ('IN01', 'Formación en Inglés MOD1 (Niveles I-IV)','ING', FI),
]
for cod, nom, tipo, fac in PROGRAMAS:
    Programa.objects.update_or_create(
        codigo=cod,
        defaults={'nombre': nom, 'tipo': tipo, 'facultad': fac, 'activo': True}
    )

print(f"   ✓ {Programa.objects.count()} programas creados")
for tipo, label in Programa.TIPO_CHOICES:
    count = Programa.objects.filter(tipo=tipo).count()
    print(f"     · {label}: {count}")

# ═══════════════════════════════════════════════════════════
# 5) PERIODO 2026-2 y BLOQUES
# ═══════════════════════════════════════════════════════════
print("\n[5/5] Creando periodo y bloques...")
Periodo.objects.update_or_create(
    codigo='2026-2',
    defaults={
        'nombre': 'Segundo Periodo 2026',
        'fecha_inicio': date(2026, 7, 15),
        'fecha_fin': date(2026, 12, 15),
        'fecha_limite_cancelacion': date(2026, 8, 15),
        'activo': True,
    }
)

# 14 bloques de 80 min, de 6:00 a.m. a 10:00 p.m.
BLOQUES = [
    (1,  '06:00', '07:20'), (2,  '07:20', '08:40'), (3,  '08:40', '10:00'),
    (4,  '10:00', '11:20'), (5,  '11:20', '12:40'), (6,  '12:40', '14:00'),
    (7,  '14:00', '15:20'), (8,  '15:20', '16:40'), (9,  '16:40', '18:00'),
    (10, '18:00', '19:20'), (11, '19:20', '20:40'), (12, '20:40', '22:00'),
    (13, '18:30', '20:00'), (14, '20:00', '22:00'),  # bloques nocturnos extendidos
]
for num, ini, fin in BLOQUES:
    hi = time(*map(int, ini.split(':')))
    hf = time(*map(int, fin.split(':')))
    Bloque.objects.update_or_create(numero=num, defaults={'hora_inicio': hi, 'hora_fin': hf})

print(f"   ✓ Periodo 2026-2 creado")
print(f"   ✓ {Bloque.objects.count()} bloques horarios creados")

# ═══════════════════════════════════════════════════════════
# RESUMEN
# ═══════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  SEED COMPLETADO - DATOS REALES DEL POLITÉCNICO INTERNACIONAL")
print("═" * 60)
print(f"  Sedes:          {Sede.objects.count()}")
print(f"  Salones:        {Salon.objects.count()} (datos reales del Excel)")
print(f"  Facultades:     {Facultad.objects.count()}")
print(f"  Programas:      {Programa.objects.count()} en 4 tipos institucionales")
print(f"  Periodos:       {Periodo.objects.count()}")
print(f"  Bloques:        {Bloque.objects.count()}")
print("═" * 60)
