"""
SIIHAPI - Exportacion de auditoria en multiples formatos.

Genera reportes en:
    - Excel  (.xlsx) usando openpyxl
    - PDF    (.pdf)  usando reportlab
    - Word   (.docx) usando python-docx
    - PowerPoint (.pptx) usando python-pptx
"""
import io
from datetime import datetime

from apps.autenticacion.models import IntentoLogin
from apps.integracion_sisca.models import IntegracionLog
from apps.horarios.models import AsignacionIA


# Paleta institucional (azul Politecnico)
COLOR_PRIMARIO = '1F6FEB'  # azul
COLOR_SECUNDARIO = '4D9BFF'
COLOR_LIME = '84CC16'
COLOR_RED = 'EF4444'
COLOR_TXT = '111111'


def _cargar_datos(limite_intentos=200, limite_sisca=200, limite_ia=100):
    """Carga los datos comunes a todos los formatos."""
    return {
        'fecha_generacion':  datetime.now(),
        'intentos':          list(IntentoLogin.objects.order_by('-fecha')[:limite_intentos]),
        'logs_sisca':        list(IntegracionLog.objects.order_by('-fecha')[:limite_sisca]),
        'asignaciones_ia':   list(AsignacionIA.objects.order_by('-fecha_inicio')[:limite_ia]),
        'stats': {
            'logins_exitosos':  IntentoLogin.objects.filter(exitoso=True).count(),
            'logins_fallidos':  IntentoLogin.objects.filter(exitoso=False).count(),
            'eventos_sisca':    IntegracionLog.objects.count(),
            'sisca_exitos':     IntegracionLog.objects.filter(estado='EXITO').count(),
            'sisca_errores':    IntegracionLog.objects.filter(estado='ERROR').count(),
            'ejecuciones_ia':   AsignacionIA.objects.count(),
            'ia_exitosas':      AsignacionIA.objects.filter(estado='COMPLETADA').count(),
            'ia_fallidas':      AsignacionIA.objects.filter(estado='FALLIDA').count(),
        }
    }


