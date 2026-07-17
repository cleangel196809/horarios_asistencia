"""
SIIHAPI - Pipeline de analisis IA de archivos de horarios.

Orquesta todo el flujo senior:
  1. Hash del archivo → consulta cache (evita llamadas LLM redundantes)
  2. Parse del archivo (CSV/XLSX/PDF/DOCX)
  3. Llamada LLM para extraer/normalizar datos
  4. Validacion con schemas (HorarioExtraido)
  5. Routing por confianza:
       >= 75% → crear PROPUESTO automaticamente
       <  75% → devolver para revision manual
  6. Guardar en BD solo filas validas
  7. Log de AsignacionIA con metricas completas

Uso:
    from siihapi.motor_ia.pipeline import analizar_archivo_pipeline
    resultado = analizar_archivo_pipeline(archivo_bytes, nombre, periodo, usuario)
"""
import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ─── Importaciones con fallback ───────────────────────────────────────────────

_PALABRAS_CABECERA = ['asignatura', 'materia', 'codigo', 'profesor', 'docente',
                      'dia', 'hora', 'creditos', 'programa', 'grupo', 'salon',
                      'matricula', 'correo', 'ciclo', 'nombre']

def _detectar_fila_encabezado(filas):
    """Encuentra el indice de la fila que es el ENCABEZADO real (la que tiene mas
    palabras clave conocidas). Permite saltar preambulos (titulos, filas en blanco)."""
    mejor_idx, mejor_score = None, 0
    for i, fila in enumerate(filas[:25]):
        celdas = [str(c or '').strip().lower() for c in fila]
        score = sum(1 for c in celdas for kw in _PALABRAS_CABECERA if kw in c)
        no_vacias = sum(1 for c in celdas if c)
        if no_vacias >= 3 and score > mejor_score:
            mejor_score, mejor_idx = score, i
    return mejor_idx if mejor_score >= 2 else (0 if filas else None)


def _leer_archivo(contenido: bytes, nombre: str) -> List[dict]:
    """Convierte bytes del archivo a lista de dicts con columnas raw."""
    nombre_lower = nombre.lower()
    try:
        if nombre_lower.endswith('.csv'):
            import csv, io
            texto = contenido.decode('utf-8-sig', errors='replace')
            lineas_txt = texto.splitlines()
            primera = lineas_txt[0] if lineas_txt else ''
            try:
                delim = csv.Sniffer().sniff(texto[:2048], delimiters=',;\t').delimiter
            except Exception:
                delim = max([',', ';', '\t'], key=lambda d: primera.count(d))
            todas = list(csv.reader(io.StringIO(texto), delimiter=delim))
            cab_idx = _detectar_fila_encabezado(todas)
            if cab_idx is None:
                return []
            headers = [str(c or '').strip() for c in todas[cab_idx]]
            rows = []
            for fila in todas[cab_idx + 1:]:
                if not any((str(c or '').strip()) for c in fila):
                    continue
                rows.append({headers[i]: (str(fila[i]).strip() if i < len(fila) else '')
                             for i in range(len(headers))})
            return rows
        elif nombre_lower.endswith(('.xlsx', '.xls')):
            import openpyxl, io
            wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
            rows_total = []
            for ws in wb.worksheets:  # leer TODAS las hojas (sesiones)
                matriz = [[str(c.value).strip() if c.value is not None else '' for c in row]
                          for row in ws.iter_rows(values_only=False)]
                cab_idx = _detectar_fila_encabezado(matriz)
                if cab_idx is None:
                    continue
                headers = matriz[cab_idx]
                for fila in matriz[cab_idx + 1:]:
                    if not any(fila):
                        continue
                    rows_total.append({headers[i]: (fila[i] if i < len(fila) else '')
                                       for i in range(len(headers))})
            return rows_total
        elif nombre_lower.endswith('.pdf'):
            try:
                import pdfplumber, io as _io
                texto_completo = ''
                with pdfplumber.open(_io.BytesIO(contenido)) as pdf:
                    for page in pdf.pages:
                        texto_completo += (page.extract_text() or '') + '\n'
                return [{'texto_raw': texto_completo}]
            except Exception:
                import pypdf, io as _io2
                reader = pypdf.PdfReader(_io2.BytesIO(contenido))
                texto = '\n'.join(p.extract_text() or '' for p in reader.pages)
                return [{'texto_raw': texto}]
        elif nombre_lower.endswith(('.docx', '.doc')):
            import docx, io as _io3
            doc = docx.Document(_io3.BytesIO(contenido))
            texto = '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
            return [{'texto_raw': texto}]
        else:
            return []
    except Exception as exc:
        log.error(f"[Pipeline] Error leyendo archivo '{nombre}': {exc}")
        return []


