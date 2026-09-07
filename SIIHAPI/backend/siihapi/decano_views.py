"""
SIIHAPI · Vistas del Modulo del Decano (Sprint 4, 2026-09-06).

Archivo NUEVO (no se agrega a frontend_views.py, ya con 5000+ lineas) --
importa sus helpers (permisos, _construir_pdf_generico_politecnico,
_construir_excel_generico_politecnico) de ese modulo en vez de duplicarlos.

Estructura:
    A. Helper resolver_jornada() -- Entregable 3, Reporte #2
    B. Panel del Decano (dashboard)
    C. MatrizPlaneacion -- CRUD + transiciones de estado (Entregable 2.A)
    D. ReglaIntervencion / PlantillaCorreo / LogIntervencion -- CRUD +
       "disparar ahora" (Entregable 2.B) + reenvio manual
    E. Los 7 reportes del Decano (Entregable 3)
"""
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.academico.models import Facultad, Programa, Materia
from apps.matriculas.models import Periodo, Estudiante
from apps.infraestructura.models import Sede, Salon
from apps.personal.models import Docente
from apps.horarios.models import Horario, AsignacionIA, SolicitudReprogramacion
from apps.asistencias.models import AsistenciaEstudiante, AsistenciaDocente, AlertaRiesgo
from apps.bienestar.models import CasoBienestar
from apps.eventos.models import Evento, ReservaRecurso
from apps.mentoria.models import AsignacionMentoria
from apps.decano.models import (
    Jornada, PerfilDecano, MatrizPlaneacion, ReglaIntervencion,
    PlantillaCorreo, LogIntervencion,
)

from . import frontend_views as fv
from .permisos import decano_required, operacion_required, staff_required


# ════════════════════════════════════════════════════════════════
#  A. HELPER -- resolucion de Jornada por rango horario del Bloque
# ════════════════════════════════════════════════════════════════

def resolver_jornada(bloque):
    """Dado un horarios.Bloque, devuelve la decano.Jornada activa cuyo
    rango [hora_inicio_tipica, hora_fin_tipica) lo contiene, o None si no
    hay ninguna (o el bloque no trae hora_inicio). Mismo criterio que usa
    apps.decano.tasks._evaluar_asistencia_jornada_pct -- no se duplica la
    logica de negocio, solo se re-expresa por-fila para el Reporte #2."""
    if not bloque or not bloque.hora_inicio:
        return None
    return Jornada.objects.filter(
        activa=True,
        hora_inicio_tipica__lte=bloque.hora_inicio,
        hora_fin_tipica__gt=bloque.hora_inicio,
    ).order_by('orden').first()


# ════════════════════════════════════════════════════════════════
#  B. PANEL DEL DECANO
# ════════════════════════════════════════════════════════════════

@decano_required
def decano_panel(request):
    matrices = MatrizPlaneacion.objects.select_related('facultad', 'periodo', 'sede', 'jornada')
    reglas_activas = ReglaIntervencion.objects.filter(activa=True).count()
    logs_recientes = LogIntervencion.objects.select_related('regla').order_by('-fecha_disparo')[:8]
    context = {
        'kpis': {
            'matrices_borrador':    matrices.filter(estado='BORRADOR').count(),
            'matrices_en_revision': matrices.filter(estado='EN_REVISION').count(),
            'matrices_aprobadas':   matrices.filter(estado='APROBADO').count(),
            'matrices_publicadas':  matrices.filter(estado='PUBLICADO').count(),
            'reglas_activas':       reglas_activas,
            'logs_fallidos':        LogIntervencion.objects.filter(estado='FALLIDO').count(),
        },
        'matrices_recientes': matrices.order_by('-created_at')[:6],
        'logs_recientes':     logs_recientes,
    }
    return render(request, 'dashboard/decano_panel.html', context)


# ════════════════════════════════════════════════════════════════
#  C. MATRIZ DE PLANEACION -- CRUD + transiciones (Entregable 2.A)
# ════════════════════════════════════════════════════════════════

@decano_required
def matriz_planeacion_lista(request):
    matrices = MatrizPlaneacion.objects.select_related('facultad', 'periodo', 'sede', 'jornada').order_by('-created_at')
    return render(request, 'dashboard/matriz_planeacion_lista.html', {'matrices': matrices})