# ════════════════════════════════════════════════════════════════
#  1. EXCEL
# ════════════════════════════════════════════════════════════════
def exportar_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    datos = _cargar_datos()
    wb = Workbook()

    blue_fill = PatternFill('solid', fgColor=COLOR_PRIMARIO)
    bold_white = Font(bold=True, color='FFFFFF', size=11)
    bold = Font(bold=True, size=10)
    center = Alignment(horizontal='center', vertical='center')
    thin = Side(border_style='thin', color='CCCCCC')
    border_cell = Border(left=thin, right=thin, top=thin, bottom=thin)

    def estilo_header(ws, row, cols):
        for col in range(1, cols + 1):
            c = ws.cell(row=row, column=col)
            c.fill = blue_fill
            c.font = bold_white
            c.alignment = center
            c.border = border_cell

    # ── Hoja 1: Resumen ──
    ws = wb.active
    ws.title = 'Resumen'
    ws['A1'] = 'SIIHAPI · Reporte de Auditoría'
    ws['A1'].font = Font(bold=True, size=16, color=COLOR_PRIMARIO)
    ws.merge_cells('A1:D1')
    ws['A2'] = f'Generado: {datos["fecha_generacion"].strftime("%d/%m/%Y %H:%M:%S")}'
    ws['A2'].font = Font(italic=True, color='666666')
    ws.merge_cells('A2:D2')

    ws['A4'] = 'Métrica'; ws['B4'] = 'Valor'
    estilo_header(ws, 4, 2)
    fila = 5
    metricas = [
        ('Logins exitosos', datos['stats']['logins_exitosos']),
        ('Logins fallidos', datos['stats']['logins_fallidos']),
        ('Total eventos SISCA', datos['stats']['eventos_sisca']),
        ('Eventos SISCA exitosos', datos['stats']['sisca_exitos']),
        ('Eventos SISCA fallidos', datos['stats']['sisca_errores']),
        ('Ejecuciones Motor IA', datos['stats']['ejecuciones_ia']),
        ('Ejecuciones IA exitosas', datos['stats']['ia_exitosas']),
        ('Ejecuciones IA fallidas', datos['stats']['ia_fallidas']),
    ]
    for nombre, valor in metricas:
        ws.cell(row=fila, column=1, value=nombre).font = bold
        ws.cell(row=fila, column=2, value=valor)
        fila += 1
    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 15

    # ── Hoja 2: Intentos de login ──
    ws2 = wb.create_sheet('Intentos de Login')
    headers = ['Fecha', 'Correo', 'IP', 'Resultado', 'User Agent']
    for col, h in enumerate(headers, 1):
        ws2.cell(row=1, column=col, value=h)
    estilo_header(ws2, 1, len(headers))
    for i, intento in enumerate(datos['intentos'], 2):
        ws2.cell(row=i, column=1, value=intento.fecha.strftime('%d/%m/%Y %H:%M:%S'))
        ws2.cell(row=i, column=2, value=intento.correo)
        ws2.cell(row=i, column=3, value=intento.ip or '')
        ws2.cell(row=i, column=4, value='Exitoso' if intento.exitoso else 'Fallido')
        ws2.cell(row=i, column=5, value=(intento.user_agent or '')[:80])
    for col, width in [('A', 20), ('B', 32), ('C', 16), ('D', 12), ('E', 50)]:
        ws2.column_dimensions[col].width = width

    # ── Hoja 3: Eventos SISCA ──
    ws3 = wb.create_sheet('Eventos SISCA')
    headers = ['Fecha', 'Operación', 'Estado', 'Endpoint', 'HTTP', 'Intentos', 'Duración (ms)', 'Error']
    for col, h in enumerate(headers, 1):
        ws3.cell(row=1, column=col, value=h)
    estilo_header(ws3, 1, len(headers))
    for i, log in enumerate(datos['logs_sisca'], 2):
        ws3.cell(row=i, column=1, value=log.fecha.strftime('%d/%m/%Y %H:%M:%S'))
        ws3.cell(row=i, column=2, value=log.get_operacion_display())
        ws3.cell(row=i, column=3, value=log.estado)
        ws3.cell(row=i, column=4, value=log.endpoint or '')
        ws3.cell(row=i, column=5, value=log.codigo_http or '')
        ws3.cell(row=i, column=6, value=log.intentos)
        ws3.cell(row=i, column=7, value=log.duracion_ms or 0)
        ws3.cell(row=i, column=8, value=(log.error_msg or '')[:80])
    for col, width in [('A', 20), ('B', 32), ('C', 12), ('D', 36), ('E', 8), ('F', 10), ('G', 14), ('H', 40)]:
        ws3.column_dimensions[col].width = width

    # ── Hoja 4: Ejecuciones Motor IA ──
    ws4 = wb.create_sheet('Ejecuciones IA')
    headers = ['Job ID', 'Periodo', 'Estado', 'Inicio', 'Duración (ms)', 'Matrículas', 'Asignadas', 'Conflictos']
    for col, h in enumerate(headers, 1):
        ws4.cell(row=1, column=col, value=h)
    estilo_header(ws4, 1, len(headers))
    for i, a in enumerate(datos['asignaciones_ia'], 2):
        ws4.cell(row=i, column=1, value=a.job_id)
        ws4.cell(row=i, column=2, value=a.periodo.codigo)
        ws4.cell(row=i, column=3, value=a.estado)
        ws4.cell(row=i, column=4, value=a.fecha_inicio.strftime('%d/%m/%Y %H:%M:%S') if a.fecha_inicio else '')
        ws4.cell(row=i, column=5, value=a.duracion_ms or 0)
        ws4.cell(row=i, column=6, value=a.total_matriculas)
        ws4.cell(row=i, column=7, value=a.asignaciones_exitosas)
        ws4.cell(row=i, column=8, value=a.conflictos_residuales)
    for col, width in [('A', 24), ('B', 12), ('C', 14), ('D', 20), ('E', 14), ('F', 14), ('G', 14), ('H', 12)]:
        ws4.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


