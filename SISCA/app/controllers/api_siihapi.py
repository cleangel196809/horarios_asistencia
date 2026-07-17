"""
SISCA - API REAL de integracion con SIIHAPI.

Recibe horarios de SIIHAPI y los inserta en las tablas Oracle de SISCA:
    - MATERIA (si el codigo no existe)
    - HORARIO (con dia, hora_inicio, hora_fin, aula)
    - SESION_CLASE (opcional, para la primera sesion del periodo)

Endpoints:
    POST   /api/v1/horarios/publicar      - Publica lote de horarios
    PUT    /api/v1/horarios/<id>          - Actualiza un horario
    DELETE /api/v1/horarios/<id>          - Cancela un horario
    GET    /api/v1/asistencia/sesion/<id>
    GET    /api/v1/asistencia/materia/<id>/periodo/<p>
"""
import logging
from datetime import datetime, timedelta, date
from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for

from app.database.connection import execute_one, execute_query


def execute_dml(sql, params=None):
    """Wrapper para INSERT/UPDATE/DELETE con commit."""
    return execute_query(sql, params, fetch=False, commit=True)


def get_connection():
    """Stub para compatibilidad."""
    from app.database.connection import get_db
    return get_db()

log = logging.getLogger(__name__)
api_siihapi_bp = Blueprint('api_siihapi', __name__)
ui_siihapi_bp  = Blueprint('ui_siihapi',  __name__)


# ── Autenticación Bearer ──────────────────────────────────────────────────────

def _verificar_token() -> bool:
    """Comprueba que el request lleve el Bearer token correcto."""
    from flask import current_app
    token_esperado = current_app.config.get('SISCA_API_TOKEN', '')
    if not token_esperado:
        return True  # sin token configurado, modo permisivo (dev)
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:].strip() == token_esperado
    # También aceptar como query param ?token=... (útil para pruebas rápidas)
    return request.args.get('token', '') == token_esperado


def _token_requerido(fn):
    """Decorador que exige Bearer token en endpoints API."""
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _verificar_token():
            return jsonify({'error': 'No autorizado', 'code': 401}), 401
        return fn(*args, **kwargs)
    return wrapper