@decano_required
def matriz_planeacion_crear(request):
    if request.method == 'POST':
        try:
            facultad = get_object_or_404(Facultad, id_facultad=request.POST.get('facultad'))
            periodo = get_object_or_404(Periodo, id_periodo=request.POST.get('periodo'))
            sede = get_object_or_404(Sede, id_sede=request.POST.get('sede'))
            jornada = get_object_or_404(Jornada, id_jornada=request.POST.get('jornada'))
            matriz = MatrizPlaneacion.objects.create(
                nombre=request.POST.get('nombre') or f'Matriz {facultad.codigo} {periodo.codigo}',
                facultad=facultad, periodo=periodo, sede=sede, jornada=jornada,
                ciclo=request.POST.get('ciclo', ''),
                created_by=request.user,
            )
            messages.success(request, 'Matriz de planeación creada en estado Borrador.')
            return redirect('matriz_planeacion_detalle', matriz.id_matriz)
        except Exception as exc:
            messages.error(request, f'No se pudo crear la matriz: {str(exc)[:200]}')
    return render(request, 'dashboard/matriz_planeacion_form.html', {
        'facultades': Facultad.objects.filter(activa=True).order_by('nombre'),
        'periodos':   Periodo.objects.all().order_by('-codigo'),
        'sedes':      Sede.objects.filter(estado='A').order_by('nombre'),
        'jornadas':   Jornada.objects.filter(activa=True).order_by('orden'),
    })


@decano_required
def matriz_planeacion_detalle(request, id_matriz):
    matriz = get_object_or_404(
        MatrizPlaneacion.objects.select_related('facultad', 'periodo', 'sede', 'jornada', 'asignacion_ia', 'aprobado_por', 'publicado_por', 'created_by'),
        id_matriz=id_matriz,
    )
    ultima_ia_disponible = AsignacionIA.objects.filter(periodo=matriz.periodo, estado='COMPLETADA').order_by('-fecha_inicio').first()
    return render(request, 'dashboard/matriz_planeacion_detalle.html', {
        'matriz': matriz,
        'ultima_ia_disponible': ultima_ia_disponible,
    })


@decano_required
def matriz_planeacion_vincular_ia(request, id_matriz):
    matriz = get_object_or_404(MatrizPlaneacion, id_matriz=id_matriz)
    if request.method != 'POST':
        return redirect('matriz_planeacion_detalle', id_matriz)
    corrida = AsignacionIA.objects.filter(periodo=matriz.periodo, estado='COMPLETADA').order_by('-fecha_inicio').first()
    if not corrida:
        messages.error(request, 'No hay ninguna corrida COMPLETADA del Motor IA para el periodo de esta matriz. Ejecuta el Motor IA (Operación > Motor IA) primero.')
        return redirect('matriz_planeacion_detalle', id_matriz)
    matriz.asignacion_ia = corrida
    snapshot = dict(matriz.parametros_simulacion or {})
    snapshot['ultima_corrida_ia'] = {
        'job_id': corrida.job_id,
        'asignaciones_exitosas': corrida.asignaciones_exitosas,
        'conflictos_residuales': corrida.conflictos_residuales,
        'total_matriculas': corrida.total_matriculas,
        'vinculado_en': timezone.now().isoformat(),
    }
    matriz.parametros_simulacion = snapshot
    matriz.save(update_fields=['asignacion_ia', 'parametros_simulacion', 'updated_at'])
    messages.success(request, f'Corrida del Motor IA (job {corrida.job_id}) vinculada a la matriz.')
    return redirect('matriz_planeacion_detalle', id_matriz)


@decano_required
def matriz_planeacion_enviar_revision(request, id_matriz):
    matriz = get_object_or_404(MatrizPlaneacion, id_matriz=id_matriz)
    if request.method == 'POST' and matriz.estado == 'BORRADOR':
        matriz.estado = 'EN_REVISION'
        matriz.save(update_fields=['estado', 'updated_at'])
        messages.success(request, 'Matriz enviada a revisión.')
    else:
        messages.error(request, 'Solo una matriz en Borrador puede enviarse a revisión.')
    return redirect('matriz_planeacion_detalle', id_matriz)