_DIA_NORM = {
    'lu': 'LUNES', 'lun': 'LUNES', 'lunes': 'LUNES', 'l': 'LUNES',
    'ma': 'MARTES', 'mar': 'MARTES', 'martes': 'MARTES',
    'mi': 'MIERCOLES', 'mie': 'MIERCOLES', 'mier': 'MIERCOLES',
    'miercoles': 'MIERCOLES', 'x': 'MIERCOLES',
    'ju': 'JUEVES', 'jue': 'JUEVES', 'jueves': 'JUEVES', 'j': 'JUEVES',
    'vi': 'VIERNES', 'vie': 'VIERNES', 'viernes': 'VIERNES', 'v': 'VIERNES',
    'sa': 'SABADO', 'sab': 'SABADO', 'sabado': 'SABADO', 's': 'SABADO',
    'do': 'DOMINGO', 'dom': 'DOMINGO', 'domingo': 'DOMINGO', 'd': 'DOMINGO',
}


def _normalizar_dia(valor: str) -> str:
    """Convierte 'LU','Lun','Miércoles', etc. al nombre canonico (LUNES...)."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(valor or '')).encode('ascii', 'ignore').decode('ascii')
    s = s.strip().lower()
    if not s:
        return ''
    return _DIA_NORM.get(s, s.upper())


def _normalizar_hora(valor: str) -> str:
    """Normaliza horas a HH:MM. Acepta '7', '7:0', '07.00', '7h', '0700'."""
    import re
    s = str(valor or '').strip().lower().replace('h', '').replace('.', ':').replace(',', ':')
    if not s:
        return ''
    # Formato HHMM sin separador (ej '0700')
    if re.fullmatch(r'\d{3,4}', s):
        s = s.zfill(4)
        return f'{s[:2]}:{s[2:]}'
    m = re.match(r'(\d{1,2}):?(\d{0,2})', s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2)) if m.group(2) else 0
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f'{hh:02d}:{mm:02d}'
    return s


def _partir_rango_hora(valor):
    """Parte un rango de hora ("16:00 - 18:00", "8:00-10:00", "07:00 a 09:00")
    en (hora_inicio, hora_fin). Si no es rango, devuelve (valor, '')."""
    import re
    s = str(valor or '').strip()
    if not s:
        return '', ''
    m = re.findall(r'(\d{1,2}[:.]?\d{0,2})', s)
    if len(m) >= 2:
        return m[0], m[1]
    return (m[0] if m else s), ''


def _mapear_fila(fila: dict) -> Optional[dict]:
    """
    Normaliza nombres de columnas del archivo al schema interno.
    Acepta variaciones como 'Codigo Materia', 'cod_mat', 'CODIGO', etc.
    """
    import unicodedata as _ud
    def _norm(s: str) -> str:
        s = _ud.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode('ascii')
        return s.strip().lower().replace(' ', '_').replace('.', '').replace('-', '_')

    def _buscar(fila: dict, *claves) -> str:
        claves_norm = {_norm(k) for k in claves}
        for fk in fila:
            if _norm(fk) in claves_norm:
                v = str(fila[fk] or '').strip()
                if v:
                    return v
        return ''

    # HORA puede venir como rango ("16:00 - 18:00") o en columnas separadas.
    hi = _buscar(fila, 'hora_inicio', 'inicio', 'start', 'hora_inicio_clase')
    hf = _buscar(fila, 'hora_fin', 'fin', 'end', 'hora_fin_clase')
    if not hi:
        hora_raw = _buscar(fila, 'hora', 'horario', 'franja_horaria')
        ini, fin = _partir_rango_hora(hora_raw)
        hi = hi or ini
        hf = hf or fin

    return {
        'codigo_materia': _buscar(fila, 'codigo_materia', 'materia_codigo', 'codigo', 'cod_materia', 'cod', 'subject_code', 'codigo_asignatura', 'id_assignatura', 'id_asignatura', 'id_materia'),
        'nombre_materia': _buscar(fila, 'nombre_materia', 'nombre', 'materia', 'asignatura', 'subject', 'nombre_asignatura', 'nombre_materia'),
        'dia':            _normalizar_dia(_buscar(fila, 'dia', 'day', 'dia_semana', 'dias')),
        'hora_inicio':    _normalizar_hora(hi),
        'hora_fin':       _normalizar_hora(hf),
        'docente':        _buscar(fila, 'docente', 'profesor', 'teacher', 'instructor'),
        'docente_email':  _buscar(fila, 'docente_email', 'docente_correo', 'email_docente', 'correo_docente', 'correo', 'email', 'correo_pi'),
        'salon':          _buscar(fila, 'salon', 'salon_codigo', 'aula', 'room', 'classroom', 'salon_aula'),
        'grupo':          _buscar(fila, 'grupo', 'group', 'seccion') or 'A',
        'creditos':       _buscar(fila, 'creditos', 'credits', 'credit_hours') or '3',
        '_bloque_raw':    _buscar(fila, 'bloque', 'block', 'periodo_bloque', 'franja'),
    }


def analizar_archivo_pipeline(
    contenido: bytes,
    nombre_archivo: str,
    periodo: str,
    usuario_id: int,
    forzar_llm: bool = False,
) -> Dict[str, Any]:
    """
    Pipeline completo: bytes → BD (horarios PROPUESTO).

    Retorna dict con:
      exito, horarios_creados, confianza, requiere_revision,
      advertencias, errores_detalle, desde_cache, proveedor_llm,
      tiempo_ms
    """
    from siihapi.motor_ia.schemas import HorarioExtraido, ResultadoValidacion
    from siihapi.motor_ia.cache_llm import cache_llm

    t0 = time.monotonic()
    resultado_base = {
        'exito':            False,
        'horarios_creados': 0,
        'confianza':        0,
        'requiere_revision': True,
        'advertencias':     [],
        'errores_detalle':  [],
        'desde_cache':      False,
        'proveedor_llm':    'none',
        'periodo':          periodo,
        'tiempo_ms':        0,
    }

    if not contenido:
        resultado_base['error'] = 'Archivo vacio'
        return resultado_base

    # ── 1. Cache lookup ───────────────────────────────────────────────────────
    cache_key = cache_llm.make_key(contenido, periodo=periodo)
    if not forzar_llm:
        cached = cache_llm.get(cache_key)
        if cached is not None:
            log.info(f"[Pipeline] Cache HIT para '{nombre_archivo}' periodo={periodo}")
            cached['desde_cache'] = True
            cached['tiempo_ms']   = int((time.monotonic() - t0) * 1000)
            return cached

    # ── 2. Parse del archivo ──────────────────────────────────────────────────
    filas_raw = _leer_archivo(contenido, nombre_archivo)
    if not filas_raw:
        resultado_base['error'] = f"No se pudo leer el archivo '{nombre_archivo}'"
        return resultado_base

    tiene_texto_raw = 'texto_raw' in (filas_raw[0] if filas_raw else {})

    # ── 3. LLM para PDF/DOCX o si hay pocas columnas reconocibles ────────────
    horarios_dicts: List[dict] = []
    proveedor = 'directo'

    if tiene_texto_raw:
        # PDF/DOCX: extraccion estructurada con IA (Gemini/GPT/Claude o heuristico)
        try:
            from siihapi.motor_ia.llm import extraer_horarios_con_ia
            texto = filas_raw[0]['texto_raw']
            catalogo = _construir_catalogo_bd()
            horarios_dicts, proveedor, _modelo = extraer_horarios_con_ia(
                texto, periodo=periodo, catalogo=catalogo,
            )
            if not isinstance(horarios_dicts, list):
                horarios_dicts = []
            log.info(f"[Pipeline] IA extrajo {len(horarios_dicts)} horarios "
                     f"de '{nombre_archivo}' con {proveedor}/{_modelo}")
        except Exception as exc:
            log.warning(f"[Pipeline] Extraccion IA fallo para PDF/DOCX: {exc}")
            resultado_base['error'] = f'La IA no pudo extraer datos: {exc}'
            return resultado_base
    else:
        # CSV/XLSX: mapeo directo de columnas
        for fila in filas_raw:
            mapeada = _mapear_fila(fila)
            if mapeada:
                horarios_dicts.append(mapeada)

    # ── 3.5. Asignacion inteligente: rellena dia/hora/salon/docente faltantes ──
    horarios_dicts, _asignados = _asignar_faltantes(horarios_dicts)
    if _asignados:
        log.info(f"[Pipeline] IA asigno automaticamente slot/salon/docente a {_asignados} clase(s)")

    # ── 4. Validacion con schema ──────────────────────────────────────────────
    horarios_dicts = _enriquecer_dicts(horarios_dicts)
    horarios_obj = [HorarioExtraido(**d) for d in horarios_dicts if d]
    validacion   = ResultadoValidacion.desde_lista(horarios_obj)
    resumen      = validacion.resumen()

    log.info(
        f"[Pipeline] '{nombre_archivo}' periodo={periodo} "
        f"validos={resumen['validos']}/{resumen['total_extraidos']} "
        f"confianza={resumen['confianza_global']}%"
    )

    # ── 5. Guardar en BD solo si confianza >= 50% ─────────────────────────────
    creados = 0
    if resumen['validos'] > 0 and resumen['confianza_global'] >= 50:
        try:
            creados = _guardar_horarios_propuestos(
                validacion.horarios_validos, periodo, usuario_id
            )
        except Exception as exc:
            log.error(f"[Pipeline] Error guardando en BD: {exc}")
            resultado_base['error'] = f'Error al guardar horarios: {exc}'
            return resultado_base

    # ── 6. Resultado final ────────────────────────────────────────────────────
    resultado = {
        'exito':            creados > 0,
        'horarios_creados': creados,
        'registros':        _muestra_registros(horarios_dicts),
        'confianza':        resumen['confianza_global'],
        'requiere_revision': resumen['requiere_revision'],
        'advertencias':     resumen['advertencias'],
        'errores_detalle':  resumen['errores_detalle'],
        'desde_cache':      False,
        'proveedor_llm':    proveedor,
        'periodo':          periodo,
        'tiempo_ms':        int((time.monotonic() - t0) * 1000),
    }

    # Solo cachear si el resultado fue exitoso
    if resultado['exito']:
        cache_llm.set(cache_key, resultado, ttl=1800)  # 30 min

    return resultado


def analizar_multiples_archivos(archivos, periodo, usuario_id, forzar_llm=False):
    """Analiza 2+ archivos tabulares: los CRUZA y unifica (gestion_documentos),
    asigna lo que falte, valida y crea horarios PROPUESTO. Misma forma de retorno
    que analizar_archivo_pipeline."""
    import time as _t
    from siihapi.motor_ia.schemas import HorarioExtraido, ResultadoValidacion
    t0 = _t.monotonic()
    base = {
        'exito': False, 'horarios_creados': 0, 'confianza': 0, 'requiere_revision': True,
        'advertencias': [], 'errores_detalle': [], 'desde_cache': False,
        'proveedor_llm': 'cruce-multidoc', 'periodo': periodo, 'tiempo_ms': 0,
        'archivos': [n for n, _ in archivos],
    }
    try:
        from siihapi.motor_ia import gestion_documentos as gd
        sesion = gd.analizar_documentos(archivos, periodo=periodo, sesion_id='motoria')
        dicts = sesion.df().to_dict('records')
    except Exception as exc:
        log.warning(f"[Pipeline] Cruce multidoc fallo: {exc}")
        base['error'] = f'No se pudieron cruzar los archivos: {exc}'
        return base

    # Asignar faltantes + enriquecer (reusa la logica existente)
    dicts, _asig = _asignar_faltantes(dicts)
    dicts = _enriquecer_dicts(dicts)
    horarios_obj = [HorarioExtraido(**{k: d.get(k, '') for k in (
        'codigo_materia','nombre_materia','dia','hora_inicio','hora_fin',
        'docente','docente_email','salon','grupo','creditos')}) for d in dicts if d]
    validacion = ResultadoValidacion.desde_lista(horarios_obj)
    resumen = validacion.resumen()

    creados = 0
    if resumen['validos'] > 0 and resumen['confianza_global'] >= 50:
        try:
            creados = _guardar_horarios_propuestos(validacion.horarios_validos, periodo, usuario_id)
        except Exception as exc:
            log.error(f"[Pipeline] Error guardando multidoc: {exc}")
            base['error'] = f'Error al guardar: {exc}'
            return base

    base.update({
        'exito': creados > 0,
        'horarios_creados': creados,
        'confianza': resumen['confianza_global'],
        'requiere_revision': resumen['requiere_revision'],
        'advertencias': resumen['advertencias'] + sesion.advertencias,
        'errores_detalle': resumen['errores_detalle'],
        'tiempo_ms': int((_t.monotonic() - t0) * 1000),
        'registros': _muestra_registros(dicts),
    })
    return base


def _muestra_registros(dicts, limite=80):
    """Devuelve una muestra compacta de los registros para dar CONTEXTO al chat."""
    out = []
    for d in (dicts or [])[:limite]:
        if not d:
            continue
        out.append({
            'codigo_materia': d.get('codigo_materia', ''),
            'nombre_materia': d.get('nombre_materia', ''),
            'dia': d.get('dia', ''),
            'hora_inicio': d.get('hora_inicio', ''),
            'hora_fin': d.get('hora_fin', ''),
            'docente': d.get('docente', ''),
            'salon': d.get('salon', ''),
            'grupo': d.get('grupo', ''),
        })
    return out


def _construir_catalogo_bd():
    """Catalogo de materias/docentes/salones reales para guiar a la IA en el mapeo."""
    catalogo = {'materias': {}, 'docentes': [], 'salones': []}
    try:
        from apps.academico.models import Materia
        for m in Materia.objects.all()[:300]:
            catalogo['materias'][m.codigo] = m.nombre
    except Exception:
        pass
    try:
        from apps.personal.models import Docente
        for d in Docente.objects.filter(activo=True).select_related('usuario')[:200]:
            u = d.usuario
            correo = getattr(u, 'correo', '') or getattr(u, 'email', '')
            catalogo['docentes'].append(f"{u.nombre} {u.apellido} <{correo}>")
    except Exception:
        pass
    try:
        from apps.infraestructura.models import Salon
        catalogo['salones'] = [s.codigo for s in Salon.objects.filter(activo=True)[:200]]
    except Exception:
        pass
    return catalogo


def _asignar_faltantes(dicts):
    """Motor de asignacion: para cada clase sin dia/hora/salon/docente, asigna
    un slot libre (sin choques de salon ni docente). Asi, subir un Excel con solo
    las materias basta para que la IA proponga el horario completo."""
    if not dicts:
        return dicts, 0

    DIAS = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES']
    bloques, salones, docentes = [], [], []
    try:
        from apps.horarios.models import Bloque
        bloques = [(b.numero, b.hora_inicio.strftime('%H:%M'), b.hora_fin.strftime('%H:%M'))
                   for b in Bloque.objects.order_by('numero')]
    except Exception:
        bloques = [(i, f"{6+i:02d}:00", f"{7+i:02d}:00") for i in range(1, 13)]
    try:
        from apps.infraestructura.models import Salon
        salones = [s.codigo for s in Salon.objects.filter(activo=True)[:200]]
    except Exception:
        pass
    try:
        from apps.personal.models import Docente
        for d in Docente.objects.filter(activo=True).select_related('usuario')[:200]:
            u = d.usuario
            docentes.append((f"{u.nombre} {u.apellido}",
                             getattr(u, 'correo', '') or getattr(u, 'email', '')))
    except Exception:
        pass

    # Ocupacion ya existente en BD (no chocar con lo publicado/propuesto)
    ocup_salon, ocup_doc = set(), set()
    try:
        from apps.horarios.models import Horario
        for h in Horario.objects.select_related('salon', 'docente', 'bloque').all():
            ocup_salon.add((h.dia, h.bloque.numero, getattr(h.salon, 'codigo', '')))
            ocup_doc.add((h.dia, h.bloque.numero, h.docente_id))
    except Exception:
        pass

    asignados = 0
    di = 0
    total = len(DIAS) * max(1, len(bloques)) * max(1, len(salones) or 1)
    for idx, d in enumerate(dicts):
        if not d:
            continue
        falta_slot = not (d.get('dia') and d.get('hora_inicio') and d.get('hora_fin'))
        falta_salon = not d.get('salon')
        falta_doc = not (d.get('docente') or d.get('docente_email'))
        if not (falta_slot or falta_salon or falta_doc):
            continue

        # Elegir docente si falta
        if falta_doc and docentes:
            nom, correo = docentes[idx % len(docentes)]
            d['docente'] = d.get('docente') or nom
            d['docente_email'] = d.get('docente_email') or correo
        doc_key = d.get('docente_email') or d.get('docente') or f'doc{idx}'

        # Buscar slot libre (dia, bloque, salon)
        if falta_slot or falta_salon:
            colocado = False
            intentos = 0
            while not colocado and intentos < total + 5:
                dia = d.get('dia') or DIAS[di % len(DIAS)]
                bnum, hi, hf = bloques[(di // len(DIAS)) % len(bloques)] if bloques else (1, '07:00', '08:00')
                salon = (d.get('salon') or (salones[(di // (len(DIAS) * max(1, len(bloques)))) % len(salones)]
                                            if salones else 'POR-ASIGNAR'))
                di += 1
                intentos += 1
                if (dia, bnum, salon) in ocup_salon or (dia, bnum, doc_key) in ocup_doc:
                    continue
                ocup_salon.add((dia, bnum, salon))
                ocup_doc.add((dia, bnum, doc_key))
                d['dia'] = dia
                d['hora_inicio'] = d.get('hora_inicio') or hi
                d['hora_fin'] = d.get('hora_fin') or hf
                d['salon'] = salon
                colocado = True
            asignados += 1
        elif falta_doc:
            asignados += 1
    return dicts, asignados


def _enriquecer_dicts(dicts):
    """Completa datos faltantes: resuelve 'bloque' -> horas y nombre de materia
    consultando la BD. Permite usar archivos estilo carga-masiva en el analizador."""
    # Cache de bloques {numero: (hi, hf)}
    bloques = {}
    try:
        from apps.horarios.models import Bloque
        for b in Bloque.objects.all():
            bloques[str(b.numero)] = (b.hora_inicio.strftime('%H:%M'),
                                      b.hora_fin.strftime('%H:%M'))
    except Exception:
        pass

    try:
        from apps.academico.models import Materia
    except Exception:
        Materia = None

    salida = []
    for d in dicts:
        if not d:
            continue
        bloque_raw = str(d.pop('_bloque_raw', '') or '').strip()
        # Resolver horas desde bloque si faltan
        if (not d.get('hora_inicio') or not d.get('hora_fin')) and bloque_raw in bloques:
            hi, hf = bloques[bloque_raw]
            d['hora_inicio'] = d.get('hora_inicio') or hi
            d['hora_fin'] = d.get('hora_fin') or hf
        # Nombre de materia por defecto: buscar en BD por codigo, si no usar el codigo
        if not d.get('nombre_materia') and d.get('codigo_materia'):
            nombre = ''
            if Materia is not None:
                try:
                    m = Materia.objects.filter(codigo__iexact=d['codigo_materia']).first()
                    if m:
                        nombre = m.nombre
                except Exception:
                    pass
            d['nombre_materia'] = nombre or f"Materia {d['codigo_materia']}"
        # Limpiar cualquier clave extra que el dataclass no acepte
        d.pop('_bloque_raw', None)
        salida.append(d)
    return salida


def _entidades_por_defecto():
    """Crea (si faltan) Facultad/Programa/Estudiante placeholder para importar
    documentos cuyas materias aun no existen. Devuelve (programa, estudiante)."""
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
            u = Usuario(correo='import.horarios@pi.edu.co', nombre='Grupo', apellido='Importado (IA)', rol='ESTUDIANTE')
            try:
                u.set_password('Import_2026!')
            except Exception:
                pass
            u.save()
        est = Estudiante.objects.create(usuario=u, codigo='DOC-IMPORT', programa=prog)
    return prog, est


def _guardar_horarios_propuestos(horarios: list, periodo: str, usuario_id: int,
                                 crear_faltantes: bool = True) -> int:
    """Crea Horarios PROPUESTO mapeando al modelo real. INICIALIZA DESDE CERO.
    Si crear_faltantes=True, crea automaticamente las Materias que no existan
    (bajo un programa 'Importado') y una matricula placeholder para que la clase
    quede registrada aunque aun no haya estudiantes matriculados."""
    from apps.horarios.models import Horario, Bloque
    from apps.academico.models import Materia
    from apps.personal.models import Docente
    from apps.infraestructura.models import Salon
    from apps.matriculas.models import Matricula, Periodo
    from django.db import transaction
    from datetime import datetime as _dt

    per = Periodo.objects.filter(codigo=periodo).first() or Periodo.objects.filter(activo=True).first()
    bloques = list(Bloque.objects.order_by('numero'))
    salones = list(Salon.objects.filter(activo=True))
    docentes = list(Docente.objects.filter(activo=True).select_related('usuario'))
    if not (bloques and salones and docentes and per):
        log.warning('[Pipeline] Faltan bloques/salones/docentes/periodo para persistir.')
        return 0

    prog_def = est_def = None
    if crear_faltantes:
        try:
            prog_def, est_def = _entidades_por_defecto()
        except Exception as exc:
            log.warning(f"[Pipeline] No se pudieron crear entidades por defecto: {exc}")

    def _bloque_cercano(hi):
        try:
            t = _dt.strptime(hi, '%H:%M').time()
        except Exception:
            return bloques[0]
        return min(bloques, key=lambda b: abs(
            (b.hora_inicio.hour*60 + b.hora_inicio.minute) - (t.hour*60 + t.minute)))

    _MAPA_DIA = {'LU':'LU','MA':'MA','MI':'MI','JU':'JU','VI':'VI','SA':'SA','DO':'DO',
                 'LUNES':'LU','MARTES':'MA','MIERCOLES':'MI','JUEVES':'JU','VIERNES':'VI',
                 'SABADO':'SA','DOMINGO':'DO'}

    creados = 0
    with transaction.atomic():
        Horario.objects.filter(estado='PROPUESTO').delete()  # inicializar desde cero
        ocup_salon, ocup_doc = set(), set()
        for h in Horario.objects.filter(estado__in=['APROBADO', 'PUBLICADO']):
            ocup_salon.add((h.dia, h.bloque_id, h.salon_id))
            ocup_doc.add((h.dia, h.bloque_id, h.docente_id))

        for idx, h in enumerate(horarios):
            cod = str(h.codigo_materia).strip()
            if not cod:
                continue
            materia = Materia.objects.filter(codigo__iexact=cod).first()
            if not materia:
                if not (crear_faltantes and prog_def):
                    log.info(f"[Pipeline] Materia {cod} no existe; se omite.")
                    continue
                materia = Materia.objects.create(
                    programa=prog_def, codigo=cod,
                    nombre=(h.nombre_materia or f'Materia {cod}'),
                    creditos=int(getattr(h, 'creditos', 3) or 3))

            bloque = _bloque_cercano(h.hora_inicio)
            salon = (Salon.objects.filter(codigo__iexact=str(h.salon)).first()
                     or salones[idx % len(salones)])
            docente = None
            if h.docente_email:
                docente = Docente.objects.filter(usuario__correo__iexact=h.docente_email).first()
            if not docente:
                docente = docentes[idx % len(docentes)]
            dia_cod = _MAPA_DIA.get(str(h.dia).upper(), 'LU')

            # matriculas reales de la materia; si no hay, usar placeholder
            matriculas = list(Matricula.objects.filter(materia=materia, periodo=per, estado='ACTIVA'))
            if not matriculas and crear_faltantes and est_def:
                mph, _ = Matricula.objects.get_or_create(
                    estudiante=est_def, materia=materia, periodo=per,
                    defaults={'estado': 'ACTIVA'})
                matriculas = [mph]
            if not matriculas:
                continue

            for mat in matriculas:
                if (dia_cod, bloque.id_bloque, salon.id_salon) in ocup_salon:
                    continue
                if (dia_cod, bloque.id_bloque, docente.id_docente) in ocup_doc:
                    continue
                try:
                    Horario.objects.create(
                        matricula=mat, materia=materia, docente=docente,
                        salon=salon, bloque=bloque, dia=dia_cod, estado='PROPUESTO')
                    ocup_salon.add((dia_cod, bloque.id_bloque, salon.id_salon))
                    ocup_doc.add((dia_cod, bloque.id_bloque, docente.id_docente))
                    creados += 1
                except Exception as exc:
                    log.warning(f"[Pipeline] No se creo horario: {exc}")
    return creados