# ════════════════════════════════════════════════════════════════
#  UI: Panel de horarios subidos desde SIIHAPI
# ════════════════════════════════════════════════════════════════
@ui_siihapi_bp.route('/horarios', methods=['GET'])
def panel_horarios_siihapi():
    """Panel visual con todos los horarios sincronizados desde SIIHAPI."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    dia_filtro = request.args.get('dia', '').upper()
    aula_filtro = request.args.get('aula', '').upper()
    codigo_filtro = request.args.get('codigo', '').upper()
    carrera_filtro = request.args.get('carrera', '').strip()
    semestre_filtro = request.args.get('semestre', '').strip()
    jornada_filtro = request.args.get('jornada', '').upper().strip()
    docente_filtro = request.args.get('docente', '').strip()

    # ── KPIs robustos (LEFT JOIN + NVL) ──
    kpis = execute_one("""
        SELECT
          COUNT(*) AS total_horarios,
          COUNT(DISTINCT H.ID_MATERIA) AS total_materias,
          COUNT(DISTINCT M.ID_DOCENTE) AS total_docentes,
          COUNT(DISTINCT H.AULA) AS total_aulas
        FROM HORARIO H
        LEFT JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
        WHERE NVL(H.ESTADO,'A') = 'A'
    """) or {'total_horarios':0,'total_materias':0,'total_docentes':0,'total_aulas':0}

    fila_ses = execute_one(
        "SELECT COUNT(*) AS total FROM SESION_CLASE WHERE ESTADO_SESION = 'ACTIVA'"
    )
    kpis['total_sesiones'] = fila_ses['total'] if fila_ses else 0

    # KPI extra: última actividad de integración
    fila_ultimo = execute_one("""
        SELECT TO_CHAR(MAX(FECHA_SESION), 'DD/MM/YYYY HH24:MI') AS ultima
        FROM SESION_CLASE
    """)
    kpis['ultima_sync'] = (fila_ultimo and fila_ultimo.get('ultima')) or 'Sin actividad'

    # ── Tabla principal con LEFT JOIN robusto ──
    sql = """
        SELECT
          H.ID_HORARIO,
          NVL(M.CODIGO, '—')             AS CODIGO,
          NVL(M.NOMBRE_MATERIA, '(Sin materia)') AS NOMBRE_MATERIA,
          NVL(H.DIA, '—')                AS DIA,
          TO_CHAR(H.HORA_INICIO, 'HH24:MI') AS HORA_INICIO,
          TO_CHAR(H.HORA_FIN, 'HH24:MI')    AS HORA_FIN,
          NVL(H.AULA, '—')               AS AULA,
          NVL(H.ESTADO, 'A')             AS ESTADO,
          NVL(U.NOMBRE || ' ' || U.APELLIDO, 'Sin asignar') AS DOCENTE,
          U.CORREO AS DOCENTE_EMAIL,
          NVL(D.ESPECIALIDAD, '—')       AS ESPECIALIDAD,
          NVL(C.NOMBRE_CARRERA, '—')     AS CARRERA
        FROM HORARIO H
        LEFT JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
        LEFT JOIN DOCENTE D ON D.ID_DOCENTE = M.ID_DOCENTE
        LEFT JOIN USUARIO U ON U.ID_USUARIO = D.ID_USUARIO
        LEFT JOIN CARRERA C ON C.ID_CARRERA = M.ID_CARRERA
        WHERE NVL(H.ESTADO,'A') = 'A'
    """
    params = {}
    if dia_filtro:
        sql += " AND UPPER(NVL(H.DIA,'')) = :d"
        params['d'] = dia_filtro
    if aula_filtro:
        sql += " AND UPPER(NVL(H.AULA,'')) LIKE :a"
        params['a'] = f'%{aula_filtro}%'
    if codigo_filtro:
        sql += " AND UPPER(NVL(M.CODIGO,'')) LIKE :c"
        params['c'] = f'%{codigo_filtro}%'
    if carrera_filtro:
        sql += " AND (UPPER(NVL(C.NOMBRE_CARRERA,'')) LIKE :car OR UPPER(NVL(C.CODIGO_CARRERA,'')) LIKE :car)"
        params['car'] = f'%{carrera_filtro.upper()}%'
    if semestre_filtro:
        sql += " AND TO_CHAR(NVL(M.SEMESTRE,0)) = :sem"
        params['sem'] = semestre_filtro
    if docente_filtro:
        sql += " AND UPPER(NVL(U.NOMBRE,'')||' '||NVL(U.APELLIDO,'')) LIKE :doc"
        params['doc'] = f'%{docente_filtro.upper()}%'
    if jornada_filtro == 'DIURNA':
        sql += " AND H.HORA_INICIO >= TO_DATE('07:00','HH24:MI') AND H.HORA_INICIO < TO_DATE('10:00','HH24:MI')"
    elif jornada_filtro == 'ESPECIAL':
        sql += " AND H.HORA_INICIO >= TO_DATE('10:00','HH24:MI') AND H.HORA_INICIO < TO_DATE('13:00','HH24:MI')"
    elif jornada_filtro == 'NOCTURNA':
        sql += " AND H.HORA_INICIO >= TO_DATE('18:00','HH24:MI') AND H.HORA_INICIO < TO_DATE('21:00','HH24:MI')"
    elif jornada_filtro == 'SABADO':
        sql += " AND UPPER(NVL(H.DIA,'')) = 'SABADO'"

    sql += " ORDER BY DECODE(H.DIA,'LUNES',1,'MARTES',2,'MIERCOLES',3,'JUEVES',4,'VIERNES',5,'SABADO',6,7), H.HORA_INICIO"

    horarios = (execute_query(sql, params, fetch=True) or [])[:300]

    # Distribución por día (para mini-chart)
    dist_dia = execute_query("""
        SELECT NVL(DIA,'—') AS DIA, COUNT(*) AS TOTAL
        FROM HORARIO
        WHERE NVL(ESTADO,'A') = 'A'
        GROUP BY DIA
        ORDER BY DECODE(NVL(DIA,'—'),'LUNES',1,'MARTES',2,'MIERCOLES',3,'JUEVES',4,'VIERNES',5,'SABADO',6,7)
    """, fetch=True) or []

    log.info(f"[SISCA] panel_horarios_siihapi -> {len(horarios)} horarios, KPIs: {kpis}")

    # Catalogo de carreras para el desplegable
    carreras = execute_query("SELECT DISTINCT NVL(NOMBRE_CARRERA,'') AS NOMBRE_CARRERA FROM CARRERA WHERE NOMBRE_CARRERA IS NOT NULL ORDER BY NOMBRE_CARRERA", fetch=True) or []
    semestres = execute_query("SELECT DISTINCT NVL(SEMESTRE,0) AS SEMESTRE FROM MATERIA WHERE SEMESTRE IS NOT NULL ORDER BY SEMESTRE", fetch=True) or []

    return render_template('integracion/horarios_siihapi.html',
        horarios=horarios, kpis=kpis, dist_dia=dist_dia,
        dia_filtro=dia_filtro, aula_filtro=aula_filtro, codigo_filtro=codigo_filtro,
        carrera_filtro=carrera_filtro, semestre_filtro=semestre_filtro,
        jornada_filtro=jornada_filtro, docente_filtro=docente_filtro,
        carreras=carreras, semestres=semestres,
    )


@ui_siihapi_bp.route('/horarios/<int:id_horario>', methods=['GET'])
def detalle_horario(id_horario):
    """Detalle completo de un horario sincronizado desde SIIHAPI."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    try:
        sql = """
            SELECT
              H.ID_HORARIO,
              M.ID_MATERIA,
              NVL(M.CODIGO, '—')          AS CODIGO,
              NVL(M.NOMBRE_MATERIA, '—')  AS NOMBRE_MATERIA,
              M.CREDITOS,
              M.SEMESTRE,
              NVL(H.DIA, '—')             AS DIA,
              TO_CHAR(H.HORA_INICIO, 'HH24:MI') AS HORA_INICIO,
              TO_CHAR(H.HORA_FIN, 'HH24:MI')    AS HORA_FIN,
              NVL(H.AULA, '—')            AS AULA,
              NVL(H.ESTADO, 'A')          AS ESTADO,
              D.ID_DOCENTE,
              NVL(D.ESPECIALIDAD, '—')    AS ESPECIALIDAD,
              NVL(U.NOMBRE, '')           AS DOC_NOMBRE,
              NVL(U.APELLIDO, '')         AS DOC_APELLIDO,
              NVL(U.CORREO, '—')          AS DOC_CORREO,
              NVL(C.NOMBRE_CARRERA, '—')  AS NOMBRE_CARRERA,
              NVL(C.CODIGO_CARRERA, '—')  AS CODIGO_CARRERA
            FROM HORARIO H
            JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
            LEFT JOIN DOCENTE D ON D.ID_DOCENTE = M.ID_DOCENTE
            LEFT JOIN USUARIO U ON U.ID_USUARIO = D.ID_USUARIO
            LEFT JOIN CARRERA C ON C.ID_CARRERA = M.ID_CARRERA
            WHERE H.ID_HORARIO = :h
        """
        h = execute_one(sql, {'h': id_horario})
        if not h:
            from flask import abort
            return abort(404)

        # Otras clases del mismo docente
        otras_doc = []
        if h.get('id_docente'):
            otras_doc = execute_query("""
                SELECT * FROM (
                    SELECT NVL(M.CODIGO,'—') AS CODIGO,
                           NVL(M.NOMBRE_MATERIA,'—') AS NOMBRE_MATERIA,
                           NVL(H.DIA,'—') AS DIA,
                           TO_CHAR(H.HORA_INICIO,'HH24:MI') AS HORA_INICIO,
                           NVL(H.AULA,'—') AS AULA
                    FROM HORARIO H
                    JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
                    WHERE M.ID_DOCENTE = :d AND H.ID_HORARIO != :h
                    ORDER BY H.DIA, H.HORA_INICIO
                ) WHERE ROWNUM <= 10
            """, {'d': h['id_docente'], 'h': id_horario}, fetch=True) or []

        # Otras clases en el mismo aula
        otras_aula = []
        if h.get('aula') and h['aula'] != '—':
            otras_aula = execute_query("""
                SELECT * FROM (
                    SELECT NVL(M.CODIGO,'—') AS CODIGO,
                           NVL(M.NOMBRE_MATERIA,'—') AS NOMBRE_MATERIA,
                           NVL(H.DIA,'—') AS DIA,
                           TO_CHAR(H.HORA_INICIO,'HH24:MI') AS HORA_INICIO,
                           NVL(U.NOMBRE || ' ' || U.APELLIDO, '—') AS DOCENTE
                    FROM HORARIO H
                    JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
                    LEFT JOIN DOCENTE D ON D.ID_DOCENTE = M.ID_DOCENTE
                    LEFT JOIN USUARIO U ON U.ID_USUARIO = D.ID_USUARIO
                    WHERE H.AULA = :a AND H.ID_HORARIO != :h
                    ORDER BY H.DIA, H.HORA_INICIO
                ) WHERE ROWNUM <= 10
            """, {'a': h['aula'], 'h': id_horario}, fetch=True) or []

        # Sesiones de este horario
        sesiones = execute_query("""
            SELECT * FROM (
                SELECT ID_SESION,
                       TO_CHAR(FECHA_SESION, 'DD/MM/YYYY') AS FECHA,
                       NVL(ESTADO_SESION, 'ACTIVA') AS ESTADO_SESION,
                       NVL(MODO_CONEXION, 'ONLINE') AS MODO_CONEXION
                FROM SESION_CLASE
                WHERE ID_HORARIO = :h
                ORDER BY FECHA_SESION DESC
            ) WHERE ROWNUM <= 10
        """, {'h': id_horario}, fetch=True) or []

        return render_template('integracion/horario_detalle.html',
            h=h, otras_doc=otras_doc, otras_aula=otras_aula, sesiones=sesiones,
        )
    except Exception as exc:
        log.exception(f"[SISCA] detalle_horario({id_horario}) FALLO: {exc}")
        print(f"[SISCA] ERROR detalle_horario: {exc}")
        return f"""
        <html><body style='font-family:sans-serif;padding:40px;background:#0d1117;color:#e6edf3;'>
        <h1 style='color:#EF4444;'>❌ Error al cargar el detalle del horario</h1>
        <p><strong>ID horario:</strong> {id_horario}</p>
        <p><strong>Error:</strong> {exc}</p>
        <p><a href='/siihapi/horarios' style='color:#1F6FEB;'>← Volver al panel</a></p>
        </body></html>
        """, 500