@operacion_required
def matriz_planeacion_aprobar(request, id_matriz):
    matriz = get_object_or_404(MatrizPlaneacion, id_matriz=id_matriz)
    if request.method == 'POST' and matriz.estado == 'EN_REVISION':
        matriz.estado = 'APROBADO'
        matriz.aprobado_por = request.user
        matriz.fecha_aprobacion = timezone.now()
        matriz.save(update_fields=['estado', 'aprobado_por', 'fecha_aprobacion', 'updated_at'])
        messages.success(request, 'Matriz aprobada.')
    else:
        messages.error(request, 'Solo una matriz En revisión puede aprobarse.')
    return redirect('matriz_planeacion_detalle', id_matriz)


@decano_required
def matriz_planeacion_publicar(request, id_matriz):
    matriz = get_object_or_404(MatrizPlaneacion, id_matriz=id_matriz)
    if request.method == 'POST' and matriz.estado == 'APROBADO':
        matriz.estado = 'PUBLICADO'
        matriz.publicado_por = request.user
        matriz.fecha_publicacion = timezone.now()
        matriz.save(update_fields=['estado', 'publicado_por', 'fecha_publicacion', 'updated_at'])
        messages.success(request, 'Matriz publicada. Para llevar los horarios asociados a SISCA usa el Centro de Publicación (Operación > Centro de publicación).')
    else:
        messages.error(request, 'Solo una matriz Aprobada puede publicarse.')
    return redirect('matriz_planeacion_detalle', id_matriz)


# ════════════════════════════════════════════════════════════════
#  D. MOTOR DE REGLAS -- ReglaIntervencion / PlantillaCorreo / LogIntervencion
#     (Entregable 2.B, Entregable 4)
# ════════════════════════════════════════════════════════════════

@decano_required
def reglas_lista(request):
    reglas = ReglaIntervencion.objects.select_related('plantilla').order_by('-prioridad', 'nombre')
    return render(request, 'dashboard/reglas_lista.html', {'reglas': reglas})


def _guardar_regla_desde_post(request, regla=None):
    plantilla = get_object_or_404(PlantillaCorreo, id_plantilla=request.POST.get('plantilla'))
    datos = dict(
        nombre=request.POST.get('nombre', '').strip(),
        descripcion=request.POST.get('descripcion', '').strip(),
        metrica=request.POST.get('metrica'),
        operador=request.POST.get('operador'),
        umbral=request.POST.get('umbral') or 0,
        ventana_dias=int(request.POST.get('ventana_dias') or 7),
        destinatarios_roles=[r for r in request.POST.getlist('destinatarios_roles') if r],
        plantilla=plantilla,
        activa=bool(request.POST.get('activa')),
        prioridad=int(request.POST.get('prioridad') or 5),
        cooldown_horas=int(request.POST.get('cooldown_horas') or 24),
    )
    if regla is None:
        return ReglaIntervencion.objects.create(created_by=request.user, **datos)
    for campo, valor in datos.items():
        setattr(regla, campo, valor)
    regla.save()
    return regla


@decano_required
def regla_crear(request):
    if request.method == 'POST':
        try:
            regla = _guardar_regla_desde_post(request)
            messages.success(request, 'Regla de intervención creada.')
            return redirect('reglas_lista')
        except Exception as exc:
            messages.error(request, f'No se pudo crear la regla: {str(exc)[:200]}')
    return render(request, 'dashboard/regla_form.html', {
        'regla': None,
        'metricas': ReglaIntervencion.METRICA_CHOICES,
        'operadores': ReglaIntervencion.OPERADOR_CHOICES,
        'plantillas': PlantillaCorreo.objects.filter(activa=True),
        'roles_destino': ['DECANO', 'SECRETARIA_ACADEMICA', 'COORDINADOR', 'BIENESTAR_ACADEMICO', 'MENTORIAS', 'ADMINISTRADOR'],
    })


