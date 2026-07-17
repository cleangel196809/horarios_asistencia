"""
SIIHAPI - Carga masiva CSV/Excel.

Implementa los RF de carga masiva del documento tecnico:
    - Estudiantes (RF-23 / RF-25)
    - Docentes   (RF-20)
    - Materias   (RF-15)
    - Horarios   (RF-30)
    - Personal   (RF-20)

Soporta CSV (.csv) y Excel (.xlsx).
Cada handler:
    1) Lee el archivo
    2) Valida cada fila
    3) Crea/actualiza registros con bulk operations
    4) Devuelve resumen: creados, actualizados, errores con detalle
"""
import csv
import io
from datetime import datetime
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction


User = get_user_model()


# ════════════════════════════════════════════════════════════════
#  Lectores universales CSV / XLSX
# ════════════════════════════════════════════════════════════════
def leer_archivo(archivo):
    """
    Lee un archivo subido (CSV o XLSX) y devuelve (cabeceras, filas).
    Los valores son strings - cada handler hace su propia validacion.
    """
    nombre = archivo.name.lower()

    if nombre.endswith('.csv'):
        return _leer_csv(archivo)
    elif nombre.endswith('.xlsx') or nombre.endswith('.xls'):
        return _leer_xlsx(archivo)
    else:
        raise ValueError(f'Formato no soportado: {nombre}. Use .csv o .xlsx')


def _leer_csv(archivo):
    # Intentar varios encodings
    raw = archivo.read()
    archivo.seek(0)
    for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('No se pudo decodificar el CSV')

    # Detectar delimitador (coma o punto y coma)
    primera_linea = text.split('\n', 1)[0]
    delim = ';' if primera_linea.count(';') > primera_linea.count(',') else ','

    reader = csv.reader(io.StringIO(text), delimiter=delim)
    cabeceras = next(reader, [])
    cabeceras = [h.strip().lower() for h in cabeceras]
    filas = [row for row in reader if any(c.strip() for c in row)]
    return cabeceras, filas