def _construir_pdf_politecnico(filas, titular=None, periodo_fechas=None):
    """
    Construye un PDF estilo Politécnico Internacional con la tabla de horarios.

    filas: lista de dicts con keys: codigo, nombre_materia, dia, hora_inicio, hora_fin,
           aula, doc_nombre, doc_apellido, codigo_carrera, nombre_carrera, semestre
    titular: dict opcional con: nombre, doc_ident, periodo, centro, plan
    periodo_fechas: str ej '28/04/2026 - 04/07/2026'
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    AZUL = colors.HexColor('#1F4988')
    AZUL_CLARO = colors.HexColor('#E8EEF7')
    GRIS_BORDE = colors.HexColor('#9CA3AF')
    NEGRO_DIA = colors.HexColor('#1E293B')

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1.2*cm, rightMargin=1.2*cm,
        topMargin=1.0*cm, bottomMargin=1.0*cm,
        title='Horario - Politecnico Internacional',
    )
    styles = getSampleStyleSheet()

    s_title = ParagraphStyle('inst', parent=styles['Normal'], fontName='Helvetica-BoldOblique',
                              fontSize=16, textColor=AZUL, alignment=TA_CENTER)
    s_label = ParagraphStyle('lbl', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=8, textColor=AZUL)
    s_val   = ParagraphStyle('val', parent=styles['Normal'], fontName='Helvetica',
                              fontSize=8, textColor=colors.black)
    s_th    = ParagraphStyle('th', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=8, textColor=AZUL)
    s_td    = ParagraphStyle('td', parent=styles['Normal'], fontName='Helvetica',
                              fontSize=8, textColor=colors.black, leading=10)
    s_dia   = ParagraphStyle('dia', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=8, textColor=NEGRO_DIA)
    s_foot_l = ParagraphStyle('fl', parent=styles['Normal'], fontName='Helvetica-Oblique',
                               fontSize=9, textColor=colors.black, alignment=TA_LEFT)
    s_foot_r = ParagraphStyle('fr', parent=styles['Normal'], fontName='Helvetica-Oblique',
                               fontSize=9, textColor=colors.black, alignment=TA_RIGHT)

    story = []

    # ─────────── Header institucional ───────────
    encabezado = Table([[
        Paragraph('<b>Polit&eacute;cnico</b><br/>Internacional', s_label),
        Paragraph('<i>POLITECNICO INTERNACIONAL</i>', s_title),
    ]], colWidths=[3.5*cm, 23.5*cm], rowHeights=[1.3*cm])
    encabezado.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(encabezado)
    story.append(Spacer(1, 0.1*cm))

    # ─────────── Datos del titular ───────────
    if titular:
        nombre = titular.get('nombre', '')
        doc_id = titular.get('doc_ident', '')
        periodo = titular.get('periodo', '')
        centro = titular.get('centro', '')
        plan = titular.get('plan', '')
        info = Table([
            [Paragraph('<b>Nombre y apellidos</b>', s_label), Paragraph(nombre, s_val),
             Paragraph('<b>Doc. Ident.</b>', s_label), Paragraph(doc_id, s_val)],
            [Paragraph('<b>Curso Académico</b>', s_label), Paragraph(periodo, s_val),
             Paragraph('<b>Centro</b>', s_label), Paragraph(centro, s_val)],
            [Paragraph('<b>Plan</b>', s_label), Paragraph(plan, s_val), '', ''],
        ], colWidths=[3.2*cm, 9.0*cm, 2.4*cm, 12.4*cm])
        info.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('SPAN', (1,2), (3,2)),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(info)
        story.append(Spacer(1, 0.15*cm))

    # ─────────── Periodo de fechas ───────────
    if periodo_fechas:
        fechas_tbl = Table([[Paragraph(f'<b>{periodo_fechas}</b>', s_th)]],
                            colWidths=[27*cm], rowHeights=[0.55*cm])
        fechas_tbl.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(fechas_tbl)

    # ─────────── Tabla principal de horarios ───────────
    headers = ['Dias', 'Asignatura', 'Grupo', 'Profesor', 'Aula', 'Franja Horaria']

    # Agrupar filas por día en orden
    orden_dias = ['LUNES','MARTES','MIERCOLES','MIÉRCOLES','JUEVES','VIERNES','SABADO','SÁBADO','DOMINGO']
    def _key_dia(f):
        d = (f.get('dia') or '').upper()
        try: return orden_dias.index(d)
        except ValueError: return 99
    filas_ord = sorted(filas, key=lambda f: (_key_dia(f), f.get('hora_inicio') or ''))

    # Cabecera
    data = [[Paragraph(f'<b>{h}</b>', s_th) for h in headers]]
    span_groups = []  # (col=0, fila_inicio, fila_fin)
    row_idx = 1
    dia_actual = None
    fila_inicio_dia = None

    for f in filas_ord:
        dia = (f.get('dia') or '—').upper()
        # Acentos para MIERCOLES y SABADO
        dia_display = {'MIERCOLES':'MIÉRCOLES', 'SABADO':'SÁBADO'}.get(dia, dia)
        codigo = f.get('codigo') or '—'
        materia = f.get('nombre_materia') or '—'
        asignatura = f"[{codigo}] {materia}"

        cod_carrera = f.get('codigo_carrera') or 'GRP'
        grupo = f"1 ({cod_carrera})"

        doc_nom = (f.get('doc_nombre') or '').strip()
        doc_ape = (f.get('doc_apellido') or '').strip()
        profesor = (f"{doc_nom} {doc_ape}").strip() or '—'

        aula_corta = f.get('aula') or '—'
        if aula_corta and aula_corta != '—':
            aula_full = f"SALA DE SISTEMAS {aula_corta} SEDE CALLE 73 (SEDE CALLE 73) -"
        else:
            aula_full = "ASIGNATURA ASISTIDA POR TECNOLOGIA CON ENCUENTROS SINCRONICOS (CAMPUS) -"

        hora_ini = f.get('hora_inicio') or '--:--'
        hora_fin = f.get('hora_fin') or '--:--'
        franja = f"{hora_ini}  -  {hora_fin}"

        # El dia se marca por fila (sin SPAN). Asi la tabla puede dividirse en
        # varias paginas sin el error "too large on page 2" al imprimir TODO.
        if dia_actual != dia:
            dia_actual = dia
            celda_dia = Paragraph(f'<b>{dia_display}</b>', s_dia)
        else:
            celda_dia = Paragraph(f'<font color="#94A3B8">{dia_display}</font>', s_dia)

        data.append([
            celda_dia,
            Paragraph(asignatura, s_td),
            Paragraph(grupo, s_td),
            Paragraph(profesor.upper(), s_td),
            Paragraph(aula_full, s_td),
            Paragraph(franja, s_td),
        ])
        row_idx += 1

    # Si no hay filas, agregar fila placeholder
    if len(data) == 1:
        data.append([Paragraph('—', s_td)] * 6)

    col_widths = [2.0*cm, 7.0*cm, 2.8*cm, 4.7*cm, 6.0*cm, 2.8*cm]
    tabla = Table(data, colWidths=col_widths, repeatRows=1)
    estilo = [
        # Header
        ('BACKGROUND', (0,0), (-1,0), AZUL_CLARO),
        ('LINEBELOW', (0,0), (-1,0), 0.7, AZUL),
        ('LINEABOVE', (0,0), (-1,0), 0.7, GRIS_BORDE),
        # Grid
        ('GRID', (0,1), (-1,-1), 0.4, GRIS_BORDE),
        ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
        # Padding
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        # Columna día
        ('BACKGROUND', (0,1), (0,-1), colors.white),
    ]
    # NOTA: no se usa SPAN en la columna de dias. Un SPAN que agrupa muchas filas
    # genera una celda mas alta que la pagina y ReportLab no puede partirla
    # (error "too large on page 2"). Sin SPAN, la tabla se divide y se imprime TODO.
    tabla.setStyle(TableStyle(estilo))
    story.append(tabla)

    # ─────────── Footer con numero de pagina real en cada hoja ───────────
    def _pie(canvas, documento):
        canvas.saveState()
        canvas.setFont('Helvetica-Oblique', 9)
        ancho, _alto = landscape(A4)
        y = 0.7*cm
        canvas.setStrokeColor(GRIS_BORDE)
        canvas.line(documento.leftMargin, y + 0.35*cm, ancho - documento.rightMargin, y + 0.35*cm)
        canvas.setFillColor(colors.black)
        canvas.drawString(documento.leftMargin, y, 'Leyenda de abreviaturas.')
        canvas.drawRightString(ancho - documento.rightMargin, y, f'Pag. {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_pie, onLaterPages=_pie)
    buf.seek(0)
    return buf.read()


def _get_titular_actual():
    """Obtiene info del usuario logueado para el header del PDF."""
    uid = session.get('usuario_id')
    if not uid:
        return None
    u = execute_one("""
        SELECT U.NOMBRE, U.APELLIDO, U.CORREO, U.ROL,
               E.CODIGO_ESTUDIANTE, E.SEMESTRE,
               C.NOMBRE_CARRERA, C.CODIGO_CARRERA
        FROM USUARIO U
        LEFT JOIN ESTUDIANTE E ON E.ID_USUARIO = U.ID_USUARIO
        LEFT JOIN INSCRIPCION I ON I.ID_ESTUDIANTE = E.ID_ESTUDIANTE AND I.ESTADO = 'ACTIVA'
        LEFT JOIN MATERIA M ON M.ID_MATERIA = I.ID_MATERIA
        LEFT JOIN CARRERA C ON C.ID_CARRERA = M.ID_CARRERA
        WHERE U.ID_USUARIO = :u AND ROWNUM = 1
    """, {'u': uid}) or {}
    nombre_full = f"{(u.get('nombre') or '').upper()} {(u.get('apellido') or '').upper()}".strip() or 'USUARIO SISCA'
    plan = u.get('nombre_carrera') or 'TECNOLOGIA EN DESARROLLO DE SOFTWARE Y APLICATIVOS MOVILES SEDE CALLE 73'
    return {
        'nombre':    nombre_full,
        'doc_ident': str(u.get('codigo_estudiante') or uid),
        'periodo':   '2026-2T',
        'centro':    'SEDE CALLE 73',
        'plan':      plan,
    }


@ui_siihapi_bp.route('/horarios/<int:id_horario>/pdf', methods=['GET'])
def exportar_horario_pdf(id_horario):
    """Exporta UN horario en formato Politécnico Internacional."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    from flask import abort, Response

    try:
        sql = """
            SELECT
              H.ID_HORARIO,
              NVL(M.CODIGO, '—')         AS CODIGO,
              NVL(M.NOMBRE_MATERIA, '—') AS NOMBRE_MATERIA,
              M.CREDITOS, M.SEMESTRE,
              NVL(H.DIA, '—')            AS DIA,
              TO_CHAR(H.HORA_INICIO, 'HH24:MI') AS HORA_INICIO,
              TO_CHAR(H.HORA_FIN, 'HH24:MI')    AS HORA_FIN,
              NVL(H.AULA, '—')           AS AULA,
              NVL(H.ESTADO, 'A')         AS ESTADO,
              NVL(U.NOMBRE, '')          AS DOC_NOMBRE,
              NVL(U.APELLIDO, '')        AS DOC_APELLIDO,
              NVL(C.NOMBRE_CARRERA, '—') AS NOMBRE_CARRERA,
              NVL(C.CODIGO_CARRERA, 'GRP') AS CODIGO_CARRERA
            FROM HORARIO H
            JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
            LEFT JOIN DOCENTE D ON D.ID_DOCENTE = M.ID_DOCENTE
            LEFT JOIN USUARIO U ON U.ID_USUARIO = D.ID_USUARIO
            LEFT JOIN CARRERA C ON C.ID_CARRERA = M.ID_CARRERA
            WHERE H.ID_HORARIO = :h
        """
        h = execute_one(sql, {'h': id_horario})
        if not h:
            return abort(404)
    except Exception as exc:
        log.exception(f"[SISCA] PDF SQL error: {exc}")
        return f"<h1>Error consultando horario</h1><pre>{exc}</pre>", 500

    try:
        titular = _get_titular_actual()
        # Si el titular no tiene plan, usar el de este horario
        if titular and (titular['plan'] == '—' or not titular['plan']):
            titular['plan'] = h.get('nombre_carrera') or 'POLITECNICO INTERNACIONAL'
        pdf_bytes = _construir_pdf_politecnico(
            filas=[h],
            titular=titular,
            periodo_fechas='28/04/2026 - 04/07/2026',
        )
    except ImportError:
        return "Falta libreria reportlab. Ejecuta: pip install reportlab", 500
    except Exception as exc:
        log.exception(f"[SISCA] PDF build error: {exc}")
        return f"<h1>Error generando PDF</h1><pre>{exc}</pre>", 500

    from flask import Response
    codigo = str(h.get('codigo') or 'sisca').replace('/', '_').replace(' ', '_')
    dia    = str(h.get('dia') or '').replace('/', '_').replace(' ', '_')
    filename = f"horario_{codigo}_{dia}.pdf"
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@ui_siihapi_bp.route('/horarios/pdf-completo', methods=['GET'])
def exportar_horarios_pdf_completo():
    """Exporta TODOS los horarios (con filtros opcionales) en formato Politécnico."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    from flask import Response

    dia_filtro = request.args.get('dia', '').upper()
    aula_filtro = request.args.get('aula', '').upper()
    codigo_filtro = request.args.get('codigo', '').upper()
    carrera_filtro = request.args.get('carrera', '').strip()
    semestre_filtro = request.args.get('semestre', '').strip()
    jornada_filtro = request.args.get('jornada', '').upper().strip()
    docente_filtro = request.args.get('docente', '').strip()

    try:
        sql = """
            SELECT
              H.ID_HORARIO,
              NVL(M.CODIGO, '—')         AS CODIGO,
              NVL(M.NOMBRE_MATERIA, '—') AS NOMBRE_MATERIA,
              NVL(M.SEMESTRE, 1)         AS SEMESTRE,
              NVL(H.DIA, '—')            AS DIA,
              TO_CHAR(H.HORA_INICIO, 'HH24:MI') AS HORA_INICIO,
              TO_CHAR(H.HORA_FIN, 'HH24:MI')    AS HORA_FIN,
              NVL(H.AULA, '—')           AS AULA,
              NVL(U.NOMBRE, '')          AS DOC_NOMBRE,
              NVL(U.APELLIDO, '')        AS DOC_APELLIDO,
              NVL(C.NOMBRE_CARRERA, '—') AS NOMBRE_CARRERA,
              NVL(C.CODIGO_CARRERA, 'GRP') AS CODIGO_CARRERA
            FROM HORARIO H
            JOIN MATERIA M ON M.ID_MATERIA = H.ID_MATERIA
            LEFT JOIN DOCENTE D ON D.ID_DOCENTE = M.ID_DOCENTE
            LEFT JOIN USUARIO U ON U.ID_USUARIO = D.ID_USUARIO
            LEFT JOIN CARRERA C ON C.ID_CARRERA = M.ID_CARRERA
            WHERE H.ESTADO = 'A'
        """
        params = {}
        if dia_filtro:
            sql += " AND UPPER(H.DIA) = :d"
            params['d'] = dia_filtro
        if aula_filtro:
            sql += " AND UPPER(H.AULA) LIKE :a"
            params['a'] = f'%{aula_filtro}%'
        if codigo_filtro:
            sql += " AND UPPER(M.CODIGO) LIKE :c"
            params['c'] = f'%{codigo_filtro}%'
        if carrera_filtro:
            sql += " AND (UPPER(NVL(C.NOMBRE_CARRERA,'')) LIKE :car OR UPPER(NVL(C.CODIGO_CARRERA,'')) LIKE :car)"
            params['car'] = f'%{carrera_filtro.upper()}%'
        if semestre_filtro:
            sql += " AND TO_CHAR(NVL(M.SEMESTRE,0)) = :sem"
            params['sem'] = semestre_filtro
        if docente_filtro:
            sql += " AND UPPER(NVL(U.NOMBRE,'')||' '||NVL(U.APELLIDO,'')) LIKE :doc"
            params['doc'] = f'%{docente_filtro.upper()}%'
        if jornada_filtro == 'DIURNA':
            sql += " AND H.HORA_INICIO >= TO_DATE('07:00','HH24:MI') AND H.HORA_INICIO < TO_DATE('10:00','HH24:MI')"
        elif jornada_filtro == 'ESPECIAL':
            sql += " AND H.HORA_INICIO >= TO_DATE('10:00','HH24:MI') AND H.HORA_INICIO < TO_DATE('13:00','HH24:MI')"
        elif jornada_filtro == 'NOCTURNA':
            sql += " AND H.HORA_INICIO >= TO_DATE('18:00','HH24:MI') AND H.HORA_INICIO < TO_DATE('21:00','HH24:MI')"
        elif jornada_filtro == 'SABADO':
            sql += " AND UPPER(NVL(H.DIA,'')) = 'SABADO'"
        sql += " ORDER BY DECODE(H.DIA,'LUNES',1,'MARTES',2,'MIERCOLES',3,'JUEVES',4,'VIERNES',5,'SABADO',6,7), H.HORA_INICIO"

        filas = execute_query(sql, params, fetch=True) or []
    except Exception as exc:
        log.exception(f"[SISCA] PDF completo SQL error: {exc}")
        return f"<h1>Error consultando horarios</h1><pre>{exc}</pre>", 500

    try:
        titular = _get_titular_actual()
        # Si tiene horarios, usar la primera carrera del listado como plan si no tiene asignada
        if titular and (titular['plan'] == '—' or not titular['plan']) and filas:
            titular['plan'] = filas[0].get('nombre_carrera') or 'POLITECNICO INTERNACIONAL'
        pdf_bytes = _construir_pdf_politecnico(
            filas=filas,
            titular=titular,
            periodo_fechas='28/04/2026 - 04/07/2026',
        )
    except ImportError:
        return "Falta libreria reportlab. Ejecuta: pip install reportlab", 500
    except Exception as exc:
        log.exception(f"[SISCA] PDF completo build error: {exc}")
        return f"<h1>Error generando PDF</h1><pre>{exc}</pre>", 500

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': 'attachment; filename="horario_politecnico.pdf"'}
    )


def _mapear_hora_bloque(bloque_num):
    """Mapea el numero de bloque (1-14) a hora_inicio y hora_fin."""
    BLOQUES = {
        1:  ('06:00', '07:20'),        1:  ('06:00', '07:20'),  2:  ('07:20', '08:40'),
        3:  ('08:40', '10:00'),  4:  ('10:00', '11:20'),
        5:  ('11:20', '12:40'),  6:  ('12:40', '14:00'),
        7:  ('14:00', '15:20'),  8:  ('15:20', '16:40'),
        9:  ('16:40', '18:00'),  10: ('18:00', '19:20'),
        11: ('19:20', '20:40'),  12: ('20:40', '22:00'),
        13: ('18:30', '20:00'),  14: ('20:00', '22:00'),
    }
    return BLOQUES.get(int(bloque_num), ('06:00', '07:20'))


def _mapear_dia(codigo):
    """Mapea LU/MA/MI/JU/VI/SA a string legible."""
    DIAS = {
        'LU': 'LUNES', 'MA': 'MARTES', 'MI': 'MIERCOLES',
        'JU': 'JUEVES', 'VI': 'VIERNES', 'SA': 'SABADO',
    }
    return DIAS.get(codigo, codigo)


@api_siihapi_bp.route('/', methods=['GET'])
def api_root():
    """Healthcheck del endpoint de integracion."""
    # execute_one() nunca propaga excepciones (las atrapa y retorna None),
    # asi que el chequeo real es si obtuvimos fila, no si hubo excepcion.
    bd_ok = execute_one("SELECT 1 FROM DUAL") is not None
    return jsonify({
        'sistema': 'SISCA',
        'version': '1.0',
        'integracion_siihapi': 'activa',
        'oracle_conectado': bd_ok,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    })


@api_siihapi_bp.route('/horarios/publicar', methods=['POST'])
@_token_requerido
def publicar_horarios():
    """Recibe lote de horarios desde SIIHAPI y los inserta REALMENTE en Oracle."""
    data = request.get_json(silent=True) or {}
    periodo = data.get('periodo', '')
    horarios_in = data.get('horarios', [])

    if not horarios_in:
        return jsonify({
            'success': False,
            'error': 'Lista de horarios vacia',
            'periodo': periodo,
        }), 400

    creados = 0
    actualizados = 0
    errores = []
    sesiones_creadas = []

    for i, h in enumerate(horarios_in):
        codigo_mat = ''
        try:
            codigo_mat   = h.get('codigo_materia', '').strip()
            nombre_mat   = h.get('nombre_materia', '').strip() or codigo_mat
            docente_nom  = h.get('docente', '').strip()
            docente_em   = (h.get('docente_email') or '').strip().lower()
            salon        = h.get('salon', '').strip()
            dia_cod      = h.get('dia', 'LU')
            bloque       = h.get('bloque', 1)
            hora_inicio  = h.get('hora_inicio') or _mapear_hora_bloque(bloque)[0]
            hora_fin     = h.get('hora_fin')    or _mapear_hora_bloque(bloque)[1]
            dia          = _mapear_dia(dia_cod)

            if not codigo_mat:
                errores.append(f'Horario {i+1}: codigo_materia vacio')
                continue

            id_docente = None
            if docente_em:
                fila_doc = execute_one(
                    "SELECT D.ID_DOCENTE FROM DOCENTE D "
                    "JOIN USUARIO U ON D.ID_USUARIO = U.ID_USUARIO "
                    "WHERE LOWER(U.CORREO) = :c",
                    {'c': docente_em}
                )
                if fila_doc:
                    id_docente = fila_doc['id_docente']
                else:
                    partes = docente_nom.split(' ', 1)
                    nombre = partes[0] if partes else 'Docente'
                    apellido = partes[1] if len(partes) > 1 else 'SIIHAPI'
                    execute_dml(
                        "INSERT INTO USUARIO(ESTADO,NOMBRE,APELLIDO,CORREO,CONTRASENA,ROL,ACEPTA_TERMINOS) "
                        "VALUES('A',:n,:a,:c,'$2b$12$default','DOCENTE','S')",
                        {'n': nombre, 'a': apellido, 'c': docente_em}
                    )
                    fila_u = execute_one("SELECT ID_USUARIO FROM USUARIO WHERE CORREO=:c", {'c': docente_em})
                    if fila_u:
                        id_usu = fila_u['id_usuario']
                        execute_dml(
                            "INSERT INTO DOCENTE(ID_USUARIO, ESPECIALIDAD) VALUES(:u, 'Importado SIIHAPI')",
                            {'u': id_usu}
                        )
                        fila_d = execute_one("SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO=:u", {'u': id_usu})
                        if fila_d:
                            id_docente = fila_d['id_docente']

            fila_mat = execute_one(
                "SELECT ID_MATERIA FROM MATERIA WHERE CODIGO = :c",
                {'c': codigo_mat}
            )
            if fila_mat:
                id_materia = fila_mat['id_materia']
                if id_docente:
                    execute_dml(
                        "UPDATE MATERIA SET ID_DOCENTE = :d WHERE ID_MATERIA = :m",
                        {'d': id_docente, 'm': id_materia}
                    )
            else:
                fila_car = execute_one("SELECT ID_CARRERA FROM CARRERA WHERE ROWNUM=1")
                id_carrera = fila_car['id_carrera'] if fila_car else None
                execute_dml(
                    "INSERT INTO MATERIA(ID_CARRERA, ID_DOCENTE, NOMBRE_MATERIA, CODIGO, CREDITOS, SEMESTRE, ESTADO) "
                    "VALUES(:cr, :d, :n, :c, 3, 1, 'A')",
                    {'cr': id_carrera, 'd': id_docente, 'n': nombre_mat[:150], 'c': codigo_mat[:20]}
                )
                fila_new = execute_one("SELECT ID_MATERIA FROM MATERIA WHERE CODIGO=:c", {'c': codigo_mat})
                id_materia = fila_new['id_materia'] if fila_new else None
                creados += 1

            if not id_materia:
                errores.append(f'Horario {i+1}: no se pudo crear materia {codigo_mat}')
                continue

            fila_h = execute_one(
                "SELECT ID_HORARIO FROM HORARIO "
                "WHERE ID_MATERIA = :m AND DIA = :d "
                "AND TO_CHAR(HORA_INICIO, 'HH24:MI') = :hi",
                {'m': id_materia, 'd': dia, 'hi': hora_inicio}
            )

            hoy = date.today()
            if fila_h:
                id_horario = fila_h['id_horario']
                execute_dml(
                    "UPDATE HORARIO SET AULA = :au, ESTADO = 'A' WHERE ID_HORARIO = :h",
                    {'au': salon[:30], 'h': id_horario}
                )
                actualizados += 1
            else:
                execute_dml(
                    "INSERT INTO HORARIO(ID_MATERIA, HORA_INICIO, HORA_FIN, DIA, AULA, ESTADO) "
                    "VALUES(:m, TO_TIMESTAMP(:hi, 'YYYY-MM-DD HH24:MI'), TO_TIMESTAMP(:hf, 'YYYY-MM-DD HH24:MI'), :d, :au, 'A')",
                    {
                        'm':  id_materia,
                        'hi': f"{hoy.isoformat()} {hora_inicio}",
                        'hf': f"{hoy.isoformat()} {hora_fin}",
                        'd':  dia,
                        'au': salon[:30],
                    }
                )
                fila_new_h = execute_one(
                    "SELECT ID_HORARIO FROM HORARIO WHERE ID_MATERIA=:m AND DIA=:d "
                    "AND TO_CHAR(HORA_INICIO, 'HH24:MI')=:hi",
                    {'m': id_materia, 'd': dia, 'hi': hora_inicio}
                )
                id_horario = fila_new_h['id_horario'] if fila_new_h else None
                creados += 1

            if id_horario:
                execute_dml(
                    "INSERT INTO SESION_CLASE(ID_HORARIO, FECHA_SESION, ESTADO_SESION, MODO_CONEXION) "
                    "VALUES(:h, SYSDATE, 'ACTIVA', 'ONLINE')",
                    {'h': id_horario}
                )
                sesiones_creadas.append(f'SISCA-H{id_horario}')

        except Exception as e:
            log.exception(f"Error procesando horario {i+1}")
            errores.append(f'Horario {i+1} ({codigo_mat}): {str(e)[:200]}')

    return jsonify({
        'success':         True,
        'periodo':         periodo,
        'total_recibido':  len(horarios_in),
        'creados':         creados,
        'actualizados':    actualizados,
        'errores_total':   len(errores),
        'errores':         errores[:10],
        'sesiones':        sesiones_creadas[:20],
        'mensaje':         f'{creados} horarios nuevos + {actualizados} actualizados en SISCA Oracle',
        'timestamp':       datetime.utcnow().isoformat() + 'Z',
    }), 201


@api_siihapi_bp.route('/horarios/<id_sisca>', methods=['PUT'])
@_token_requerido
def actualizar_horario(id_sisca):
    data = request.get_json(silent=True) or {}
    try:
        if id_sisca.startswith('SISCA-H'):
            id_horario = int(id_sisca[7:])
        else:
            id_horario = int(id_sisca)
    except ValueError:
        return jsonify({'success': False, 'error': 'ID invalido'}), 400
    fila = execute_one("SELECT ID_HORARIO FROM HORARIO WHERE ID_HORARIO = :h", {'h': id_horario})
    if not fila:
        return jsonify({'success': False, 'error': 'Horario no existe en SISCA'}), 404
    if 'aula' in data:
        execute_dml("UPDATE HORARIO SET AULA = :a WHERE ID_HORARIO = :h",
                    {'a': data['aula'][:30], 'h': id_horario})
    if 'dia' in data:
        execute_dml("UPDATE HORARIO SET DIA = :d WHERE ID_HORARIO = :h",
                    {'d': _mapear_dia(data['dia']), 'h': id_horario})
    return jsonify({'success': True, 'id_sisca': id_sisca})


@api_siihapi_bp.route('/horarios/<id_sisca>', methods=['DELETE'])
@_token_requerido
def cancelar_horario(id_sisca):
    try:
        if id_sisca.startswith('SISCA-H'):
            id_horario = int(id_sisca[7:])
        else:
            id_horario = int(id_sisca)
    except ValueError:
        return jsonify({'success': False, 'error': 'ID invalido'}), 400
    execute_dml("UPDATE HORARIO SET ESTADO = 'I' WHERE ID_HORARIO = :h", {'h': id_horario})
    execute_dml("UPDATE SESION_CLASE SET ESTADO_SESION='CANCELADA' WHERE ID_HORARIO = :h",
                {'h': id_horario})
    return jsonify({'success': True, 'id_sisca': id_sisca, 'estado': 'CANCELADO'})


@api_siihapi_bp.route('/asistencia/sesion/<id_sesion>', methods=['GET'])
@_token_requerido
def consultar_asistencia_sesion(id_sesion):
    try:
        if id_sesion.startswith('SISCA-H'):
            id_horario = int(id_sesion[7:])
        else:
            id_horario = int(id_sesion)
    except ValueError:
        return jsonify({'success': False, 'error': 'ID invalido'}), 400
    fila_total = execute_one(
        "SELECT COUNT(*) AS total FROM INSCRIPCION I "
        "JOIN HORARIO H ON H.ID_MATERIA = I.ID_MATERIA "
        "WHERE H.ID_HORARIO = :h",
        {'h': id_horario}
    )
    total = fila_total['total'] if fila_total else 0
    fila_asis = execute_one(
        "SELECT COUNT(*) AS pres FROM ASISTENCIA A "
        "JOIN SESION_CLASE S ON S.ID_SESION = A.ID_SESION "
        "WHERE S.ID_HORARIO = :h AND A.ESTADO = 'PRESENTE'",
        {'h': id_horario}
    )
    presentes = fila_asis['pres'] if fila_asis else 0
    porcentaje = round((presentes / max(total, 1)) * 100, 1)
    return jsonify({
        'success':              True,
        'id_sesion':            id_sesion,
        'fecha_consulta':       datetime.utcnow().isoformat() + 'Z',
        'total_estudiantes':    total,
        'presentes':            presentes,
        'ausentes':             max(0, total - presentes),
        'porcentaje_asistencia': porcentaje,
    })


@api_siihapi_bp.route('/asistencia/materia/<codigo>/periodo/<periodo>', methods=['GET'])
@_token_requerido
def consultar_asistencia_materia(codigo, periodo):
    fila = execute_one("SELECT ID_MATERIA FROM MATERIA WHERE CODIGO = :c", {'c': codigo})
    if not fila:
        return jsonify({
            'success': True,
            'codigo_materia': codigo,
            'periodo': periodo,
            'mensaje': 'Materia no encontrada en SISCA',
            'total_inscritos': 0,
            'sesiones_realizadas': 0,
            'porcentaje_promedio': 0.0,
            'estudiantes_en_riesgo': [],
        })

    id_materia = fila['id_materia']

    # Total de sesiones realizadas en el periodo
    sesiones = execute_one(
        """SELECT COUNT(*) AS N
             FROM SESION_CLASE sc
             JOIN HORARIO h ON h.ID_HORARIO = sc.ID_HORARIO
            WHERE h.ID_MATERIA = :m
              AND sc.PERIODO   = :p
              AND sc.ESTADO    = 'CERRADA'""",
        {'m': id_materia, 'p': periodo},
    )
    total_sesiones = (sesiones or {}).get('n', 0)

    if total_sesiones == 0:
        return jsonify({
            'success': True,
            'codigo_materia': codigo,
            'periodo': periodo,
            'total_inscritos': 0,
            'sesiones_realizadas': 0,
            'porcentaje_promedio': 0.0,
            'estudiantes_en_riesgo': [],
        })

    # Por-estudiante: cuántas sesiones asistió vs total
    filas = execute_query(
        """SELECT e.ID_ESTUDIANTE,
                  e.NOMBRE || ' ' || e.APELLIDO AS nombre,
                  e.EMAIL,
                  COUNT(a.ID_ASISTENCIA) AS asistencias
             FROM ESTUDIANTE e
             JOIN MATRICULA m2 ON m2.ID_ESTUDIANTE = e.ID_ESTUDIANTE
             JOIN HORARIO   h  ON h.ID_HORARIO = m2.ID_HORARIO
             JOIN SESION_CLASE sc ON sc.ID_HORARIO = h.ID_HORARIO
                                  AND sc.PERIODO  = :p
                                  AND sc.ESTADO   = 'CERRADA'
             LEFT JOIN ASISTENCIA a ON a.ID_SESION     = sc.ID_SESION
                                   AND a.ID_ESTUDIANTE = e.ID_ESTUDIANTE
                                   AND a.ESTADO        = 'PRESENTE'
            WHERE h.ID_MATERIA = :m
            GROUP BY e.ID_ESTUDIANTE, e.NOMBRE, e.APELLIDO, e.EMAIL""",
        {'m': id_materia, 'p': periodo},
    )

    total_inscritos = len(filas)
    estudiantes_en_riesgo = []
    suma_pct = 0.0

    for f in filas:
        asistencias = f.get('asistencias', 0) or 0
        pct = round(asistencias / total_sesiones * 100, 1) if total_sesiones > 0 else 0.0
        suma_pct += pct
        if pct < 75.0:
            estudiantes_en_riesgo.append({
                'id_estudiante': f.get('id_estudiante'),
                'nombre':        f.get('nombre', ''),
                'email':         f.get('email', ''),
                'porcentaje_asistencia': pct,
            })

    porcentaje_promedio = round(suma_pct / total_inscritos, 1) if total_inscritos > 0 else 0.0

    return jsonify({
        'success':               True,
        'codigo_materia':        codigo,
        'periodo':               periodo,
        'total_inscritos':       total_inscritos,
        'sesiones_realizadas':   total_sesiones,
        'porcentaje_promedio':   porcentaje_promedio,
        'estudiantes_en_riesgo': estudiantes_en_riesgo,
        'timestamp':             datetime.utcnow().isoformat() + 'Z',
    })