# ════════════════════════════════════════════════════════════════
#  2. PDF
# ════════════════════════════════════════════════════════════════
def exportar_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    )
    from reportlab.lib.enums import TA_CENTER

    datos = _cargar_datos(limite_intentos=80, limite_sisca=80, limite_ia=50)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=2*cm, rightMargin=2*cm,
                             topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle('titulo', parent=styles['Heading1'],
                                    fontSize=20, textColor=colors.HexColor('#' + COLOR_PRIMARIO),
                                    alignment=TA_CENTER, spaceAfter=14)
    subtitulo_style = ParagraphStyle('subtitulo', parent=styles['Heading2'],
                                       fontSize=14, textColor=colors.HexColor('#' + COLOR_PRIMARIO),
                                       spaceAfter=10)
    centrado = ParagraphStyle('centro', parent=styles['Normal'], alignment=TA_CENTER, fontSize=10, textColor=colors.grey)

    story = []

    # Portada
    story.append(Spacer(1, 4*cm))
    story.append(Paragraph('SIIHAPI', titulo_style))
    story.append(Paragraph('Reporte de Auditoría', titulo_style))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph('Sistema Inteligente e Integrado de Horarios Académicos', centrado))
    story.append(Paragraph('Politécnico Internacional', centrado))
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph(f'Generado el {datos["fecha_generacion"].strftime("%d/%m/%Y a las %H:%M:%S")}', centrado))
    story.append(PageBreak())

    # Resumen ejecutivo
    story.append(Paragraph('1. Resumen Ejecutivo', subtitulo_style))
    s = datos['stats']
    resumen = [
        ['Métrica', 'Valor'],
        ['Logins exitosos', str(s['logins_exitosos'])],
        ['Logins fallidos', str(s['logins_fallidos'])],
        ['Total eventos SISCA', str(s['eventos_sisca'])],
        ['Eventos SISCA exitosos', str(s['sisca_exitos'])],
        ['Eventos SISCA fallidos', str(s['sisca_errores'])],
        ['Ejecuciones Motor IA', str(s['ejecuciones_ia'])],
        ['Ejecuciones IA exitosas', str(s['ia_exitosas'])],
        ['Ejecuciones IA fallidas', str(s['ia_fallidas'])],
    ]
    t = Table(resumen, colWidths=[10*cm, 4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#' + COLOR_PRIMARIO)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # Intentos de login
    story.append(PageBreak())
    story.append(Paragraph('2. Intentos de Login (últimos 80)', subtitulo_style))
    if datos['intentos']:
        data = [['Fecha', 'Correo', 'IP', 'Resultado']]
        for i in datos['intentos'][:80]:
            data.append([
                i.fecha.strftime('%d/%m %H:%M'),
                (i.correo or '')[:30],
                (i.ip or '')[:15],
                'OK' if i.exitoso else 'FALLO'
            ])
        t = Table(data, colWidths=[3*cm, 7*cm, 3.5*cm, 2.5*cm])
        t.setStyle(_estilo_tabla())
        story.append(t)
    else:
        story.append(Paragraph('Sin intentos de login registrados.', styles['Normal']))

    # Eventos SISCA
    story.append(PageBreak())
    story.append(Paragraph('3. Eventos de Integración SISCA', subtitulo_style))
    if datos['logs_sisca']:
        data = [['Fecha', 'Operación', 'Estado', 'HTTP', 'Dur(ms)']]
        for l in datos['logs_sisca'][:80]:
            data.append([
                l.fecha.strftime('%d/%m %H:%M'),
                l.get_operacion_display()[:25],
                l.estado,
                str(l.codigo_http or '-'),
                str(l.duracion_ms or 0)
            ])
        t = Table(data, colWidths=[3*cm, 6*cm, 2.5*cm, 2*cm, 2.5*cm])
        t.setStyle(_estilo_tabla())
        story.append(t)
    else:
        story.append(Paragraph('Sin eventos de integración registrados.', styles['Normal']))

    # Ejecuciones IA
    story.append(PageBreak())
    story.append(Paragraph('4. Ejecuciones del Motor IA', subtitulo_style))
    if datos['asignaciones_ia']:
        data = [['Job ID', 'Estado', 'Matr.', 'Asig.', 'Confl.', 'Dur(ms)']]
        for a in datos['asignaciones_ia'][:50]:
            data.append([
                a.job_id[:18],
                a.estado,
                str(a.total_matriculas),
                str(a.asignaciones_exitosas),
                str(a.conflictos_residuales),
                str(a.duracion_ms or 0)
            ])
        t = Table(data, colWidths=[5*cm, 3*cm, 2*cm, 2*cm, 2*cm, 2.5*cm])
        t.setStyle(_estilo_tabla())
        story.append(t)
    else:
        story.append(Paragraph('Sin ejecuciones del Motor IA registradas.', styles['Normal']))

    doc.build(story)
    buf.seek(0)
    return buf.read(), 'application/pdf'


def _estilo_tabla():
    from reportlab.platypus import TableStyle
    from reportlab.lib import colors
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#' + COLOR_PRIMARIO)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F8FC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])


# ════════════════════════════════════════════════════════════════
#  3. WORD (.docx)
# ════════════════════════════════════════════════════════════════
def exportar_word():
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    datos = _cargar_datos(limite_intentos=100, limite_sisca=100, limite_ia=50)

    doc = Document()

    # Portada
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('\n\n\nSIIHAPI')
    run.font.size = Pt(36)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x1F, 0x6F, 0xEB)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('Reporte de Auditoría')
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor(0x1F, 0x6F, 0xEB)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run('\nSistema Inteligente e Integrado de Horarios Académicos\nPolitécnico Internacional')
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f'\n\nGenerado el {datos["fecha_generacion"].strftime("%d/%m/%Y a las %H:%M:%S")}').italic = True
    doc.add_page_break()

    # Resumen
    doc.add_heading('1. Resumen Ejecutivo', level=1)
    s = datos['stats']
    tabla = doc.add_table(rows=1, cols=2)
    tabla.style = 'Light Grid Accent 1'
    hdr = tabla.rows[0].cells
    hdr[0].text = 'Métrica'; hdr[1].text = 'Valor'
    for nombre, valor in [
        ('Logins exitosos', s['logins_exitosos']),
        ('Logins fallidos', s['logins_fallidos']),
        ('Total eventos SISCA', s['eventos_sisca']),
        ('Eventos SISCA exitosos', s['sisca_exitos']),
        ('Eventos SISCA fallidos', s['sisca_errores']),
        ('Ejecuciones Motor IA', s['ejecuciones_ia']),
        ('Ejecuciones IA exitosas', s['ia_exitosas']),
        ('Ejecuciones IA fallidas', s['ia_fallidas']),
    ]:
        row = tabla.add_row().cells
        row[0].text = nombre
        row[1].text = str(valor)

    # Intentos
    doc.add_page_break()
    doc.add_heading('2. Intentos de Login', level=1)
    t = doc.add_table(rows=1, cols=4)
    t.style = 'Light Grid Accent 1'
    h = t.rows[0].cells
    h[0].text = 'Fecha'; h[1].text = 'Correo'; h[2].text = 'IP'; h[3].text = 'Resultado'
    for i in datos['intentos']:
        r = t.add_row().cells
        r[0].text = i.fecha.strftime('%d/%m/%Y %H:%M')
        r[1].text = i.correo
        r[2].text = i.ip or '-'
        r[3].text = 'Exitoso' if i.exitoso else 'Fallido'

    # Eventos SISCA
    doc.add_page_break()
    doc.add_heading('3. Eventos de Integración SISCA', level=1)
    t = doc.add_table(rows=1, cols=5)
    t.style = 'Light Grid Accent 1'
    h = t.rows[0].cells
    h[0].text = 'Fecha'; h[1].text = 'Operación'; h[2].text = 'Estado'; h[3].text = 'HTTP'; h[4].text = 'Dur (ms)'
    for l in datos['logs_sisca']:
        r = t.add_row().cells
        r[0].text = l.fecha.strftime('%d/%m/%Y %H:%M')
        r[1].text = l.get_operacion_display()
        r[2].text = l.estado
        r[3].text = str(l.codigo_http or '-')
        r[4].text = str(l.duracion_ms or 0)

    # Ejecuciones IA
    doc.add_page_break()
    doc.add_heading('4. Ejecuciones del Motor IA', level=1)
    t = doc.add_table(rows=1, cols=6)
    t.style = 'Light Grid Accent 1'
    h = t.rows[0].cells
    h[0].text = 'Job ID'; h[1].text = 'Periodo'; h[2].text = 'Estado'
    h[3].text = 'Matrículas'; h[4].text = 'Asignadas'; h[5].text = 'Conflictos'
    for a in datos['asignaciones_ia']:
        r = t.add_row().cells
        r[0].text = a.job_id
        r[1].text = a.periodo.codigo
        r[2].text = a.estado
        r[3].text = str(a.total_matriculas)
        r[4].text = str(a.asignaciones_exitosas)
        r[5].text = str(a.conflictos_residuales)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