@decano_required
def regla_editar(request, id_regla):
    regla = get_object_or_404(ReglaIntervencion, id_regla=id_regla)
    if request.method == 'POST':
        try:
            _guardar_regla_desde_post(request, regla=regla)
            messages.success(request, 'Regla actualizada.')
            return redirect('reglas_lista')
        except Exception as exc:
            messages.error(request, f'No se pudo actualizar la regla: {str(exc)[:200]}')
    return render(request, 'dashboard/regla_form.html', {
        'regla': regla,
        'metricas': ReglaIntervencion.METRICA_CHOICES,
        'operadores': ReglaIntervencion.OPERADOR_CHOICES,
        'plantillas': PlantillaCorreo.objects.filter(activa=True),
        'roles_destino': ['DECANO', 'SECRETARIA_ACADEMICA', 'COORDINADOR', 'BIENESTAR_ACADEMICO', 'MENTORIAS', 'ADMINISTRADOR'],
    })


@decano_required
def regla_activar_toggle(request, id_regla):
    regla = get_object_or_404(ReglaIntervencion, id_regla=id_regla)
    if request.method == 'POST':
        regla.activa = not regla.activa
        regla.save(update_fields=['activa', 'updated_at'])
        messages.success(request, f'Regla {"activada" if regla.activa else "desactivada"}.')
    return redirect('reglas_lista')


@decano_required
def regla_disparar_ahora(request, id_regla):
    """Entregable 2.B -- disparo manual, fuera del ciclo automatico de
    Celery Beat. Llama a la MISMA funcion de evaluacion que usa la tarea
    periodica y los signals (evaluar_reglas_intervencion_sync), nunca se
    duplica la logica de calculo."""
    regla = get_object_or_404(ReglaIntervencion, id_regla=id_regla)
    if request.method != 'POST':
        return redirect('reglas_lista')
    from apps.decano.tasks import evaluar_reglas_intervencion_sync
    try:
        creados = evaluar_reglas_intervencion_sync(solo_regla_id=regla.id_regla)
        if creados:
            messages.success(request, f'Regla evaluada: {len(creados)} intervención(es) encolada(s)/enviada(s).')
        else:
            messages.info(request, 'La regla se evaluó pero ningún caso cumplió la condición (o está en cooldown).')
    except Exception as exc:
        messages.error(request, f'Error evaluando la regla: {str(exc)[:200]}')
    return redirect('reglas_lista')


@decano_required
def plantillas_lista(request):
    plantillas = PlantillaCorreo.objects.order_by('codigo')
    return render(request, 'dashboard/plantillas_lista.html', {'plantillas': plantillas})


@decano_required
def plantilla_crear(request):
    if request.method == 'POST':
        try:
            PlantillaCorreo.objects.create(
                codigo=request.POST.get('codigo', '').strip(),
                asunto=request.POST.get('asunto', '').strip(),
                cuerpo_html=request.POST.get('cuerpo_html', ''),
                variables_disponibles=[v.strip() for v in request.POST.get('variables_disponibles', '').split(',') if v.strip()],
                activa=bool(request.POST.get('activa')),
            )
            messages.success(request, 'Plantilla de correo creada.')
            return redirect('plantillas_lista')
        except Exception as exc:
            messages.error(request, f'No se pudo crear la plantilla: {str(exc)[:200]}')
    return render(request, 'dashboard/plantilla_form.html', {'plantilla': None})


@decano_required
def plantilla_editar(request, id_plantilla):
    plantilla = get_object_or_404(PlantillaCorreo, id_plantilla=id_plantilla)
    if request.method == 'POST':
        try:
            plantilla.asunto = request.POST.get('asunto', '').strip()
            plantilla.cuerpo_html = request.POST.get('cuerpo_html', '')
            plantilla.variables_disponibles = [v.strip() for v in request.POST.get('variables_disponibles', '').split(',') if v.strip()]
            plantilla.activa = bool(request.POST.get('activa'))
            plantilla.save()
            messages.success(request, 'Plantilla actualizada.')
            return redirect('plantillas_lista')
        except Exception as exc:
            messages.error(request, f'No se pudo actualizar la plantilla: {str(exc)[:200]}')
    return render(request, 'dashboard/plantilla_form.html', {'plantilla': plantilla})


@decano_required
def logs_intervencion(request):
    estado_filtro = request.GET.get('estado', '')
    logs = LogIntervencion.objects.select_related('regla').order_by('-fecha_disparo')
    if estado_filtro:
        logs = logs.filter(estado=estado_filtro)
    return render(request, 'dashboard/logs_intervencion.html', {
        'logs': logs[:300],
        'estado_filtro': estado_filtro,
        'estados': LogIntervencion.ESTADO_CHOICES,
    })


