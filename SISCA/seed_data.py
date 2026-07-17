"""
SISCA — Seed Data: Ingeniería de Software
Pobla la BD con datos reales de prueba:
  - 2 Administradores adicionales
  - 5 Docentes con especialidades
  - 20 Estudiantes
  - 8 Materias de Ing. Software (semestres 1-8)
  - Horarios por materia
  - Inscripciones de estudiantes
Ejecutar: python seed_data.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()

import oracledb
import bcrypt

HOST = os.getenv('ORACLE_HOST', 'localhost')
PORT = os.getenv('ORACLE_PORT', '1521')
SID  = os.getenv('ORACLE_SID', 'XEPDB1')
USER = os.getenv('ORACLE_USER', 'sisca_admin')
PWD  = os.getenv('ORACLE_PASSWORD', 'fjnv1305')
DSN  = f"{HOST}:{PORT}/{SID}"

def hp(plain): return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def bar(t=''): print('-'*55); print(f'  {t}') if t else None

print('='*55)
print('  SISCA — Carga de Datos · Ing. de Software')
print('='*55)

conn = oracledb.connect(user=USER, password=PWD, dsn=DSN)
cur  = conn.cursor()
print(f'  Conectado a Oracle XE: {DSN}\n')

# ════════════════════════════════════════════════════════
# 0. Limpiar datos existentes (excepto el admin original)
# ════════════════════════════════════════════════════════
bar('Limpiando datos de prueba anteriores...')
tablas = [
    'ALERTA_INASISTENCIA','SINCRONIZACION','SERVIDOR_LOCAL',
    'AUDITORIA','JUSTIFICACION','ASISTENCIA','CODIGO_QR',
    'SESION_CLASE','INSCRIPCION','HORARIO','MATERIA','CARRERA',
    'ESTUDIANTE','DOCENTE','ADMINISTRADOR',
]
for t in tablas:
    try:
        cur.execute(f"DELETE FROM {t}")
        conn.commit()
        print(f'  Limpiado: {t}')
    except Exception as e:
        conn.rollback()
        print(f'  Skip {t}: {e}')

# Eliminar usuarios que no sean el admin original
try:
    cur.execute("DELETE FROM USUARIO WHERE ID_USUARIO > 1")
    conn.commit()
    print('  Usuarios adicionales eliminados.')
except:
    conn.rollback()

# Re-insertar el admin original
try:
    cur.execute("SELECT COUNT(*) FROM USUARIO WHERE ID_USUARIO=1")
    if cur.fetchone()[0] == 0:
        cur.execute("""INSERT INTO USUARIO(ESTADO,NOMBRE,APELLIDO,CORREO,CONTRASENA,ROL,ACEPTA_TERMINOS)
            VALUES('A','Administrador','SISCA','admin@politecnico.edu.co',:p,'ADMINISTRADOR','S')""",
            {'p': hp('Admin2026!')})
        conn.commit()
    cur.execute("SELECT ID_USUARIO FROM USUARIO WHERE CORREO='admin@politecnico.edu.co'")
    r = cur.fetchone()
    orig_admin_id = r[0] if r else None
    if orig_admin_id:
        cur.execute("INSERT INTO ADMINISTRADOR(ID_USUARIO,NIVEL_ACCESO) VALUES(:id,'TOTAL')", {'id': orig_admin_id})
        conn.commit()
except Exception as e:
    conn.rollback()
    print(f'  Admin original: {e}')

# ════════════════════════════════════════════════════════
# 1. ADMINISTRADORES
# ════════════════════════════════════════════════════════
bar('Creando Administradores...')

admins = [
    ('Carlos',   'Mendoza',     'carlos.mendoza@politecnico.edu.co',   'Carlos2026!',   'TOTAL'),
    ('Patricia', 'Rodríguez',   'patricia.rodriguez@politecnico.edu.co','Patricia2026!', 'PARCIAL'),
]

admin_ids = {}
for nombre, apellido, correo, clave, nivel in admins:
    try:
        cur.execute("""INSERT INTO USUARIO(ESTADO,NOMBRE,APELLIDO,CORREO,CONTRASENA,ROL,ACEPTA_TERMINOS)
            VALUES('A',:n,:a,:c,:p,'ADMINISTRADOR','S')""",
            {'n':nombre,'a':apellido,'c':correo,'p':hp(clave)})
        conn.commit()
        cur.execute("SELECT ID_USUARIO FROM USUARIO WHERE CORREO=:c", {'c':correo})
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO ADMINISTRADOR(ID_USUARIO,NIVEL_ACCESO) VALUES(:id,:nv)", {'id':uid,'nv':nivel})
        conn.commit()
        admin_ids[correo] = uid
        print(f'  Admin: {nombre} {apellido} | {correo} | Clave: {clave}')
    except Exception as e:
        conn.rollback()
        print(f'  ERROR Admin {nombre}: {e}')

# ════════════════════════════════════════════════════════
# 2. DOCENTES
# ════════════════════════════════════════════════════════
bar('Creando Docentes...')

docentes_data = [
    ('Andrés',    'García',    'andres.garcia@politecnico.edu.co',    'Garcia2026!',    'Ingeniería de Software',       '3001234501'),
    ('Lucía',     'Martínez',  'lucia.martinez@politecnico.edu.co',   'Martinez2026!',  'Base de Datos y Sistemas',     '3001234502'),
    ('Fernando',  'López',     'fernando.lopez@politecnico.edu.co',   'Lopez2026!',     'Redes y Seguridad Informática','3001234503'),
    ('Daniela',   'Vargas',    'daniela.vargas@politecnico.edu.co',   'Vargas2026!',    'Inteligencia Artificial',      '3001234504'),
    ('Sebastián', 'Torres',    'sebastian.torres@politecnico.edu.co', 'Torres2026!',    'Matemáticas y Estadística',    '3001234505'),
]

docente_ids = {}
for nombre, apellido, correo, clave, esp, tel in docentes_data:
    try:
        cur.execute("""INSERT INTO USUARIO(ESTADO,NOMBRE,APELLIDO,CORREO,CONTRASENA,ROL,ACEPTA_TERMINOS)
            VALUES('A',:n,:a,:c,:p,'DOCENTE','S')""",
            {'n':nombre,'a':apellido,'c':correo,'p':hp(clave)})
        conn.commit()
        cur.execute("SELECT ID_USUARIO FROM USUARIO WHERE CORREO=:c", {'c':correo})
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO DOCENTE(ID_USUARIO,ESPECIALIDAD,TELEFONO) VALUES(:id,:e,:t)",
            {'id':uid,'e':esp,'t':tel})
        conn.commit()
        cur.execute("SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO=:id", {'id':uid})
        did = cur.fetchone()[0]
        docente_ids[correo] = did
        print(f'  Docente: {nombre} {apellido} | {correo} | Clave: {clave}')
    except Exception as e:
        conn.rollback()
        print(f'  ERROR Docente {nombre}: {e}')

# ════════════════════════════════════════════════════════
# 3. CARRERA — Ingeniería de Software
# ════════════════════════════════════════════════════════
bar('Creando Carrera...')
try:
    # La carrera "Ingenieria de Sistemas" ya existe del setup, creamos "Ing. Software"
    cur.execute("""INSERT INTO CARRERA(NOMBRE_CARRERA,FACULTAD,CODIGO_CARRERA)
        VALUES('Ingeniería de Software','Ingeniería y Tecnología','ING-SW')""")
    conn.commit()
    cur.execute("SELECT ID_CARRERA FROM CARRERA WHERE CODIGO_CARRERA='ING-SW'")
    id_carrera = cur.fetchone()[0]
    print(f'  Carrera: Ingeniería de Software (ID:{id_carrera})')
except Exception as e:
    conn.rollback()
    print(f'  Carrera existente o error: {e}')
    cur.execute("SELECT ID_CARRERA FROM CARRERA WHERE CODIGO_CARRERA='ING-SW'")
    r = cur.fetchone()
    id_carrera = r[0] if r else 1

# ════════════════════════════════════════════════════════
# 4. MATERIAS — Ingeniería de Software (8 semestres)
# ════════════════════════════════════════════════════════
bar('Creando Materias...')

# (nombre, codigo, creditos, semestre, pct_min, docente_correo)
docente_list = list(docente_ids.keys())
materias_data = [
    # Semestre 1
    ('Fundamentos de Programación',       'PROG-101', 4, 1, 75.0, docente_list[0] if len(docente_list)>0 else None),
    ('Matemáticas Discretas',             'MASD-101', 3, 1, 75.0, docente_list[4] if len(docente_list)>4 else None),
    ('Introducción a la Ing. de Software','IISW-101', 3, 1, 80.0, docente_list[0] if len(docente_list)>0 else None),
    # Semestre 2
    ('Estructuras de Datos',              'ESTR-201', 4, 2, 75.0, docente_list[0] if len(docente_list)>0 else None),
    ('Bases de Datos I',                  'BDAI-201', 4, 2, 80.0, docente_list[1] if len(docente_list)>1 else None),
    ('Cálculo Diferencial',               'CALC-201', 3, 2, 70.0, docente_list[4] if len(docente_list)>4 else None),
    # Semestre 3
    ('Programación Orientada a Objetos',  'POOG-301', 4, 3, 80.0, docente_list[0] if len(docente_list)>0 else None),
    ('Bases de Datos II',                 'BDII-301', 4, 3, 80.0, docente_list[1] if len(docente_list)>1 else None),
    # Semestre 4
    ('Ingeniería de Requisitos',          'REQR-401', 3, 4, 80.0, docente_list[0] if len(docente_list)>0 else None),
    ('Redes de Computadores',             'RECO-401', 3, 4, 75.0, docente_list[2] if len(docente_list)>2 else None),
    # Semestre 5
    ('Arquitectura de Software',          'ARCS-501', 3, 5, 80.0, docente_list[0] if len(docente_list)>0 else None),
    ('Seguridad Informática',             'SECU-501', 3, 5, 80.0, docente_list[2] if len(docente_list)>2 else None),
    # Semestre 6
    ('Desarrollo Web y Móvil',            'WEBM-601', 4, 6, 75.0, docente_list[1] if len(docente_list)>1 else None),
    ('Pruebas de Software',               'TEST-601', 3, 6, 80.0, docente_list[0] if len(docente_list)>0 else None),
    # Semestre 7
    ('Inteligencia Artificial',           'INTA-701', 3, 7, 75.0, docente_list[3] if len(docente_list)>3 else None),
    ('Gestión de Proyectos TI',           'GPTI-701', 3, 7, 80.0, docente_list[0] if len(docente_list)>0 else None),
    # Semestre 8
    ('Trabajo de Grado I',                'TGRA-801', 6, 8, 90.0, docente_list[0] if len(docente_list)>0 else None),
    ('Ética y Legislación TI',            'ETIC-801', 2, 8, 75.0, docente_list[4] if len(docente_list)>4 else None),
]

materia_ids = {}
for nombre, codigo, creditos, sem, pct, doc_correo in materias_data:
    try:
        did = docente_ids.get(doc_correo) if doc_correo else None
        cur.execute("""INSERT INTO MATERIA(NOMBRE_MATERIA,CODIGO,CREDITOS,SEMESTRE,PORCENTAJE_MIN,ID_CARRERA,ID_DOCENTE)
            VALUES(:n,:c,:cr,:s,:p,:ic,:id)""",
            {'n':nombre,'c':codigo,'cr':creditos,'s':sem,'p':pct,'ic':id_carrera,'id':did})
        conn.commit()
        cur.execute("SELECT ID_MATERIA FROM MATERIA WHERE CODIGO=:c", {'c':codigo})
        mid = cur.fetchone()[0]
        materia_ids[codigo] = mid
        print(f'  Sem{sem}: {nombre} ({codigo}) | Docente ID:{did}')
    except Exception as e:
        conn.rollback()
        print(f'  ERROR Materia {nombre}: {e}')

# ════════════════════════════════════════════════════════
# 5. HORARIOS
# ════════════════════════════════════════════════════════
bar('Creando Horarios...')

# (codigo_materia, dia, hora_inicio, hora_fin, aula)
horarios_data = [
    ('PROG-101', 'LUNES',     '07:00', '09:00', 'Sala 101'),
    ('PROG-101', 'MIERCOLES', '07:00', '09:00', 'Sala 101'),
    ('MASD-101', 'MARTES',    '09:00', '11:00', 'Aula 201'),
    ('MASD-101', 'JUEVES',    '09:00', '11:00', 'Aula 201'),
    ('IISW-101', 'VIERNES',   '07:00', '10:00', 'Sala 103'),
    ('ESTR-201', 'LUNES',     '11:00', '13:00', 'Lab Sistemas 1'),
    ('ESTR-201', 'MIERCOLES', '11:00', '13:00', 'Lab Sistemas 1'),
    ('BDAI-201', 'MARTES',    '14:00', '16:00', 'Lab BD'),
    ('BDAI-201', 'JUEVES',    '14:00', '16:00', 'Lab BD'),
    ('CALC-201', 'VIERNES',   '10:00', '13:00', 'Aula 301'),
    ('POOG-301', 'LUNES',     '07:00', '09:00', 'Lab Sistemas 2'),
    ('POOG-301', 'MIERCOLES', '07:00', '09:00', 'Lab Sistemas 2'),
    ('BDII-301', 'MARTES',    '07:00', '09:00', 'Lab BD'),
    ('BDII-301', 'JUEVES',    '07:00', '09:00', 'Lab BD'),
    ('REQR-401', 'LUNES',     '14:00', '17:00', 'Sala 401'),
    ('RECO-401', 'MARTES',    '11:00', '14:00', 'Lab Redes'),
    ('ARCS-501', 'MIERCOLES', '14:00', '17:00', 'Sala 501'),
    ('SECU-501', 'JUEVES',    '14:00', '17:00', 'Lab Redes'),
    ('WEBM-601', 'LUNES',     '09:00', '11:00', 'Lab Sistemas 3'),
    ('WEBM-601', 'MIERCOLES', '09:00', '11:00', 'Lab Sistemas 3'),
    ('TEST-601', 'VIERNES',   '14:00', '17:00', 'Sala 601'),
    ('INTA-701', 'MARTES',    '16:00', '19:00', 'Lab IA'),
    ('GPTI-701', 'JUEVES',    '16:00', '19:00', 'Sala 701'),
    ('TGRA-801', 'SABADO',    '07:00', '13:00', 'Auditorium'),
    ('ETIC-801', 'SABADO',    '13:00', '15:00', 'Sala 801'),
]

horario_ids_by_materia = {}  # codigo -> lista de id_horario
for cod, dia, hi, hf, aula in horarios_data:
    mid = materia_ids.get(cod)
    if not mid:
        print(f'  SKIP horario {cod}: materia no encontrada')
        continue
    hi_ts = f"01/01/2026 {hi}:00"
    hf_ts = f"01/01/2026 {hf}:00"
    try:
        cur.execute("""INSERT INTO HORARIO(ID_MATERIA,HORA_INICIO,HORA_FIN,DIA,AULA)
            VALUES(:im,TO_TIMESTAMP(:hi,'DD/MM/YYYY HH24:MI:SS'),
                   TO_TIMESTAMP(:hf,'DD/MM/YYYY HH24:MI:SS'),:d,:a)""",
            {'im':mid,'hi':hi_ts,'hf':hf_ts,'d':dia,'a':aula})
        conn.commit()
        cur.execute("""SELECT ID_HORARIO FROM HORARIO WHERE ID_MATERIA=:im AND DIA=:d
            AND HORA_INICIO=TO_TIMESTAMP(:hi,'DD/MM/YYYY HH24:MI:SS')""",
            {'im':mid,'d':dia,'hi':hi_ts})
        hid = cur.fetchone()[0]
        horario_ids_by_materia.setdefault(cod, []).append(hid)
        print(f'  Horario: {cod} | {dia} {hi}-{hf} | {aula}')
    except Exception as e:
        conn.rollback()
        print(f'  ERROR Horario {cod} {dia}: {e}')

# ════════════════════════════════════════════════════════
# 6. ESTUDIANTES (20 estudiantes)
# ════════════════════════════════════════════════════════
bar('Creando Estudiantes...')

estudiantes_data = [
    # (nombre, apellido, correo, clave, semestre, codigo)
    ('Santiago',   'Pérez',      'santiago.perez@politecnico.edu.co',    'Perez2026!',    1, 20260001),
    ('Valentina',  'Gómez',      'valentina.gomez@politecnico.edu.co',   'Gomez2026!',    1, 20260002),
    ('Miguel',     'Hernández',  'miguel.hernandez@politecnico.edu.co',  'Hernandez2026!',1, 20260003),
    ('Isabella',   'Castro',     'isabella.castro@politecnico.edu.co',   'Castro2026!',   1, 20260004),
    ('Tomás',      'Morales',    'tomas.morales@politecnico.edu.co',     'Morales2026!',  2, 20250001),
    ('Camila',     'Jiménez',    'camila.jimenez@politecnico.edu.co',    'Jimenez2026!',  2, 20250002),
    ('Daniel',     'Ramírez',    'daniel.ramirez@politecnico.edu.co',    'Ramirez2026!',  2, 20250003),
    ('Salomé',     'Torres',     'salome.torres@politecnico.edu.co',     'Torres2026!',   2, 20250004),
    ('Sebastián',  'Vargas',     'sebastian.vargas@politecnico.edu.co',  'Vargas2026!',   3, 20240001),
    ('Mariana',    'López',      'mariana.lopez@politecnico.edu.co',     'Lopez2026!',    3, 20240002),
    ('Alejandro',  'Martínez',   'alejandro.martinez@politecnico.edu.co','Martinez2026!', 3, 20240003),
    ('Juliana',    'Sánchez',    'juliana.sanchez@politecnico.edu.co',   'Sanchez2026!',  3, 20240004),
    ('Nicolás',    'Díaz',       'nicolas.diaz@politecnico.edu.co',      'Diaz2026!',     4, 20230001),
    ('Gabriela',   'Reyes',      'gabriela.reyes@politecnico.edu.co',    'Reyes2026!',    4, 20230002),
    ('Samuel',     'González',   'samuel.gonzalez@politecnico.edu.co',   'Gonzalez2026!', 5, 20220001),
    ('Luciana',    'Herrera',    'luciana.herrera@politecnico.edu.co',   'Herrera2026!',  5, 20220002),
    ('David',      'Medina',     'david.medina@politecnico.edu.co',      'Medina2026!',   6, 20210001),
    ('Sara',       'Guerrero',   'sara.guerrero@politecnico.edu.co',     'Guerrero2026!', 6, 20210002),
    ('Mateo',      'Navarro',    'mateo.navarro@politecnico.edu.co',     'Navarro2026!',  7, 20200001),
    ('Paula',      'Romero',     'paula.romero@politecnico.edu.co',      'Romero2026!',   8, 20190001),
]

estudiante_ids = []
for nombre, apellido, correo, clave, sem, codigo in estudiantes_data:
    try:
        cur.execute("""INSERT INTO USUARIO(ESTADO,NOMBRE,APELLIDO,CORREO,CONTRASENA,ROL,ACEPTA_TERMINOS)
            VALUES('A',:n,:a,:c,:p,'ESTUDIANTE','S')""",
            {'n':nombre,'a':apellido,'c':correo,'p':hp(clave)})
        conn.commit()
        cur.execute("SELECT ID_USUARIO FROM USUARIO WHERE CORREO=:c", {'c':correo})
        uid = cur.fetchone()[0]
        cur.execute("""INSERT INTO ESTUDIANTE(ID_USUARIO,SEMESTRE,CODIGO_ESTUDIANTE)
            VALUES(:id,:s,:cod)""", {'id':uid,'s':sem,'cod':codigo})
        conn.commit()
        cur.execute("SELECT ID_ESTUDIANTE FROM ESTUDIANTE WHERE ID_USUARIO=:id", {'id':uid})
        eid = cur.fetchone()[0]
        estudiante_ids.append({'id': eid, 'sem': sem, 'nombre': f'{nombre} {apellido}', 'clave': clave, 'correo': correo})
        print(f'  Estudiante sem{sem}: {nombre} {apellido} | {correo} | Cod:{codigo} | Clave:{clave}')
    except Exception as e:
        conn.rollback()
        print(f'  ERROR Estudiante {nombre}: {e}')

# ════════════════════════════════════════════════════════
# 7. INSCRIPCIONES (por semestre)
# ════════════════════════════════════════════════════════
bar('Creando Inscripciones...')

# Materias por semestre
mats_x_sem = {}
for cod, (nombre, _, creditos, sem, pct, _2) in zip(
    [m[1] for m in materias_data], materias_data):
    mats_x_sem.setdefault(sem, []).append(materia_ids.get(cod))

inscripciones = 0
for est in estudiante_ids:
    eid = est['id']
    sem = est['sem']
    # Inscribir en materias del semestre actual y anteriores
    for s in range(max(1, sem-1), sem+1):
        mids = mats_x_sem.get(s, [])
        for mid in mids:
            if not mid: continue
            try:
                cur.execute("""INSERT INTO INSCRIPCION(ID_ESTUDIANTE,ID_MATERIA,SEMESTRE,ESTADO)
                    VALUES(:e,:m,:s,'ACTIVA')""", {'e':eid,'m':mid,'s':s})
                conn.commit()
                inscripciones += 1
            except Exception:
                conn.rollback()

print(f'  Total inscripciones creadas: {inscripciones}')

# ════════════════════════════════════════════════════════
# 8. RESUMEN FINAL
# ════════════════════════════════════════════════════════
conn.close()

print('\n' + '='*55)
print('  DATOS CARGADOS EXITOSAMENTE')
print('='*55)

print('\n  ADMINISTRADORES:')
print('  admin@politecnico.edu.co              / Admin2026!')
for nombre, apellido, correo, clave, _ in admins:
    print(f'  {correo:<45}/ {clave}')

print('\n  DOCENTES:')
for nombre, apellido, correo, clave, esp, _ in docentes_data:
    print(f'  {correo:<45}/ {clave}')

print('\n  ESTUDIANTES (muestra):')
for e in estudiantes_data[:5]:
    print(f'  {e[2]:<45}/ {e[3]}')
print(f'  ... y {len(estudiantes_data)-5} mas')

print(f'\n  MATERIAS   : {len(materia_ids)} (8 semestres Ing. Software)')
print(f'  HORARIOS   : {sum(len(v) for v in horario_ids_by_materia.values())}')
print(f'  ESTUDIANTES: {len(estudiante_ids)}')
print(f'  INSCRIPCIONES: {inscripciones}')
print('='*55)
print('  Inicia el servidor: python run.py')
print('='*55)