# ════════════════════════════════════════════════════════════════
#  4. POWERPOINT (.pptx)
# ════════════════════════════════════════════════════════════════
def exportar_pptx():
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    datos = _cargar_datos(limite_intentos=30, limite_sisca=30, limite_ia=20)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    BLUE = RGBColor(0x1F, 0x6F, 0xEB)

    # Slide 1: Portada
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    tb = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11.3), Inches(2.5))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = 'SIIHAPI'
    r.font.size = Pt(60); r.font.bold = True; r.font.color.rgb = BLUE

    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r = p2.add_run(); r.text = 'Reporte de Auditoría'
    r.font.size = Pt(36); r.font.color.rgb = BLUE

    p3 = tf.add_paragraph(); p3.alignment = PP_ALIGN.CENTER
    r = p3.add_run(); r.text = '\nPolitécnico Internacional'
    r.font.size = Pt(22); r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    p4 = tf.add_paragraph(); p4.alignment = PP_ALIGN.CENTER
    r = p4.add_run(); r.text = f'Generado el {datos["fecha_generacion"].strftime("%d/%m/%Y %H:%M")}'
    r.font.size = Pt(14); r.font.italic = True; r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    # Slide 2: Resumen ejecutivo
    s = datos['stats']
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_titulo(slide, '1. Resumen Ejecutivo')

    # 2x4 grid de KPIs
    kpis = [
        ('Logins Exitosos', s['logins_exitosos'], 0x84, 0xCC, 0x16),
        ('Logins Fallidos', s['logins_fallidos'], 0xEF, 0x44, 0x44),
        ('Eventos SISCA', s['eventos_sisca'], 0x22, 0xD3, 0xEE),
        ('Errores SISCA', s['sisca_errores'], 0xF5, 0x9E, 0x0B),
        ('Total IA', s['ejecuciones_ia'], 0x1F, 0x6F, 0xEB),
        ('IA Exitosas', s['ia_exitosas'], 0x84, 0xCC, 0x16),
        ('IA Fallidas', s['ia_fallidas'], 0xEF, 0x44, 0x44),
        ('SISCA Exitos', s['sisca_exitos'], 0x84, 0xCC, 0x16),
    ]
    for i, (label, valor, r_, g_, b_) in enumerate(kpis):
        col = i % 4
        row = i // 4
        left = Inches(0.7 + col * 3.05)
        top = Inches(1.7 + row * 2.5)
        box = slide.shapes.add_textbox(left, top, Inches(2.85), Inches(2.2))
        tf = box.text_frame
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = label
        r.font.size = Pt(14); r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
        r = p2.add_run(); r.text = str(valor)
        r.font.size = Pt(48); r.font.bold = True; r.font.color.rgb = RGBColor(r_, g_, b_)

    # Slide 3: Intentos de login
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_titulo(slide, '2. Intentos de Login (últimos 30)')
    _tabla_pptx(slide,
        ['Fecha', 'Correo', 'Resultado'],
        [[i.fecha.strftime('%d/%m %H:%M'), i.correo, 'OK' if i.exitoso else 'FALLO']
         for i in datos['intentos'][:25]],
        col_widths=[Inches(2.5), Inches(7), Inches(2)])

    # Slide 4: Eventos SISCA
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_titulo(slide, '3. Eventos de Integración SISCA (últimos 30)')
    _tabla_pptx(slide,
        ['Fecha', 'Operación', 'Estado', 'HTTP', 'ms'],
        [[l.fecha.strftime('%d/%m %H:%M'), l.get_operacion_display()[:30],
          l.estado, str(l.codigo_http or '-'), str(l.duracion_ms or 0)]
         for l in datos['logs_sisca'][:25]],
        col_widths=[Inches(2), Inches(5), Inches(1.5), Inches(1.5), Inches(1.5)])

    # Slide 5: Ejecuciones IA
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_titulo(slide, '4. Ejecuciones del Motor IA')
    _tabla_pptx(slide,
        ['Job ID', 'Estado', 'Asignadas', 'Conflictos', 'ms'],
        [[a.job_id[:22], a.estado, str(a.asignaciones_exitosas),
          str(a.conflictos_residuales), str(a.duracion_ms or 0)]
         for a in datos['asignaciones_ia'][:20]],
        col_widths=[Inches(3.5), Inches(2.5), Inches(2), Inches(2), Inches(1.5)])

    # Slide 6: Cierre
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(11.3), Inches(2))
    tf = tb.text_frame; p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = '¡Gracias!'
    r.font.size = Pt(60); r.font.bold = True; r.font.color.rgb = BLUE
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r = p2.add_run(); r.text = 'SIIHAPI · Politécnico Internacional'
    r.font.size = Pt(20); r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.read(), 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