@decano_required
def log_intervencion_reintentar(request, id_log):
    log = get_object_or_404(LogIntervencion, id_log=id_log)
    if request.method != 'POST':
        return redirect('logs_intervencion')
    if log.estado != 'FALLIDO':
        messages.error(request, 'Solo se puede reintentar un envío en estado Fallido.')
        return redirect('logs_intervencion')
    from apps.decano.tasks import reintentar_log_intervencion
    try:
        reintentar_log_intervencion(log)
        messages.success(request, 'Reenvío realizado.')
    except Exception as exc:
        messages.error(request, f'Falló el reenvío: {str(exc)[:200]}')
    return redirect('logs_intervencion')


# ════════════════════════════════════════════════════════════════
#  E. LOS 7 REPORTES DEL DECANO (Entregable 3)
#     Todos exportan a PDF/Excel con membrete institucional via los
#     helpers genericos de frontend_views.py (?export=pdf|excel).
# ════════════════════════════════════════════════════════════════

def _responder_reporte(request, slug, titulo, columnas, filas, subtitulo=None):
    formato = request.GET.get('export')
    if formato == 'pdf':
        pdf_bytes = fv._construir_pdf_generico_politecnico(titulo, columnas, filas, subtitulo=subtitulo)
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="{slug}.pdf"'
        return resp
    if formato == 'excel':
        xlsx_bytes = fv._construir_excel_generico_politecnico(titulo, columnas, filas)
        resp = HttpResponse(xlsx_bytes, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="{slug}.xlsx"'
        return resp
    return render(request, 'dashboard/decano_reporte.html', {
        'titulo': titulo, 'subtitulo': subtitulo, 'slug': slug,
        'columnas': columnas, 'filas': filas,
    })


@operacion_required
def reporte_ocupacion_salones(request):
    sede_id = request.GET.get('sede')
    periodo_id = request.GET.get('periodo')

    qs = Horario.objects.filter(estado__in=['APROBADO', 'PUBLICADO'])
    if sede_id:
        qs = qs.filter(salon__sede_id=sede_id)
    if periodo_id:
        qs = qs.filter(matricula__periodo_id=periodo_id)
    reales = qs.values('salon').annotate(horas_reales=Count('id_horario')).order_by('-horas_reales')

    # "Horas planeadas": snapshot que el Decano haya guardado en una
    # MatrizPlaneacion.parametros_simulacion para el mismo periodo (ver
    # matriz_planeacion_vincular_ia) -- si no hay matriz o el salon no
    # aparece en el snapshot se muestra "—", nunca un numero inventado.
    horas_planeadas_por_salon = {}
    matrices_qs = MatrizPlaneacion.objects.all()
    if periodo_id:
        matrices_qs = matrices_qs.filter(periodo_id=periodo_id)
    for matriz in matrices_qs.order_by('-created_at')[:20]:
        snap = matriz.parametros_simulacion or {}
        for entrada in snap.get('horas_planeadas_por_salon', []):
            try:
                horas_planeadas_por_salon.setdefault(int(entrada['salon_id']), entrada['horas'])
            except (KeyError, TypeError, ValueError):
                continue

    filas = []
    for fila in reales:
        salon = Salon.objects.filter(id_salon=fila['salon']).select_related('sede').first()
        if not salon:
            continue
        planeadas = horas_planeadas_por_salon.get(salon.id_salon, '—')
        filas.append((salon.codigo, salon.sede.nombre if salon.sede_id else '—', salon.capacidad, fila['horas_reales'], planeadas))

    return _responder_reporte(request, 'ocupacion_salones', 'Ocupación real vs. planeada de salones',
                               ['Salón', 'Sede', 'Capacidad', 'Horas reales', 'Horas planeadas'], filas)


@staff_required
def reporte_heatmap_inasistencias(request):
    sede_id = request.GET.get('sede')
    ciclo = request.GET.get('ciclo')
    materia_id = request.GET.get('materia')
    periodo_id = request.GET.get('periodo')

    qs = AsistenciaEstudiante.objects.select_related(
        'horario__salon__sede', 'horario__bloque', 'matricula__materia', 'matricula__periodo')
    if sede_id:
        qs = qs.filter(horario__salon__sede_id=sede_id)
    if ciclo:
        qs = qs.filter(matricula__materia__ciclo=ciclo)
    if materia_id:
        qs = qs.filter(matricula__materia_id=materia_id)
    if periodo_id:
        qs = qs.filter(matricula__periodo_id=periodo_id)

    celdas = {}
    for a in qs[:20000]:
        sede_nombre = a.horario.salon.sede.nombre if (a.horario_id and a.horario.salon_id and a.horario.salon.sede_id) else '—'
        jornada = resolver_jornada(a.horario.bloque) if a.horario_id else None
        clave = (
            sede_nombre,
            a.matricula.materia.ciclo if a.matricula_id and a.matricula.materia_id else '—',
            jornada.nombre if jornada else 'Sin jornada',
            a.matricula.materia.nombre if a.matricula_id and a.matricula.materia_id else '—',
        )
        acc = celdas.setdefault(clave, [0, 0])
        acc[0] += 1
        if a.estado == 'AUSENTE':
            acc[1] += 1

    filas = []
    for (sede_nombre, ciclo_v, jornada_nombre, materia_nombre), (total, ausentes) in sorted(celdas.items()):
        pct = round(ausentes / total * 100, 1) if total else 0
        filas.append((sede_nombre, ciclo_v, jornada_nombre, materia_nombre, total, ausentes, f'{pct}%'))

    return _responder_reporte(request, 'heatmap_inasistencias', 'Heatmap de inasistencias',
                               ['Sede', 'Ciclo', 'Jornada', 'Materia', 'Total registros', 'Ausentes', '% inasistencia'], filas)


@staff_required
def reporte_roi_eventos(request):
    tipo = request.GET.get('tipo')
    facultad_id = request.GET.get('facultad')
    periodo_id = request.GET.get('periodo')

    qs = Evento.objects.annotate(
        inscritos=Count('inscripciones', filter=Q(inscripciones__estado='INSCRITO'), distinct=True),
        asistentes=Count('inscripciones', filter=Q(inscripciones__estado='INSCRITO', inscripciones__asistencias__direccion='IN'), distinct=True),
    )
    if tipo:
        qs = qs.filter(tipo=tipo)
    if facultad_id:
        qs = qs.filter(facultad_id=facultad_id)
    if periodo_id:
        periodo = Periodo.objects.filter(id_periodo=periodo_id).first()
        if periodo:
            qs = qs.filter(fecha_inicio__date__gte=periodo.fecha_inicio, fecha_inicio__date__lte=periodo.fecha_fin)

    filas = []
    for evento in qs.order_by('-fecha_inicio')[:1000]:
        pct = round(evento.asistentes / evento.inscritos * 100, 1) if evento.inscritos else 0
        filas.append((evento.nombre, evento.get_tipo_display(), evento.fecha_inicio.strftime('%d/%m/%Y'),
                       evento.inscritos, evento.asistentes, f'{pct}%'))

    return _responder_reporte(request, 'roi_eventos', 'ROI académico de eventos',
                               ['Evento', 'Tipo', 'Fecha', 'Inscritos', 'Asistentes (IN)', '% asistencia'], filas)


@staff_required
def reporte_riesgo_desercion(request):
    nivel = request.GET.get('nivel')
    estado = request.GET.get('estado')
    programa_id = request.GET.get('programa')

    qs = AlertaRiesgo.objects.select_related('estudiante__usuario', 'estudiante__programa')
    if nivel:
        qs = qs.filter(nivel=nivel)
    if estado:
        qs = qs.filter(estado=estado)
    if programa_id:
        qs = qs.filter(estudiante__programa_id=programa_id)

    filas = []
    for alerta in qs.order_by('-fecha_deteccion')[:2000]:
        estudiante = alerta.estudiante
        caso = CasoBienestar.objects.filter(estudiante=estudiante).order_by('-created_at').first()
        mentoria = AsignacionMentoria.objects.filter(estudiante=estudiante, estado='ACTIVA').select_related('mentor').first()
        filas.append((
            estudiante.usuario.nombre_completo if estudiante.usuario_id else estudiante.codigo,
            estudiante.programa.nombre if estudiante.programa_id else '—',
            alerta.get_nivel_display(), f'{alerta.pct_inasistencia_calculado}%', alerta.get_estado_display(),
            caso.get_estado_display() if caso else 'Sin caso',
            mentoria.mentor.nombre_completo if mentoria else 'Sin mentor asignado',
        ))

    return _responder_reporte(request, 'riesgo_desercion', 'Riesgo de deserción estudiantil',
                               ['Estudiante', 'Programa', 'Nivel', '% inasistencia', 'Estado alerta', 'Caso Bienestar', 'Mentor'], filas)


@operacion_required
def reporte_cumplimiento_docente(request):
    facultad_id = request.GET.get('facultad')
    sede_id = request.GET.get('sede')
    periodo_id = request.GET.get('periodo')

    qs = AsistenciaDocente.objects.filter(validado_para_nomina=True)
    if sede_id:
        qs = qs.filter(horario__salon__sede_id=sede_id)
    if facultad_id:
        qs = qs.filter(horario__materia__programa__facultad_id=facultad_id)
    if periodo_id:
        qs = qs.filter(horario__matricula__periodo_id=periodo_id)

    agregado = qs.values('docente').annotate(horas_dictadas=Count('id_asistencia')).order_by('-horas_dictadas')
    filas = []
    for fila in agregado:
        docente = Docente.objects.filter(usuario_id=fila['docente']).select_related('usuario').first()
        if not docente:
            continue
        max_h = docente.carga_horaria_max
        pct_cumpl = round(fila['horas_dictadas'] / max_h * 100, 1) if max_h else None
        filas.append((docente.usuario.nombre_completo, docente.get_tipo_contrato_display(), max_h or '—',
                       fila['horas_dictadas'], f'{pct_cumpl}%' if pct_cumpl is not None else '—'))

    return _responder_reporte(request, 'cumplimiento_docente', 'Cumplimiento contractual docente',
                               ['Docente', 'Tipo contrato', 'Carga máx.', 'Horas dictadas (nómina)', '% cumplimiento'], filas)


@operacion_required
def reporte_conflictos_horario(request):
    sede_id = request.GET.get('sede')
    solo_pendientes = request.GET.get('estado', 'pendientes') != 'todos'

    solicitudes_qs = SolicitudReprogramacion.objects.select_related('horario__salon__sede', 'horario__materia')
    if solo_pendientes:
        solicitudes_qs = solicitudes_qs.filter(estado='PENDIENTE')
    if sede_id:
        solicitudes_qs = solicitudes_qs.filter(horario__salon__sede_id=sede_id)

    filas = []
    for s in solicitudes_qs.order_by('-created_at')[:500]:
        filas.append((
            'Solicitud de reprogramación',
            s.horario.materia.nombre if s.horario_id and s.horario.materia_id else '—',
            s.horario.salon.sede.nombre if s.horario_id and s.horario.salon_id and s.horario.salon.sede_id else '—',
            s.get_estado_display(), (s.motivo or '')[:80],
        ))

    ultima_ia = AsignacionIA.objects.order_by('-fecha_inicio').first()
    if ultima_ia and ultima_ia.conflictos_residuales:
        filas.append(('Motor IA (última corrida)', f'Job {ultima_ia.job_id}', '—',
                       f'{ultima_ia.conflictos_residuales} conflicto(s) residual(es)', ''))

    reservas = ReservaRecurso.objects.filter(estado__in=['SOLICITADA', 'CONFIRMADA']).select_related('salon__sede', 'evento').order_by('salon_id', 'fecha_inicio')
    if sede_id:
        reservas = reservas.filter(salon__sede_id=sede_id)
    anterior = None
    for r in reservas:
        if anterior and anterior.salon_id == r.salon_id and anterior.fecha_fin > r.fecha_inicio:
            filas.append((
                'Choque de reserva (Eventos)', f'{anterior.evento.nombre} vs {r.evento.nombre}',
                r.salon.sede.nombre if r.salon.sede_id else '—',
                f'{r.salon.codigo}: {anterior.fecha_inicio:%d/%m %H:%M}-{anterior.fecha_fin:%H:%M} solapa con {r.fecha_inicio:%d/%m %H:%M}',
                '',
            ))
        anterior = r

    return _responder_reporte(request, 'conflictos_horario', 'Conflictos de horario activos',
                               ['Origen', 'Detalle', 'Sede', 'Estado / descripción', 'Notas'], filas)


@operacion_required
def reporte_utilizacion_infraestructura(request):
    sede_id = request.GET.get('sede')
    tipo = request.GET.get('tipo')
    periodo_id = request.GET.get('periodo')

    qs = Salon.objects.filter(activo=True).select_related('sede')
    if sede_id:
        qs = qs.filter(sede_id=sede_id)
    if tipo:
        qs = qs.filter(tipo=tipo)

    filas = []
    for salon in qs.order_by('sede__nombre', 'codigo'):
        horarios_qs = salon.horario_set.filter(estado__in=['APROBADO', 'PUBLICADO'])
        if periodo_id:
            horarios_qs = horarios_qs.filter(matricula__periodo_id=periodo_id)
        horas_horarios = horarios_qs.count()

        horas_eventos = 0.0
        for r in salon.reservas_eventos.filter(estado='CONFIRMADA'):
            horas_eventos += (r.fecha_fin - r.fecha_inicio).total_seconds() / 3600

        horas_disponibles_semana = 14 * 6  # 14 bloques/dia x 6 dias (Lu-Sa) -- techo teorico semanal
        pct_uso = round((horas_horarios / horas_disponibles_semana) * 100, 1) if horas_disponibles_semana else 0

        filas.append((salon.codigo, salon.sede.nombre if salon.sede_id else '—', salon.get_tipo_display(),
                       salon.capacidad, horas_horarios, round(horas_eventos, 1), f'{pct_uso}%'))

    return _responder_reporte(request, 'utilizacion_infraestructura', 'Utilización de infraestructura por sede',
                               ['Salón', 'Sede', 'Tipo', 'Capacidad', 'Horas-bloque horarios', 'Horas eventos', '% uso semanal (horarios)'], filas)


# ════════════════════════════════════════════════════════════════
#  F. CATALOGO DE JORNADAS (Mañana/Tarde/Noche/Especial)
#     Añadido 2026-09-06 -- Jornada nace vacía y no hay UI dedicada para
#     poblarla; se agrega aquí en vez de mandar al Decano al Django Admin
#     (que exige is_staff=True, no garantizado para cuentas ADMINISTRADOR
#     creadas via create_user en vez de create_superuser).
# ════════════════════════════════════════════════════════════════

@decano_required
def jornadas_lista(request):
    if request.method == 'POST':
        try:
            Jornada.objects.create(
                nombre=request.POST.get('nombre', '').strip(),
                hora_inicio_tipica=request.POST.get('hora_inicio_tipica') or None,
                hora_fin_tipica=request.POST.get('hora_fin_tipica') or None,
                orden=int(request.POST.get('orden') or 0),
                activa=bool(request.POST.get('activa')),
            )
            messages.success(request, 'Jornada creada.')
            return redirect('jornadas_lista')
        except Exception as exc:
            messages.error(request, f'No se pudo crear la jornada: {str(exc)[:200]}')
    jornadas = Jornada.objects.order_by('orden', 'nombre')
    return render(request, 'dashboard/jornadas_lista.html', {'jornadas': jornadas})


@decano_required
def jornada_toggle(request, id_jornada):
    jornada = get_object_or_404(Jornada, id_jornada=id_jornada)
    if request.method == 'POST':
        jornada.activa = not jornada.activa
        jornada.save(update_fields=['activa'])
    return redirect('jornadas_lista')


@decano_required
def jornada_editar(request, id_jornada):
    jornada = get_object_or_404(Jornada, id_jornada=id_jornada)
    if request.method == 'POST':
        try:
            jornada.nombre = request.POST.get('nombre', '').strip()
            jornada.hora_inicio_tipica = request.POST.get('hora_inicio_tipica') or None
            jornada.hora_fin_tipica = request.POST.get('hora_fin_tipica') or None
            jornada.orden = int(request.POST.get('orden') or 0)
            jornada.activa = bool(request.POST.get('activa'))
            jornada.save()
            messages.success(request, 'Jornada actualizada.')
            return redirect('jornadas_lista')
        except Exception as exc:
            messages.error(request, f'No se pudo actualizar la jornada: {str(exc)[:200]}')
    return render(request, 'dashboard/jornada_form.html', {'jornada': jornada})