def _leer_xlsx(archivo):
    from openpyxl import load_workbook
    wb = load_workbook(archivo, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []

    cabeceras = [str(c).strip().lower() if c is not None else '' for c in rows[0]]
    filas = []
    for row in rows[1:]:
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        filas.append([str(c).strip() if c is not None else '' for c in row])
    return cabeceras, filas


# ════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════
def _get(fila, cabeceras, *nombres):
    """Busca el valor por cualquiera de los nombres de columna."""
    for nombre in nombres:
        if nombre in cabeceras:
            idx = cabeceras.index(nombre)
            if idx < len(fila):
                v = fila[idx]
                return v.strip() if isinstance(v, str) else v
    return ''


# ════════════════════════════════════════════════════════════════
#  1. ESTUDIANTES
# ════════════════════════════════════════════════════════════════
def cargar_estudiantes(archivo):
    """Carga masiva de estudiantes.

    Columnas esperadas:
        cedula, correo, nombre, apellido, programa_codigo, semestre

    Returns: dict con creados, actualizados, errores
    """
    from apps.matriculas.models import Estudiante
    from apps.academico.models import Programa

    cabeceras, filas = leer_archivo(archivo)

    if not {'correo', 'nombre', 'apellido', 'programa_codigo'}.issubset(set(cabeceras)):
        return _error_cabeceras(['cedula', 'correo', 'nombre', 'apellido', 'programa_codigo', 'semestre'], cabeceras)

    creados = 0
    actualizados = 0
    errores = []
    ahora = timezone.now()
    programas_cache = {p.codigo: p for p in Programa.objects.filter(activo=True)}

    for i, fila in enumerate(filas, start=2):
        try:
            correo = _get(fila, cabeceras, 'correo').lower()
            if not correo or '@' not in correo:
                errores.append(f'Fila {i}: correo invalido ({correo})')
                continue

            prog_cod = _get(fila, cabeceras, 'programa_codigo', 'programa')
            programa = programas_cache.get(prog_cod)
            if not programa:
                errores.append(f'Fila {i}: programa "{prog_cod}" no existe')
                continue

            cedula = _get(fila, cabeceras, 'cedula', 'documento') or correo.split('@')[0]
            nombre = _get(fila, cabeceras, 'nombre') or 'Sin nombre'
            apellido = _get(fila, cabeceras, 'apellido') or 'Sin apellido'
            try:
                semestre = int(_get(fila, cabeceras, 'semestre') or 1)
            except ValueError:
                semestre = 1

            with transaction.atomic():
                user, created = User.objects.update_or_create(
                    correo=correo,
                    defaults={
                        'nombre':    nombre,
                        'apellido':  apellido,
                        'cedula':    cedula,
                        'rol':       'ESTUDIANTE',
                        'estado':    'A',
                        'acepta_terminos': True,
                        'fecha_aceptacion_habeas_data': ahora,
                    }
                )
                if created:
                    user.set_password('Estudiante2026!')
                    user.save()

                est, est_created = Estudiante.objects.update_or_create(
                    usuario=user,
                    defaults={
                        'codigo':          cedula,
                        'programa':        programa,
                        'semestre_actual': semestre,
                        'activo':          True,
                    }
                )

            if est_created or created:
                creados += 1
            else:
                actualizados += 1

        except Exception as e:
            errores.append(f'Fila {i}: {str(e)[:200]}')

    return {
        'tipo':         'estudiantes',
        'total_filas':  len(filas),
        'creados':      creados,
        'actualizados': actualizados,
        'errores':      errores,
    }


# ════════════════════════════════════════════════════════════════
#  2. DOCENTES
# ════════════════════════════════════════════════════════════════
def cargar_docentes(archivo):
    """Carga masiva de docentes.

    Columnas: cedula, correo, nombre, apellido, tipo_contrato, carga_horaria_max
    """
    from apps.personal.models import Docente

    cabeceras, filas = leer_archivo(archivo)
    if not {'correo', 'nombre', 'apellido'}.issubset(set(cabeceras)):
        return _error_cabeceras(['cedula', 'correo', 'nombre', 'apellido', 'tipo_contrato', 'carga_horaria_max'], cabeceras)

    creados, actualizados = 0, 0
    errores = []
    ahora = timezone.now()

    for i, fila in enumerate(filas, start=2):
        try:
            correo = _get(fila, cabeceras, 'correo').lower()
            if not correo or '@' not in correo:
                errores.append(f'Fila {i}: correo invalido')
                continue
            cedula = _get(fila, cabeceras, 'cedula') or correo.split('@')[0]
            tipo = (_get(fila, cabeceras, 'tipo_contrato') or 'CATEDRA').upper()
            if tipo not in ('TC', 'MT', 'CATEDRA'):
                tipo = 'CATEDRA'
            try:
                carga = int(_get(fila, cabeceras, 'carga_horaria_max') or 20)
            except ValueError:
                carga = 20

            with transaction.atomic():
                user, c1 = User.objects.update_or_create(
                    correo=correo,
                    defaults={
                        'nombre':    _get(fila, cabeceras, 'nombre') or 'Sin nombre',
                        'apellido':  _get(fila, cabeceras, 'apellido') or 'Sin apellido',
                        'cedula':    cedula,
                        'rol':       'DOCENTE',
                        'estado':    'A',
                        'acepta_terminos': True,
                        'fecha_aceptacion_habeas_data': ahora,
                    }
                )
                if c1:
                    user.set_password('Docente2026!')
                    user.save()

                doc, c2 = Docente.objects.update_or_create(
                    usuario=user,
                    defaults={
                        'tipo_contrato':     tipo,
                        'carga_horaria_max': carga,
                        'activo':            True,
                    }
                )
            if c1 or c2:
                creados += 1
            else:
                actualizados += 1
        except Exception as e:
            errores.append(f'Fila {i}: {str(e)[:200]}')

    return {
        'tipo':         'docentes',
        'total_filas':  len(filas),
        'creados':      creados,
        'actualizados': actualizados,
        'errores':      errores,
    }


# ════════════════════════════════════════════════════════════════
#  3. MATERIAS
# ════════════════════════════════════════════════════════════════
def cargar_materias(archivo):
    """Carga masiva de materias.

    Columnas: codigo, nombre, programa_codigo, ciclo, creditos, horas_semanales
    """
    from apps.academico.models import Materia, Programa

    cabeceras, filas = leer_archivo(archivo)
    if not {'codigo', 'nombre', 'programa_codigo'}.issubset(set(cabeceras)):
        return _error_cabeceras(['codigo', 'nombre', 'programa_codigo', 'ciclo', 'creditos', 'horas_semanales'], cabeceras)

    creados, actualizados = 0, 0
    errores = []
    programas_cache = {p.codigo: p for p in Programa.objects.filter(activo=True)}

    for i, fila in enumerate(filas, start=2):
        try:
            codigo = _get(fila, cabeceras, 'codigo')
            if not codigo:
                errores.append(f'Fila {i}: codigo vacio')
                continue
            prog_cod = _get(fila, cabeceras, 'programa_codigo', 'programa')
            programa = programas_cache.get(prog_cod)
            if not programa:
                errores.append(f'Fila {i}: programa "{prog_cod}" no existe')
                continue

            try:
                ciclo = int(_get(fila, cabeceras, 'ciclo') or 1)
                creditos = int(_get(fila, cabeceras, 'creditos') or 3)
                horas = int(_get(fila, cabeceras, 'horas_semanales') or 4)
            except ValueError:
                ciclo, creditos, horas = 1, 3, 4

            _, c = Materia.objects.update_or_create(
                programa=programa, codigo=codigo,
                defaults={
                    'nombre':           _get(fila, cabeceras, 'nombre'),
                    'ciclo':            ciclo,
                    'creditos':         creditos,
                    'horas_semanales':  horas,
                    'activa':           True,
                }
            )
            if c:
                creados += 1
            else:
                actualizados += 1
        except Exception as e:
            errores.append(f'Fila {i}: {str(e)[:200]}')

    return {
        'tipo':         'materias',
        'total_filas':  len(filas),
        'creados':      creados,
        'actualizados': actualizados,
        'errores':      errores,
    }


# ════════════════════════════════════════════════════════════════
#  4. PERSONAL (usuarios administrativos / coordinadores)
# ════════════════════════════════════════════════════════════════
def cargar_personal(archivo):
    """Carga masiva de personal administrativo.

    Columnas: cedula, correo, nombre, apellido, rol (ADMINISTRADOR / COORDINADOR)
    """
    cabeceras, filas = leer_archivo(archivo)
    if not {'correo', 'nombre', 'apellido', 'rol'}.issubset(set(cabeceras)):
        return _error_cabeceras(['cedula', 'correo', 'nombre', 'apellido', 'rol'], cabeceras)

    creados, actualizados = 0, 0
    errores = []
    ahora = timezone.now()

    for i, fila in enumerate(filas, start=2):
        try:
            correo = _get(fila, cabeceras, 'correo').lower()
            if not correo or '@' not in correo:
                errores.append(f'Fila {i}: correo invalido')
                continue

            rol = _get(fila, cabeceras, 'rol').upper()
            if rol not in ('ADMINISTRADOR', 'COORDINADOR'):
                errores.append(f'Fila {i}: rol invalido "{rol}" (usa ADMINISTRADOR o COORDINADOR)')
                continue

            user, c = User.objects.update_or_create(
                correo=correo,
                defaults={
                    'nombre':    _get(fila, cabeceras, 'nombre') or 'Sin nombre',
                    'apellido':  _get(fila, cabeceras, 'apellido') or 'Sin apellido',
                    'cedula':    _get(fila, cabeceras, 'cedula') or correo.split('@')[0],
                    'rol':       rol,
                    'estado':    'A',
                    'is_staff':  True,
                    'is_superuser': rol == 'ADMINISTRADOR',
                    'acepta_terminos': True,
                    'fecha_aceptacion_habeas_data': ahora,
                }
            )
            if c:
                user.set_password(f'{rol.title()}2026!')
                user.save()
                creados += 1
            else:
                actualizados += 1
        except Exception as e:
            errores.append(f'Fila {i}: {str(e)[:200]}')

    return {
        'tipo':         'personal',
        'total_filas':  len(filas),
        'creados':      creados,
        'actualizados': actualizados,
        'errores':      errores,
    }


# ════════════════════════════════════════════════════════════════
#  5. HORARIOS (carga manual de horarios pre-aprobados)
# ════════════════════════════════════════════════════════════════
def cargar_horarios(archivo):
    """Carga masiva de horarios.

    Columnas: matricula_id, materia_codigo, docente_correo, salon_codigo,
              dia (LU/MA/MI/JU/VI/SA), bloque (1-14)
    """
    from apps.horarios.models import Horario, Bloque
    from apps.academico.models import Materia
    from apps.personal.models import Docente
    from apps.infraestructura.models import Salon
    from apps.matriculas.models import Matricula

    cabeceras, filas = leer_archivo(archivo)
    requerido = {'matricula_id', 'materia_codigo', 'docente_correo', 'salon_codigo', 'dia', 'bloque'}
    if not requerido.issubset(set(cabeceras)):
        return _error_cabeceras(list(requerido), cabeceras)

    creados, actualizados = 0, 0
    errores = []

    bloques_cache = {b.numero: b for b in Bloque.objects.all()}
    materias_cache = {m.codigo: m for m in Materia.objects.all()}
    salones_cache = {s.codigo: s for s in Salon.objects.all()}

    for i, fila in enumerate(filas, start=2):
        try:
            mat_id = _get(fila, cabeceras, 'matricula_id')
            mat = Matricula.objects.filter(id_matricula=mat_id).first()
            if not mat:
                errores.append(f'Fila {i}: matricula {mat_id} no existe')
                continue

            materia = materias_cache.get(_get(fila, cabeceras, 'materia_codigo'))
            if not materia:
                errores.append(f'Fila {i}: materia no existe')
                continue

            doc_correo = _get(fila, cabeceras, 'docente_correo').lower()
            docente = Docente.objects.filter(usuario__correo=doc_correo).first()
            if not docente:
                errores.append(f'Fila {i}: docente {doc_correo} no existe')
                continue

            salon = salones_cache.get(_get(fila, cabeceras, 'salon_codigo'))
            if not salon:
                errores.append(f'Fila {i}: salon no existe')
                continue

            try:
                bloque_num = int(_get(fila, cabeceras, 'bloque'))
            except ValueError:
                errores.append(f'Fila {i}: bloque invalido')
                continue

            bloque = bloques_cache.get(bloque_num)
            if not bloque:
                errores.append(f'Fila {i}: bloque {bloque_num} no existe')
                continue

            dia = _get(fila, cabeceras, 'dia').upper()
            if dia not in ('LU', 'MA', 'MI', 'JU', 'VI', 'SA'):
                errores.append(f'Fila {i}: dia "{dia}" invalido')
                continue

            _, c = Horario.objects.update_or_create(
                matricula=mat, dia=dia, bloque=bloque,
                defaults={
                    'materia': materia,
                    'docente': docente,
                    'salon':   salon,
                    'estado':  'APROBADO',  # carga manual = ya aprobado
                }
            )
            if c:
                creados += 1
            else:
                actualizados += 1

        except Exception as e:
            errores.append(f'Fila {i}: {str(e)[:200]}')

    return {
        'tipo':         'horarios',
        'total_filas':  len(filas),
        'creados':      creados,
        'actualizados': actualizados,
        'errores':      errores,
    }


# ════════════════════════════════════════════════════════════════
#  Helpers comunes
# ════════════════════════════════════════════════════════════════
# Firmas minimas de cabeceras por tipo (para auto-deteccion)
_FIRMAS_TIPO = {
    'estudiantes': {'correo', 'nombre', 'apellido', 'programa_codigo'},
    'docentes':    {'correo', 'nombre', 'apellido', 'tipo_contrato'},
    'materias':    {'codigo', 'nombre', 'programa_codigo'},
    'personal':    {'correo', 'nombre', 'apellido', 'rol'},
    'horarios':    {'matricula_id', 'materia_codigo', 'dia', 'bloque'},
    # formato del Motor IA (codigo_materia/hora) -> sugerir usar el Motor IA
    'horarios_ia': {'codigo_materia', 'dia', 'hora_inicio'},
}


def _detectar_tipo(encontradas):
    """Devuelve el tipo cuyas cabeceras coinciden mejor con las del archivo."""
    cab = {str(c).strip().lower() for c in encontradas}
    mejor, score = None, 0
    for tipo, firma in _FIRMAS_TIPO.items():
        inter = len(firma & cab)
        if inter > score and inter >= max(2, len(firma) - 1):
            mejor, score = tipo, inter
    return mejor


def _error_cabeceras(requeridas, encontradas):
    errores = [
        f'Cabeceras del archivo: {", ".join(encontradas) or "(vacias)"}',
        f'Cabeceras requeridas: {", ".join(requeridas)}',
    ]
    detectado = _detectar_tipo(encontradas)
    if detectado == 'horarios_ia':
        errores.append('💡 Tu archivo parece del formato del Motor IA (codigo_materia, hora_inicio…). '
                       'Súbelo en "Motor IA" para que la IA lo procese, no en Carga Masiva.')
    elif detectado:
        errores.append(f'💡 Estas cabeceras parecen ser del tipo "{detectado.upper()}". '
                       f'Cambia el selector "Tipo de carga" a "{detectado}" e inténtalo de nuevo.')
    else:
        errores.append('Renombra las columnas o usa la plantilla de ejemplo del tipo correcto.')
    return {
        'tipo':         'ERROR',
        'total_filas':  0,
        'creados':      0,
        'actualizados': 0,
        'errores':      errores,
    }


HANDLERS = {
    'estudiantes': cargar_estudiantes,
    'docentes':    cargar_docentes,
    'materias':    cargar_materias,
    'personal':    cargar_personal,
    'horarios':    cargar_horarios,
}


def plantilla_csv(tipo):
    """Devuelve el contenido de una plantilla CSV de ejemplo."""
    plantillas = {
        'estudiantes': (
            'cedula,correo,nombre,apellido,programa_codigo,semestre\n'
            '1018501234,juan.perez@pi.edu.co,Juan,Perez,TL01,3\n'
            '1018501235,ana.gomez@pi.edu.co,Ana,Gomez,TL07,2\n'
        ),
        'docentes': (
            'cedula,correo,nombre,apellido,tipo_contrato,carga_horaria_max\n'
            '52567890,maria.rodriguez@pi.edu.co,Maria,Rodriguez,TC,40\n'
            '79456123,carlos.sanchez@pi.edu.co,Carlos,Sanchez,MT,20\n'
            '12345678,ana.lopez@pi.edu.co,Ana,Lopez,CATEDRA,12\n'
        ),
        'materias': (
            'codigo,nombre,programa_codigo,ciclo,creditos,horas_semanales\n'
            'TL01-M01,Anatomia Basica,TL01,1,3,4\n'
            'TL01-M02,Farmacologia,TL01,2,3,4\n'
            'TL07-M01,Tecnicas Culinarias,TL07,1,4,6\n'
        ),
        'personal': (
            'cedula,correo,nombre,apellido,rol\n'
            '11111111,coord1@pi.edu.co,Coordinador,Uno,COORDINADOR\n'
            '22222222,admin1@pi.edu.co,Admin,Uno,ADMINISTRADOR\n'
        ),
        'horarios': (
            'matricula_id,materia_codigo,docente_correo,salon_codigo,dia,bloque\n'
            '1,TL01-M01,docente01@pi.edu.co,301,LU,3\n'
            '2,TL07-M01,docente02@pi.edu.co,COC1,MA,5\n'
        ),
    }
    return plantillas.get(tipo, '')