def _slide_titulo(slide, texto):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.8))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    r = p.add_run(); r.text = texto
    r.font.size = Pt(28); r.font.bold = True
    r.font.color.rgb = RGBColor(0x1F, 0x6F, 0xEB)


def _tabla_pptx(slide, headers, rows, col_widths):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    rows = rows[:25]
    table_shape = slide.shapes.add_table(
        len(rows) + 1, len(headers),
        Inches(0.5), Inches(1.3),
        sum(col_widths, Inches(0)), Inches(5.8)
    )
    table = table_shape.table

    for i, w in enumerate(col_widths):
        table.columns[i].width = w

    for col, h in enumerate(headers):
        cell = table.cell(0, col)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                r.font.bold = True
                r.font.size = Pt(11)
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0x1F, 0x6F, 0xEB)

    for i, row in enumerate(rows, 1):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)


# ════════════════════════════════════════════════════════════════
#  Dispatcher
# ════════════════════════════════════════════════════════════════
HANDLERS = {
    'xlsx': (exportar_excel, 'auditoria_siihapi.xlsx'),
    'pdf':  (exportar_pdf,   'auditoria_siihapi.pdf'),
    'docx': (exportar_word,  'auditoria_siihapi.docx'),
    'pptx': (exportar_pptx,  'auditoria_siihapi.pptx'),
}
