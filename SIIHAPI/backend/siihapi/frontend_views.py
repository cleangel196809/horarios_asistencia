"""
SIIHAPI · Vistas del frontend (templates Django).

Estructura por bloques:
    1. Publicas (landing, login, logout)
    2. Dashboard raiz (despacha por rol)
    3. ADMIN/COORDINADOR (academico)
    4. ADMIN/COORDINADOR (operacion: Motor IA, Horarios, SISCA)
    5. ADMIN (reportes y auditoria)
    6. COORDINADOR (aprobacion de horarios)
    7. DOCENTE (mi horario, disponibilidad, mis materias, asistencia)
    8. ESTUDIANTE (mi horario, mis materias, asistencia, notas)
    9. ADMIN (base de datos: CRUD via Django Admin, backup/restore, gestion de usuarios)
"""
import json
import os
import re
import uuid
import random
import tempfile
import calendar
from datetime import date, datetime, timedelta

from django.apps import apps as django_apps
from django.conf import settings as djsettings
from django.contrib import messages
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.infraestructura.models import Sede, Salon
from apps.academico.models import Facultad, Programa, Materia
from apps.matriculas.models import Periodo, Estudiante, Matricula
from apps.matriculas.periodo_utils import get_periodo_seleccionado, set_periodo_seleccionado
from apps.horarios.models import Bloque, Horario, AsignacionIA, ReglaNegocio, SolicitudReprogramacion
from apps.asistencias.models import AsistenciaEstudiante, AsistenciaDocente, Justificacion, AlertaRiesgo
from apps.bienestar.models import CasoBienestar
from apps.eventos.models import Evento, ReservaRecurso, InscripcionEvento, AsistenciaEvento, Certificado
from apps.personal.models import Docente, DisponibilidadDocente
from apps.autenticacion.models import IntentoLogin, Usuario
from apps.integracion_sisca.models import IntegracionLog
from apps.integracion_sisca.cliente import get_cliente, ClienteSISCAError

from .permisos import (
    rol_requerido, admin_required, staff_required,
    docente_required, estudiante_required, es_staff,
    es_docente, es_estudiante, es_solo_consulta,
    gestion_periodos_required,
    operacion_required, bloquear_solo_consulta,
)


# ════════════════════════════════════════════════════════════════
#  1. PUBLICAS
# ════════════════════════════════════════════════════════════════

def landing(request):
    # Fase 2 (2026-09-03): datos reales de integracion_pi, sin numeros de
    # relleno. Antes se usaba "or 87" / "or '8.430'" como demo si la BD
    # (Oracle) estaba vacia; ahora la BD compartida siempre tiene datos
    # reales, asi que se muestran tal cual (incluido 0 si aplica).
    stats = {
        'sedes':       Sede.objects.filter(estado='A').count(),
        'salones':     Salon.objects.filter(activo=True).count(),
        'programas':   Programa.objects.filter(activo=True).count(),
        'docentes':    Docente.objects.filter(activo=True).count(),
        'estudiantes': Estudiante.objects.filter(activo=True).count(),
    }
    sedes = Sede.objects.filter(estado='A').order_by('nombre')
    return render(request, 'landing.html', {
        'stats': stats,
        'sedes': sedes,
        'mision': 'Formar profesionales integrales, capaces de transformar la sociedad mediante la innovacion, el liderazgo y la excelencia academica.',
    })


def login_view(request):
    """RF-01 (Fase 3, 2026-09-04): el ingreso se decide SOLO por correo +
    contrasena -- ya no se pide elegir un boton de rol ni se valida que
    coincida con uno. El rol real vive en user.rol (columna 'rol' de la
    BD) y dashboard() despacha automaticamente al panel correcto segun
    user.rol_efectivo (ver Usuario.ROL_EQUIVALENCIAS): administrador como
    administrador, decano/secretaria academica/coordinador como
    coordinador, docente como docente, estudiante como estudiante, y
    bienestar academico/mentorias tambien como coordinador pero de solo
    consulta (ver permisos.ROLES_SOLO_CONSULTA)."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        correo = request.POST.get('correo', '').strip().lower()
        contrasena = request.POST.get('contrasena', '')
        ip = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]

        user = authenticate(request, username=correo, password=contrasena)

        if user is None:
            IntentoLogin.objects.create(correo=correo, exitoso=False, ip=ip, user_agent=user_agent)
            messages.error(request, 'Credenciales invalidas')
            return render(request, 'auth/login.html')

        if user.esta_bloqueado():
            messages.error(request, 'Tu cuenta esta temporalmente bloqueada por intentos fallidos')
            return render(request, 'auth/login.html')

        django_login(request, user)
        user.resetear_intentos()
        ahora = timezone.now()
        user.ultimo_login = ahora
        user.ultima_actividad = ahora  # IMPORTANTE: resetear para que el middleware no cierre sesion
        user.save(update_fields=['ultimo_login', 'ultima_actividad'])

        IntentoLogin.objects.create(correo=correo, exitoso=True, ip=ip, user_agent=user_agent)
        messages.success(request, f'Bienvenido {user.nombre_completo}')
        return redirect('dashboard')

    return render(request, 'auth/login.html')


def logout_view(request):
    django_logout(request)
    messages.info(request, 'Sesion cerrada correctamente')
    return redirect('landing')


# Fase 2 (2026-09-03): estandar de codigo para ciclos de formacion
# (periodos academicos): AÑO-CICLOT, ej. "2026-4T" (4 ciclos/trimestres
# por año). Solo aplica a los ciclos creados desde esta vista; los
# codigos historicos (ej. "2026-2") no se tocan.
PERIODO_CODIGO_RE = re.compile(r'^(?P<anio>\d{4})-(?P<ciclo>[1-4])T$')


def _ciclo_sort_key(c):
    """Ordena ciclos de formacion (Materia.ciclo: '1'..'12', semestre) de
    forma CRONOLOGICA (1,2,3,...,12) en vez de alfabetica (2026-09-06, a
    pedido del usuario -- el campo es CharField porque a veces trae datos
    legacy no numericos, asi que un sort/order_by de texto normal deja
    '10','11','12' antes que '2'..'9'). Los valores numericos van primero
    en su orden real; cualquier valor no numerico legacy queda al final,
    ordenado alfabeticamente entre si para no romper con datos viejos."""
    s = str(c).strip()
    if s.isdigit():
        return (0, int(s), '')
    return (1, 0, s)


@gestion_periodos_required
@require_http_methods(['POST'])
def crear_periodo(request):
    """Crea un nuevo ciclo de formacion (Periodo) y lo marca como el actual.

    Solo Admin, Decano y Secretaria Academica pueden llegar aqui (ver
    permisos.gestion_periodos_required). Los demas roles solo ven los
    ciclos ya creados en el selector del topbar (context_processors.py).
    """
    destino = request.META.get('HTTP_REFERER') or reverse('dashboard')

    codigo = request.POST.get('codigo', '').strip().upper()
    nombre = request.POST.get('nombre', '').strip()
    fecha_inicio = request.POST.get('fecha_inicio', '').strip()
    fecha_fin = request.POST.get('fecha_fin', '').strip()

    m = PERIODO_CODIGO_RE.match(codigo)
    if not m:
        messages.error(request, 'El código del ciclo debe tener el formato AÑO-CICLOT, por ejemplo 2026-4T.')
        return redirect(destino)

    if not fecha_inicio or not fecha_fin:
        messages.error(request, 'Debes indicar la fecha de inicio y de fin del ciclo.')
        return redirect(destino)

    if Periodo.objects.filter(codigo=codigo).exists():
        messages.error(request, f'Ya existe un ciclo con el código {codigo}.')
        return redirect(destino)

    if not nombre:
        nombre = f"Trimestre {m.group('ciclo')} de {m.group('anio')}"

    # El nuevo ciclo pasa a ser "el actual" en todo el sistema (dashboard,
    # selector del topbar, etc. ya filtran por activo=True).
    Periodo.objects.update(activo=False)
    nuevo = Periodo.objects.create(
        codigo=codigo,
        nombre=nombre,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        activo=True,
    )
    # Quien lo crea pasa a "ver" ese ciclo de inmediato (ver seleccionar_periodo).
    set_periodo_seleccionado(request, nuevo)
    messages.success(request, f'Ciclo de formación {codigo} creado y marcado como actual.')
    return redirect(destino)


@login_required
@require_http_methods(['POST'])
def seleccionar_periodo(request):
    """Guarda en la sesion del usuario el ciclo elegido en el selector del
    topbar (base.html). A partir de ahi, get_periodo_seleccionado(request)
    hace que TODAS las vistas que antes usaban Periodo.objects.filter(
    activo=True).first() consulten con este ciclo en su lugar -- sin esto,
    el selector solo era decorativo."""
    destino = request.META.get('HTTP_REFERER') or reverse('dashboard')
    periodo_id = request.POST.get('periodo_id', '').strip()
    if not periodo_id:
        set_periodo_seleccionado(request, None)
        return redirect(destino)
    try:
        periodo = Periodo.objects.get(id_periodo=periodo_id)
    except (Periodo.DoesNotExist, ValueError):
        messages.error(request, 'Ese ciclo de formación ya no existe.')
        return redirect(destino)
    set_periodo_seleccionado(request, periodo)
    messages.success(request, f'Ahora estás viendo el ciclo {periodo.codigo}.')
    return redirect(destino)


# ════════════════════════════════════════════════════════════════
#  2. DASHBOARD RAIZ - despacha por rol
# ════════════════════════════════════════════════════════════════

@login_required
def dashboard(request):
    rol = request.user.rol_efectivo
    template_map = {
        'ADMINISTRADOR': 'dashboard/admin.html',
        'COORDINADOR':   'dashboard/coordinador.html',
        'DOCENTE':       'dashboard/docente.html',
        'ESTUDIANTE':    'dashboard/estudiante.html',
    }
    template = template_map.get(rol, 'dashboard/admin.html')

    periodo_actual = get_periodo_seleccionado(request)
    periodo_cod = periodo_actual.codigo if periodo_actual else '2026-2'

    if rol in ('ADMINISTRADOR', 'COORDINADOR'):
        ultima_ia = AsignacionIA.objects.order_by('-fecha_inicio').first()
        ultimo_log_sisca = IntegracionLog.objects.order_by('-fecha').first()
        context = {
            'kpis': {
                'sedes':       Sede.objects.filter(estado='A').count(),
                'salones':     Salon.objects.filter(activo=True).count(),
                'programas':   Programa.objects.filter(activo=True).count(),
                'periodo':     periodo_cod,
                'docentes':    Docente.objects.filter(activo=True).count(),
                'estudiantes': Estudiante.objects.filter(activo=True).count(),
                'horarios':    Horario.objects.count(),
                'publicados':  Horario.objects.filter(estado='PUBLICADO').count(),
                'aprobados':   Horario.objects.filter(estado='APROBADO').count(),
                'propuestos':  Horario.objects.filter(estado='PROPUESTO').count(),
            },
            'ultima_ia': ultima_ia,
            'ultimo_log_sisca': ultimo_log_sisca,
            # Sprint 2 (2026-09-06): Bienestar/Mentoría caen en esta rama
            # porque su rol_efectivo también mapea a 'COORDINADOR' -- se
            # distingue por el rol CRUDO para mostrarles su propio enlace
            # de sidebar (bienestar_dashboard) sin tocar ROL_EQUIVALENCIAS.
            'es_bienestar_o_mentoria': request.user.rol in ('BIENESTAR_ACADEMICO', 'MENTORIAS'),
        }
    elif rol == 'DOCENTE':
        doc = Docente.objects.filter(usuario=request.user).first()
        horarios = Horario.objects.none()
        n_materias = 0
        if doc:
            horarios = Horario.objects.filter(docente=doc).select_related('materia', 'salon', 'bloque')
            n_materias = horarios.values('materia').distinct().count()
        context = {
            'docente': doc,
            'kpis': {
                'periodo':       periodo_cod,
                'mis_horarios':  horarios.count(),
                'mis_materias':  n_materias,
                'restricciones': DisponibilidadDocente.objects.filter(docente=doc).count() if doc else 0,
            },
            'proximos': horarios[:6],
        }
    elif rol == 'ESTUDIANTE':
        est = Estudiante.objects.filter(usuario=request.user).first()
        matriculas = Matricula.objects.none()
        horarios = Horario.objects.none()
        if est:
            matriculas = Matricula.objects.filter(estudiante=est, estado='ACTIVA').select_related('materia')
            horarios = Horario.objects.filter(matricula__estudiante=est).select_related('materia', 'docente__usuario', 'salon', 'bloque')
        context = {
            'estudiante': est,
            'kpis': {
                'periodo':         periodo_cod,
                'mis_materias':    matriculas.count(),
                'mis_horarios':    horarios.count(),
                'semestre':        est.semestre_actual if est else '—',
                'programa':        est.programa.nombre if est else '—',
            },
            'proximos': horarios[:6],
        }
    else:
        context = {'kpis': {'periodo': periodo_cod}}

    return render(request, template, context)


# ════════════════════════════════════════════════════════════════
#  3. ADMIN/COORDINADOR - Academico
# ════════════════════════════════════════════════════════════════

@staff_required
def sedes_view(request):
    sedes = Sede.objects.filter(estado='A').annotate(num_salones=Count('salones'))
    sede_filtro = request.GET.get('sede', '')
    tipo_filtro = request.GET.get('tipo', '')

    salones = Salon.objects.filter(activo=True).select_related('sede')
    if sede_filtro:
        salones = salones.filter(sede__codigo=sede_filtro)
    if tipo_filtro:
        salones = salones.filter(tipo=tipo_filtro)
    salones = salones.order_by('sede__nombre', 'planta', 'codigo')[:300]

    return render(request, 'dashboard/sedes.html', {
        'sedes': sedes,
        'salones': salones,
        'tipos': Salon.TIPO_CHOICES,
        'sede_filtro': sede_filtro,
        'tipo_filtro': tipo_filtro,
        'total_salones': Salon.objects.filter(activo=True).count(),
    })


@staff_required
def programas_view(request):
    tipo_filtro = request.GET.get('tipo', '')
    facultades = Facultad.objects.all().annotate(num_programas=Count('programas'))
    programas_activos = Programa.objects.filter(activo=True)
    programas = programas_activos.select_related('facultad')
    if tipo_filtro:
        programas = programas.filter(tipo=tipo_filtro)
    stats_tipo = {}
    for t, label in Programa.TIPO_CHOICES:
        stats_tipo[t] = {
            'label': label,
            'count': programas_activos.filter(tipo=t).count(),
        }
    return render(request, 'dashboard/programas.html', {
        'facultades': facultades,
        'programas': programas,
        'stats_tipo': stats_tipo,
        'tipos': Programa.TIPO_CHOICES,
        'tipo_filtro': tipo_filtro,
        # Fase 3 (2026-09-04): antes era texto fijo "27 programas... 4
        # tipos y 6 facultades"; ahora sale de la BD real.
        'total_programas': programas_activos.count(),
        'total_facultades': facultades.filter(num_programas__gt=0).count(),
    })


@staff_required
def programa_ciclos_view(request, id_programa):
    """Fase 3 (2026-09-04): primer nivel del despliegue de 'Programas y
    Materias' -- al hacer click en una carrera se listan los ciclos de
    formacion (Periodo) en los que ese programa ha tenido matriculas."""
    programa = get_object_or_404(Programa, id_programa=id_programa)

    periodos = (
        Periodo.objects
        .filter(matricula__materia__programa=programa)
        .annotate(
            n_materias=Count('matricula__materia', distinct=True),
            n_matriculas=Count('matricula', distinct=True),
            n_estudiantes=Count('matricula__estudiante', distinct=True),
        )
        .distinct()
        .order_by('-fecha_inicio')
    )

    return render(request, 'dashboard/programa_ciclos.html', {
        'programa': programa,
        'periodos': periodos,
    })


@staff_required
def programa_ciclo_materias_view(request, id_programa, id_periodo):
    """Segundo nivel: al hacer click en un ciclo de formacion se listan las
    materias de ese programa que tuvieron matriculas en ese periodo, con un
    resumen de sus horarios asignados (dia, bloque, docente, salon)."""
    programa = get_object_or_404(Programa, id_programa=id_programa)
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)

    materias = (
        Materia.objects
        .filter(programa=programa, matricula__periodo=periodo)
        .annotate(n_estudiantes=Count('matricula', distinct=True,
                                       filter=Q(matricula__periodo=periodo)))
        .distinct()
        .order_by('nombre')
    )

    horarios_por_materia = {}
    horarios_qs = (
        Horario.objects
        .filter(matricula__periodo=periodo, materia__programa=programa)
        .select_related('docente__usuario', 'salon', 'bloque', 'materia')
        .values('materia_id', 'dia', 'bloque__numero', 'bloque__hora_inicio', 'bloque__hora_fin',
                'docente__usuario__nombre', 'docente__usuario__apellido', 'salon__codigo', 'estado')
        .distinct()
        .order_by('materia_id', 'dia', 'bloque__numero')
    )
    dias_map = dict(Horario.DIA_CHOICES)
    for h in horarios_qs:
        h['dia_label'] = dias_map.get(h['dia'], h['dia'])
        horarios_por_materia.setdefault(h['materia_id'], []).append(h)

    materias_con_horario = []
    for m in materias:
        materias_con_horario.append({
            'materia': m,
            'n_estudiantes': m.n_estudiantes,
            'horarios': horarios_por_materia.get(m.id_materia, []),
        })
    # Orden cronologico por ciclo (1,2,...,12), no alfabetico -- ciclo es
    # CharField y .order_by('ciclo') a nivel de BD ordena como texto
    # (2026-09-06, a pedido del usuario, ver _ciclo_sort_key).
    materias_con_horario.sort(
        key=lambda x: (_ciclo_sort_key(x['materia'].ciclo), x['materia'].nombre or '')
    )

    return render(request, 'dashboard/programa_ciclo_materias.html', {
        'programa': programa,
        'periodo': periodo,
        'materias_con_horario': materias_con_horario,
    })


@staff_required
def materia_periodo_estudiantes_view(request, id_programa, id_periodo, id_materia):
    """Tercer nivel: al hacer click en una materia (dentro de un ciclo) se
    listan los estudiantes matriculados en ella para ese periodo, junto con
    su estado de matricula, nota (si existe) y su horario asignado."""
    programa = get_object_or_404(Programa, id_programa=id_programa)
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    materia = get_object_or_404(Materia, id_materia=id_materia, programa=programa)

    matriculas = (
        Matricula.objects
        .filter(materia=materia, periodo=periodo)
        .select_related('estudiante__usuario')
        .prefetch_related('horarios__docente__usuario', 'horarios__salon', 'horarios__bloque')
        .order_by('estudiante__usuario__apellido', 'estudiante__usuario__nombre')
    )

    return render(request, 'dashboard/materia_periodo_estudiantes.html', {
        'programa': programa,
        'periodo': periodo,
        'materia': materia,
        'matriculas': matriculas,
        'total_estudiantes': matriculas.count(),
    })


@staff_required
def docentes_view(request):
    """Fase 3 (2026-09-04): antes mostraba un "DOC-{id_docente}" que ya no
    existe (Docente usa usuario_id como PK desde la Fase 2) -- ahora la
    columna ID muestra la cedula real del docente. Se agrega busqueda por
    cedula/nombre/apellido (parametro GET 'q'); el autocompletado en vivo
    lo sirve docentes_autocomplete()."""
    q = request.GET.get('q', '').strip()
    docentes_qs = Docente.objects.filter(activo=True).select_related('usuario', 'facultad')
    if q:
        docentes_qs = docentes_qs.filter(
            Q(usuario__cedula__icontains=q) |
            Q(usuario__nombre__icontains=q) |
            Q(usuario__apellido__icontains=q)
        )
    total_general = Docente.objects.filter(activo=True).count()
    return render(request, 'dashboard/docentes.html', {
        'docentes': docentes_qs.order_by('usuario__apellido', 'usuario__nombre')[:200],
        'total': total_general,
        'total_filtrado': docentes_qs.count() if q else total_general,
        'q': q,
    })


@staff_required
def docentes_autocomplete(request):
    """Fase 3 (2026-09-04): sugerencias en vivo para el buscador de
    Docentes (por cedula, nombre o apellido). Devuelve como maximo 8
    coincidencias entre docentes activos."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'resultados': []})
    docentes_qs = Docente.objects.filter(activo=True).select_related('usuario').filter(
        Q(usuario__cedula__icontains=q) |
        Q(usuario__nombre__icontains=q) |
        Q(usuario__apellido__icontains=q)
    ).order_by('usuario__apellido', 'usuario__nombre')[:8]
    resultados = [{
        'cedula': d.usuario.cedula or '',
        'nombre': d.usuario.nombre,
        'apellido': d.usuario.apellido,
        'correo': d.usuario.correo,
    } for d in docentes_qs]
    return JsonResponse({'resultados': resultados})


@staff_required
def estudiantes_view(request):
    programa_filtro = request.GET.get('programa', '')
    estudiantes = Estudiante.objects.filter(activo=True).select_related('usuario', 'programa')
    if programa_filtro:
        estudiantes = estudiantes.filter(programa__codigo=programa_filtro)
    estudiantes = estudiantes[:300]
    return render(request, 'dashboard/estudiantes.html', {
        'estudiantes': estudiantes,
        'programas': Programa.objects.filter(activo=True),
        'programa_filtro': programa_filtro,
        'total': Estudiante.objects.filter(activo=True).count(),
    })


# ════════════════════════════════════════════════════════════════
#  4. ADMIN/COORDINADOR - Motor IA + Horarios + SISCA
# ════════════════════════════════════════════════════════════════

@operacion_required
def motor_ia_view(request):
    """Fase 3 (2026-09-04): el tile "Matrículas activas" del paso 1
    (Verificación de datos) ahora se calcula SOBRE EL PERIODO seleccionado
    en el topbar (get_periodo_seleccionado), no en toda la base de datos.
    Antes mostraba un conteo global que quedaba en verde/OK aunque el
    ciclo que realmente se iba a ejecutar (2026-3T, 2026-4T, ...) no
    tuviera ninguna matrícula ACTIVA -- lo que llevaba al motor a fallar
    con "No hay suficientes datos para el solver" sin que el paso 1 lo
    hubiera advertido. También se expone 'matriculas_inscritas': las que
    llegaron por importar_inscritos con ESTADO=INSCRITO (pre-registro sin
    confirmar) y que el motor NO usa todavía -- para que quede visible por
    qué el periodo puede verse "sin datos" aunque sí tenga inscripciones."""
    asignaciones = AsignacionIA.objects.order_by('-fecha_inicio')[:20]
    ultima = asignaciones.first() if asignaciones else None
    periodo_sel = get_periodo_seleccionado(request)

    if periodo_sel:
        matriculas_activas = Matricula.objects.filter(periodo=periodo_sel, estado='ACTIVA').count()
        matriculas_inscritas = Matricula.objects.filter(periodo=periodo_sel, estado='INSCRITA').count()
    else:
        matriculas_activas = 0
        matriculas_inscritas = 0

    return render(request, 'dashboard/motor_ia.html', {
        'asignaciones': asignaciones,
        'ultima': ultima,
        'periodo_verificacion': periodo_sel,
        'kpis': {
            'matriculas':           matriculas_activas,
            'matriculas_inscritas': matriculas_inscritas,
            'horarios':   Horario.objects.filter(matricula__periodo=periodo_sel).distinct().count() if periodo_sel else 0,
            'reglas':     ReglaNegocio.objects.filter(activa=True).count(),
            'salones':    Salon.objects.filter(activo=True).count(),
            'docentes':   Docente.objects.filter(activo=True).count(),
            'bloques':    Bloque.objects.count(),
        },
    })


@operacion_required
def motor_ia_grupos(request):
    """Fase 1 — Genera y muestra el plan de GRUPOS por asignatura (techo de
    estudiantes/capacidad, virtual 8-30, presencial por capacidad)."""
    from siihapi.motor_ia.grupos import plan_de_grupos
    periodo = request.GET.get('periodo') or ''
    try:
        plan = plan_de_grupos(periodo or None)
    except Exception as exc:
        import logging; logging.exception('plan grupos')
        messages.error(request, f'No se pudo generar el plan de grupos: {str(exc)[:200]}')
        plan = []
    tot_grupos = sum(p['num_grupos'] for p in plan)
    tot_est = sum(p['estudiantes'] for p in plan)
    return render(request, 'dashboard/grupos_plan.html', {
        'plan': plan, 'tot_grupos': tot_grupos, 'tot_est': tot_est,
        'tot_asignaturas': len(plan), 'periodo': periodo,
    })


@operacion_required
@require_http_methods(["POST"])
def motor_ia_analizar(request):
    """Recibe un archivo (CSV/XLSX/PDF/DOCX), lo analiza con el pipeline IA
    y devuelve la extracción + validación + confianza en JSON."""
    # Acepta 1 o varios archivos (campo "archivos" multiple, o "archivo" simple)
    archivos = request.FILES.getlist('archivos') or request.FILES.getlist('archivos[]')
    if not archivos:
        uno = request.FILES.get('archivo')
        archivos = [uno] if uno else []
    periodo_cod = (request.POST.get('periodo') or '2026-2').strip()
    forzar_llm = (request.POST.get('forzar_llm') or '').lower() == 'true'

    if not archivos:
        return JsonResponse({'success': False, 'error': 'No se adjuntó ningún archivo.'}, status=400)

    EXT_OK = ('csv', 'xlsx', 'xls', 'pdf', 'docx')
    pares = []
    for f in archivos:
        if f.size > 8 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': f'{f.name} supera 8 MB.'}, status=400)
        ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else ''
        if ext not in EXT_OK:
            return JsonResponse({'success': False,
                                 'error': f'Formato .{ext} no soportado ({f.name}). Usa CSV, XLSX, PDF o DOCX.'},
                                status=400)
        try:
            pares.append((f.name, f.read()))
        except Exception as exc:
            return JsonResponse({'success': False, 'error': f'No se pudo leer {f.name}: {exc}'}, status=400)

    uid = getattr(request.user, 'id_usuario', None) or request.user.pk
    try:
        from siihapi.motor_ia.pipeline import analizar_archivo_pipeline, analizar_multiples_archivos
        if len(pares) >= 2:
            # CRUCE multi-documento (2+ archivos)
            resultado = analizar_multiples_archivos(pares, periodo=periodo_cod, usuario_id=uid,
                                                    forzar_llm=forzar_llm)
            nombre = ' + '.join(n for n, _ in pares)
        else:
            nombre, contenido = pares[0]
            resultado = analizar_archivo_pipeline(
                contenido=contenido, nombre_archivo=nombre,
                periodo=periodo_cod, usuario_id=uid, forzar_llm=forzar_llm,
            )
    except ImportError as exc:
        return JsonResponse({
            'success': False,
            'error': f'Falta una librería para procesar el archivo: {exc}. '
                     f'Instala: pip install pdfplumber python-docx openpyxl'
        }, status=500)
    except Exception as exc:
        import logging
        logging.exception('Motor IA analizar archivo')
        return JsonResponse({'success': False, 'error': f'Error analizando el archivo: {str(exc)[:300]}'}, status=500)

    resultado['success'] = True
    resultado['archivo'] = nombre
    return JsonResponse(resultado)


@operacion_required
def motor_ia_descargar_borrador(request):
    """Exporta los horarios PROPUESTO/APROBADO (borrador) a Excel para AUDITORIA
    HUMANA antes de publicar a SISCA. Incluye carrera, periodo y jornada para
    evitar publicar a otra carrera/periodo."""
    from django.http import HttpResponse
    import io as _io

    def _jornada(hi):
        try:
            h = hi.hour if hasattr(hi, 'hour') else int(str(hi)[:2])
        except Exception:
            return 'N/D'
        if 7 <= h < 10:   return 'DIURNA'
        if 10 <= h < 13:  return 'ESPECIAL'
        if 13 <= h < 18:  return 'TARDE'
        if 18 <= h < 22:  return 'NOCTURNA'
        return 'OTRA'

    qs = (Horario.objects.filter(estado__in=['PROPUESTO', 'APROBADO'])
          .select_related('materia__programa', 'docente__usuario', 'salon__sede',
                          'bloque', 'matricula__periodo', 'matricula__estudiante__usuario')
          .order_by('materia__programa__nombre', 'dia', 'bloque__numero'))

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        messages.error(request, 'Falta openpyxl para exportar Excel.')
        return redirect('motor_ia')

    wb = Workbook()
    ws = wb.active
    ws.title = 'Borrador Horario'
    cols = ['Carrera/Programa', 'Periodo', 'Jornada', 'Dia', 'Bloque',
            'Hora inicio', 'Hora fin', 'Cod. Materia', 'Materia', 'Grupo',
            'Docente', 'Correo docente', 'Salon', 'Sede', 'Estado']
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F4988')
        c.alignment = Alignment(horizontal='center')

    for h in qs:
        prog = getattr(getattr(h.materia, 'programa', None), 'nombre', '') or 'N/D'
        per = getattr(getattr(getattr(h, 'matricula', None), 'periodo', None), 'codigo', '') or ''
        try:
            hi = h.bloque.hora_inicio.strftime('%H:%M'); hf = h.bloque.hora_fin.strftime('%H:%M')
        except Exception:
            hi = hf = ''
        doc = h.docente.usuario if h.docente_id else None
        ws.append([
            prog, per, _jornada(h.bloque.hora_inicio if h.bloque_id else None),
            h.get_dia_display(), f'B{h.bloque.numero}' if h.bloque_id else '',
            hi, hf, getattr(h.materia, 'codigo', ''), getattr(h.materia, 'nombre', ''),
            '', f'{doc.nombre} {doc.apellido}' if doc else '',
            getattr(doc, 'correo', '') or getattr(doc, 'email', '') if doc else '',
            getattr(h.salon, 'codigo', ''),
            getattr(getattr(h.salon, 'sede', None), 'nombre', '') if h.salon_id else '',
            h.get_estado_display(),
        ])
    anchos = [28, 10, 12, 12, 8, 11, 11, 12, 30, 12, 26, 26, 12, 16, 18]
    for i, w in enumerate(anchos, 1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else 'A'].width = w

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="borrador_horario_para_auditar.xlsx"'
    return resp


# ════════════════════════════════════════════════════════════════
#  Edición guiada por IA (propuesta + confirmación)
# ════════════════════════════════════════════════════════════════

_DIAS_MAP_EDIT = {
    'lunes': 'LU', 'lun': 'LU', 'lu': 'LU',
    'martes': 'MA', 'mar': 'MA', 'ma': 'MA',
    'miercoles': 'MI', 'miércoles': 'MI', 'mie': 'MI', 'mié': 'MI', 'mi': 'MI',
    'jueves': 'JU', 'jue': 'JU', 'ju': 'JU',
    'viernes': 'VI', 'vie': 'VI', 'vi': 'VI',
    'sabado': 'SA', 'sábado': 'SA', 'sab': 'SA', 'sa': 'SA',
}
_DIA_NOMBRE = {'LU': 'Lunes', 'MA': 'Martes', 'MI': 'Miércoles',
               'JU': 'Jueves', 'VI': 'Viernes', 'SA': 'Sábado'}


def _parsear_instruccion_edicion(texto):
    """Convierte una instrucción en lenguaje natural a un plan estructurado.
    Heurístico en español (no depende de API externa). Devuelve dict o None."""
    import re
    t = ' ' + (texto or '').lower().strip() + ' '

    # Días mencionados, en orden de aparición
    dias_encontrados = []
    for palabra, cod in sorted(_DIAS_MAP_EDIT.items(), key=lambda x: -len(x[0])):
        for m in re.finditer(r'\b' + re.escape(palabra) + r'\b', t):
            dias_encontrados.append((m.start(), cod))
    dias_encontrados.sort()
    dias_orden = []
    for _, c in dias_encontrados:
        if c not in dias_orden:
            dias_orden.append(c)

    # Código de materia (3 a 6 dígitos)
    mat = re.search(r'\b(\d{3,6})\b', t)
    materia = mat.group(1) if mat else None

    filtro = {}
    if materia:
        filtro['materia'] = materia

    # ── Acción: aprobar ──
    if re.search(r'\baprob(ar|a|ado|emos)\b', t):
        if dias_orden:
            filtro['dia'] = dias_orden[0]
        return {'accion': 'cambiar_estado', 'valor': 'APROBADO', 'filtro': filtro,
                'descripcion': 'Aprobar ' + (_desc_filtro(filtro) or 'todos los horarios propuestos')}

    # ── Acción: cancelar / anular ──
    if re.search(r'\b(cancel(ar|a|ado)|anul(ar|a|ado))\b', t):
        if dias_orden:
            filtro['dia'] = dias_orden[0]
        return {'accion': 'cambiar_estado', 'valor': 'CANCELADO', 'filtro': filtro,
                'descripcion': 'Cancelar ' + (_desc_filtro(filtro) or 'los horarios indicados')}

    # ── Acción: mover/cambiar de día X a día Y ──
    if re.search(r'\b(mover|mueve|pasa(r)?|cambia(r)?|mover|trasladar|traslada)\b', t) and len(dias_orden) >= 2:
        origen, destino = dias_orden[0], dias_orden[1]
        filtro['dia'] = origen
        return {'accion': 'cambiar_dia', 'valor': destino, 'filtro': filtro,
                'descripcion': f'Mover clases de {_DIA_NOMBRE[origen]} a {_DIA_NOMBRE[destino]}'
                               + (f' (materia {materia})' if materia else '')}

    # ── Acción: cambiar todo a un día concreto ──
    if re.search(r'\b(mover|mueve|pasa(r)?|cambia(r)?|poner|pon)\b', t) and len(dias_orden) == 1:
        return {'accion': 'cambiar_dia', 'valor': dias_orden[0], 'filtro': filtro,
                'descripcion': f'Mover {_desc_filtro(filtro) or "los horarios"} a {_DIA_NOMBRE[dias_orden[0]]}'}

    return None


def _desc_filtro(filtro):
    partes = []
    if filtro.get('dia'):
        partes.append(f'los de {_DIA_NOMBRE.get(filtro["dia"], filtro["dia"])}')
    if filtro.get('materia'):
        partes.append(f'la materia {filtro["materia"]}')
    return ' · '.join(partes) if partes else ''


def _queryset_desde_filtro(filtro):
    """Construye el queryset de horarios editables (no publicados/cancelados)."""
    qs = Horario.objects.filter(estado__in=['PROPUESTO', 'APROBADO']).select_related(
        'materia', 'docente__usuario', 'salon', 'bloque'
    )
    if filtro.get('dia'):
        qs = qs.filter(dia=filtro['dia'])
    if filtro.get('materia'):
        qs = qs.filter(materia__codigo__icontains=filtro['materia'])
    return qs


@operacion_required
@require_http_methods(["POST"])
def motor_ia_proponer_edicion(request):
    """Interpreta una instrucción y devuelve un plan de cambios SIN aplicarlo."""
    instruccion = (request.POST.get('instruccion') or '').strip()
    if not instruccion:
        return JsonResponse({'success': False, 'error': 'Escribe una instrucción.'}, status=400)

    plan = _parsear_instruccion_edicion(instruccion)
    if not plan:
        return JsonResponse({
            'success': False,
            'no_entendido': True,
            'error': 'No entendí la instrucción. Ejemplos: "pasa las clases de lunes a martes", '
                     '"aprueba todos los de viernes", "cancela la materia 0569".'
        })

    qs = _queryset_desde_filtro(plan['filtro'])
    afectados = qs.count()
    if afectados == 0:
        return JsonResponse({
            'success': False,
            'error': f'La acción "{plan["descripcion"]}" no afecta ningún horario editable '
                     f'(propuesto o aprobado).'
        })

    # ── Vista previa: hasta 25 filas con el cambio actual -> nuevo ──
    preview = []
    if plan['accion'] == 'cambiar_dia':
        campo = 'Día'
        valor_nuevo_lbl = _DIA_NOMBRE.get(plan['valor'], plan['valor'])
    else:  # cambiar_estado
        campo = 'Estado'
        valor_nuevo_lbl = dict(Horario.ESTADO_CHOICES).get(plan['valor'], plan['valor'])

    for h in qs[:25]:
        try:
            est_cod = h.matricula.estudiante.codigo if h.matricula_id else '—'
        except Exception:
            est_cod = '—'
        if plan['accion'] == 'cambiar_dia':
            valor_actual = _DIA_NOMBRE.get(h.dia, h.dia)
        else:
            valor_actual = h.get_estado_display()
        try:
            bloque_lbl = f"B{h.bloque.numero} {h.bloque.hora_inicio.strftime('%H:%M')}"
        except Exception:
            bloque_lbl = '—'
        preview.append({
            'materia':   getattr(h.materia, 'codigo', '—'),
            'estudiante': est_cod,
            'dia':       _DIA_NOMBRE.get(h.dia, h.dia),
            'bloque':    bloque_lbl,
            'salon':     getattr(h.salon, 'codigo', '—'),
            'de':        valor_actual,
            'a':         valor_nuevo_lbl,
        })

    return JsonResponse({
        'success': True,
        'plan': plan,
        'descripcion': plan['descripcion'],
        'afectados': afectados,
        'campo': campo,
        'preview': preview,
        'preview_truncado': afectados > 25,
    })


@operacion_required
@require_http_methods(["POST"])
def motor_ia_aplicar_edicion(request):
    """Aplica un plan de edición previamente confirmado por el usuario."""
    import json as _json
    try:
        plan = _json.loads(request.POST.get('plan') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'error': 'Plan inválido.'}, status=400)

    accion = plan.get('accion')
    valor = plan.get('valor')
    filtro = plan.get('filtro') or {}
    if accion not in ('cambiar_dia', 'cambiar_estado'):
        return JsonResponse({'success': False, 'error': 'Acción no soportada.'}, status=400)

    qs = _queryset_desde_filtro(filtro)
    total = qs.count()
    if total == 0:
        return JsonResponse({'success': False, 'error': 'No hay horarios para modificar.'})

    modificados = 0
    try:
        if accion == 'cambiar_dia':
            if valor not in dict(Horario.DIA_CHOICES):
                return JsonResponse({'success': False, 'error': f'Día destino inválido: {valor}'}, status=400)
            modificados = qs.update(dia=valor)
        elif accion == 'cambiar_estado':
            if valor not in dict(Horario.ESTADO_CHOICES):
                return JsonResponse({'success': False, 'error': f'Estado inválido: {valor}'}, status=400)
            modificados = qs.update(estado=valor)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': f'Error al aplicar: {str(exc)[:200]}'}, status=500)

    return JsonResponse({
        'success': True,
        'modificados': modificados,
        'mensaje': f'✅ {modificados} horario(s) actualizados: {plan.get("descripcion", "")}',
    })


@operacion_required
@require_http_methods(["POST"])
def motor_ia_ejecutar(request):
    """RF-26 - Motor IA Hibrido: CSP solver + LLM analyst."""
    from .motor_ia import resolver_csp, analizar_horario_con_ia, proveedor_disponible, SolverError
    from .motor_ia.jornadas import bloques_validos_para_ia

    periodo_cod = request.POST.get('periodo', '2026-2')
    modo = request.POST.get('modo', 'COMPLETA')
    llm_forzado = request.POST.get('llm') or None  # GEMINI | OPENAI | ANTHROPIC | HEURISTIC | None=auto

    try:
        periodo = Periodo.objects.get(codigo=periodo_cod)
    except Periodo.DoesNotExist:
        return JsonResponse({'success': False, 'error': f'Periodo {periodo_cod} no existe'}, status=400)

    if modo == 'COMPLETA':
        Horario.objects.filter(
            matricula__periodo=periodo, estado='PROPUESTO',
        ).delete()

    inicio = timezone.now()
    job_id = f'IA-{periodo_cod}-{uuid.uuid4().hex[:8].upper()}'

    asignacion = AsignacionIA.objects.create(
        periodo=periodo, estado='EJECUTANDO', job_id=job_id,
        fecha_inicio=inicio, creado_por=request.user,
        parametros={'modo': modo, 'lanzado_por': request.user.correo},
    )

    # === Cargar datos para el solver ===
    matriculas = list(Matricula.objects.filter(periodo=periodo, estado='ACTIVA').select_related(
        'estudiante', 'materia__programa__facultad'
    )[:1000])
    # Fase 4 (2026-09-05): excluye sedes inactivas (ej. Calle 80, aun no
    # habilitada -- marcala como Inactiva en Sedes desde el Admin) y
    # restringe los bloques a las 4 jornadas fijas (RF-39, ver
    # motor_ia/jornadas.py); corre 'python manage.py corregir_bloques_horario
    # --aplicar' si bloques queda vacio.
    salones = list(Salon.objects.filter(activo=True, sede__estado='A').select_related('sede'))
    bloques = bloques_validos_para_ia(list(Bloque.objects.all().order_by('numero')))
    docentes = list(Docente.objects.filter(activo=True).select_related('facultad', 'sede'))

    if not (docentes and salones and bloques and matriculas):
        # Fase 3 (2026-09-04): antes este mensaje era genérico ("Faltan
        # datos") y no decía CUÁL de los 4 conjuntos estaba vacío ni para
        # qué periodo -- obligaba a adivinar. Ahora arma la lista exacta de
        # lo que falta, con los conteos reales de ESTE periodo, y si el
        # problema son las matrículas distingue el caso más común: sí hay
        # inscripciones pero están en INSCRITA (pre-registro sin confirmar,
        # ver importar_inscritos) y el motor solo usa ACTIVA.
        faltantes = []
        if not docentes:
            faltantes.append('docentes activos (0 encontrados) — revisa Docentes y marca activos=True')
        if not salones:
            faltantes.append('salones activos (0 encontrados) — revisa Sedes y Salones')
        if not bloques:
            faltantes.append(
                'bloques horarios dentro de las 4 jornadas fijas (Diurna/Especial/'
                'Nocturna/Sabatino) -- corre \'python manage.py corregir_bloques_horario '
                '--aplicar\' una sola vez, es idempotente'
            )
        if not matriculas:
            inscritas = Matricula.objects.filter(periodo=periodo, estado='INSCRITA').count()
            if inscritas:
                faltantes.append(
                    f'matrículas ACTIVAS para {periodo_cod} (0 activas, pero hay {inscritas} en '
                    f'estado INSCRITA sin confirmar — el motor no las usa hasta que se confirmen)'
                )
            else:
                faltantes.append(f'matrículas para el periodo {periodo_cod} (0 encontradas, ni activas ni inscritas)')

        mensaje_log = 'Faltan datos: ' + '; '.join(faltantes)
        asignacion.estado = 'FALLIDA'
        asignacion.fecha_fin = timezone.now()
        asignacion.log = mensaje_log
        asignacion.save()

        if not matriculas and Matricula.objects.filter(periodo=periodo, estado='INSCRITA').exists():
            sugerencia = (
                f'Las inscripciones de {periodo_cod} están como INSCRITA (pre-registro), no ACTIVA. '
                f'Consigue el Excel "INSCRITOS POR CICLO" actualizado (con ESTADO=MATRICULADO para los '
                f'confirmados) y vuelve a correr: python manage.py importar_inscritos ruta\\archivo.xlsx '
                f'--periodo {periodo_cod} — es idempotente, solo sube de INSCRITA a ACTIVA, nunca al revés.'
            )
        elif not matriculas:
            sugerencia = (
                f'No hay ninguna matrícula (ni activa ni inscrita) para {periodo_cod}. Impórtalas con: '
                f'python manage.py importar_inscritos ruta\\archivo.xlsx --periodo {periodo_cod}'
            )
        else:
            sugerencia = 'Carga los datos base (docentes, salones o bloques) desde sus módulos en el dashboard de Admin.'

        return JsonResponse({
            'success': False,
            'error': 'No hay suficientes datos para el solver: ' + '; '.join(faltantes),
            'sugerencia': sugerencia,
            'faltantes': {
                'docentes': len(docentes), 'salones': len(salones),
                'bloques': len(bloques), 'matriculas_activas': len(matriculas),
                'matriculas_inscritas': Matricula.objects.filter(periodo=periodo, estado='INSCRITA').count(),
            },
        }, status=400)

    # === Cargar restricciones de disponibilidad docente (RF-17) ===
    restricciones = list(
        DisponibilidadDocente.objects.filter(docente__activo=True)
        .values_list('docente_id', 'dia', 'bloque__numero')
    )

    if modo == 'SIMULACION':
        # Solo contar sin escribir
        try:
            resultado = resolver_csp(matriculas, docentes, salones, bloques,
                                     restricciones_docente=restricciones)
            asignadas = resultado.asignadas
            conflictos = resultado.conflictos
            algoritmo = resultado.algoritmo
        except SolverError as e:
            asignacion.estado = 'FALLIDA'
            asignacion.fecha_fin = timezone.now()
            asignacion.log = str(e)
            asignacion.save()
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    else:
        # === Ejecutar CSP solver ===
        try:
            resultado = resolver_csp(matriculas, docentes, salones, bloques,
                                     restricciones_docente=restricciones)
        except SolverError as e:
            asignacion.estado = 'FALLIDA'
            asignacion.fecha_fin = timezone.now()
            asignacion.log = str(e)
            asignacion.save()
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

        # Persistir horarios
        horarios_a_crear = []
        for h in resultado.horarios:
            horarios_a_crear.append(Horario(
                matricula=h['matricula'],
                materia=h['matricula'].materia,
                docente=h['docente'],
                salon=h['salon'],
                bloque=h['bloque'],
                dia=h['dia'],
                estado='PROPUESTO',
            ))
        if horarios_a_crear:
            Horario.objects.bulk_create(horarios_a_crear, batch_size=200)

        asignadas = resultado.asignadas
        conflictos = resultado.conflictos
        algoritmo = resultado.algoritmo

    # === Calcular metricas para el LLM ===
    distribucion_dia = {'LU': 0, 'MA': 0, 'MI': 0, 'JU': 0, 'VI': 0}
    distribucion_salon = {}
    carga_docente = {}
    if modo != 'SIMULACION':
        for h in resultado.horarios:
            distribucion_dia[h['dia']] = distribucion_dia.get(h['dia'], 0) + 1
            tipo = h['salon'].tipo
            distribucion_salon[tipo] = distribucion_salon.get(tipo, 0) + 1
            doc_nombre = h['docente'].usuario.nombre_completo
            carga_docente[doc_nombre] = carga_docente.get(doc_nombre, 0) + 1

    top_docentes = sorted(carga_docente.items(), key=lambda x: -x[1])[:5]
    fin = timezone.now()
    duracion_ms = int((fin - inicio).total_seconds() * 1000)
    tasa_exito = round((asignadas / len(matriculas)) * 100, 1) if matriculas else 0

    # === Llamar al LLM para analisis ===
    datos_llm = {
        'periodo': periodo_cod,
        'total_matriculas': len(matriculas),
        'asignadas': asignadas,
        'conflictos': conflictos,
        'tasa_exito': tasa_exito,
        'algoritmo': algoritmo,
        'duracion_ms': duracion_ms,
        'sedes': Sede.objects.filter(estado='A').count(),
        'salones': len(salones),
        'docentes': len(docentes),
        'distribucion_dia': ', '.join(f'{d}={c}' for d, c in distribucion_dia.items()),
        'distribucion_salon': ', '.join(f'{t}={c}' for t, c in list(distribucion_salon.items())[:5]) or 'N/A',
        'carga_docente': '\n'.join(f'  - {n}: {c} horas' for n, c in top_docentes) or '  - Sin datos',
    }

    llm_result = analizar_horario_con_ia(datos_llm, forzar_proveedor=llm_forzado)

    # === Guardar todo en AsignacionIA ===
    asignacion.estado = 'COMPLETADA'
    asignacion.fecha_fin = fin
    asignacion.duracion_ms = duracion_ms
    asignacion.total_matriculas = len(matriculas)
    asignacion.asignaciones_exitosas = asignadas
    asignacion.conflictos_residuales = conflictos
    asignacion.log = (
        f'=== CSP SOLVER ===\n'
        f'Algoritmo: {algoritmo}\n'
        f'Matriculas: {len(matriculas)} | Asignadas: {asignadas} | Conflictos: {conflictos}\n'
        f'Restricciones docente respetadas: {len(restricciones)}\n'
        f'Duracion: {duracion_ms} ms\n\n'
        f'=== LLM ANALYST ({llm_result.proveedor} · {llm_result.modelo}) ===\n'
        f'Score calidad: {llm_result.score_calidad}/100\n\n'
        f'Resumen: {llm_result.resumen_ejecutivo}\n\n'
        f'Sugerencias:\n' + '\n'.join(f'  - {s}' for s in llm_result.sugerencias) + '\n\n'
        f'Anomalias:\n' + '\n'.join(f'  - {a}' for a in llm_result.anomalias)
    )
    asignacion.parametros = {
        **(asignacion.parametros or {}),
        'algoritmo_csp': algoritmo,
        'llm_proveedor': llm_result.proveedor,
        'llm_modelo': llm_result.modelo,
        'score_calidad': llm_result.score_calidad,
        'resumen': llm_result.resumen_ejecutivo,
        'sugerencias': llm_result.sugerencias,
        'anomalias': llm_result.anomalias,
    }
    asignacion.save()

    return JsonResponse({
        'success': True,
        'job_id': job_id,
        'modo': modo,
        'estado': asignacion.estado,
        'matriculas': len(matriculas),
        'asignadas': asignadas,
        'conflictos': conflictos,
        'tasa_exito': tasa_exito,
        'duracion_ms': duracion_ms,
        'algoritmo': algoritmo,
        'llm': {
            'proveedor': llm_result.proveedor,
            'modelo': llm_result.modelo,
            'resumen': llm_result.resumen_ejecutivo,
            'sugerencias': llm_result.sugerencias,
            'anomalias': llm_result.anomalias,
            'score': llm_result.score_calidad,
        },
        'mensaje': f'CSP ({algoritmo}) + LLM ({llm_result.proveedor}) · {asignadas}/{len(matriculas)} asignadas · score {llm_result.score_calidad}/100',
    })


@operacion_required
def motor_ia_chat_view(request):
    """Pagina del chat conversacional IA."""
    from .motor_ia.llm import proveedor_disponible
    proveedor = proveedor_disponible()
    return render(request, 'dashboard/motor_ia_chat.html', {
        'proveedor_activo': proveedor,
    })


@operacion_required
@require_http_methods(["POST"])
def motor_ia_chat_enviar(request):
    """RF-37 (extension) - Chat conversacional con el LLM."""
    from .motor_ia import chat_llm
    import json as _json

    mensaje = request.POST.get('mensaje', '').strip()
    if not mensaje:
        return JsonResponse({'success': False, 'error': 'Mensaje vacio'}, status=400)

    historial_raw = request.POST.get('historial', '[]')
    try:
        historial = _json.loads(historial_raw)
    except Exception:
        historial = []

    # Si subio un archivo, leemos su contenido
    contexto_archivo = ''
    archivo = request.FILES.get('archivo')
    nombre_archivo = ''
    if archivo:
        nombre_archivo = archivo.name
        try:
            if archivo.name.lower().endswith(('.csv', '.txt')):
                raw = archivo.read()
                for enc in ('utf-8', 'latin-1', 'cp1252'):
                    try:
                        contexto_archivo = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
            elif archivo.name.lower().endswith(('.xlsx', '.xls')):
                from openpyxl import load_workbook
                wb = load_workbook(archivo, read_only=True, data_only=True)
                ws = wb.active
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 100:
                        rows.append('... (truncado en fila 100)')
                        break
                    rows.append(' | '.join(str(c) if c is not None else '' for c in row))
                contexto_archivo = '\n'.join(rows)
            elif archivo.name.lower().endswith('.pdf'):
                contexto_archivo = f'(Archivo PDF subido: {archivo.name}, {archivo.size} bytes. La extraccion de texto de PDF no esta habilitada todavia.)'
            else:
                contexto_archivo = f'(Tipo de archivo no soportado para lectura: {archivo.name})'
        except Exception as e:
            contexto_archivo = f'(Error leyendo archivo: {str(e)[:200]})'

    forzar = request.POST.get('proveedor') or None
    resultado = chat_llm(mensaje, historial=historial, contexto_archivo=contexto_archivo,
                        forzar_proveedor=forzar)
    resultado['archivo'] = nombre_archivo
    return JsonResponse(resultado)


@operacion_required
def motor_ia_metricas(request):
    asignaciones = AsignacionIA.objects.order_by('-fecha_inicio')[:50]
    total = AsignacionIA.objects.count()
    exitosas = AsignacionIA.objects.filter(estado='COMPLETADA').count()
    fallidas = AsignacionIA.objects.filter(estado='FALLIDA').count()
    promedio_ms = 0
    if total > 0:
        durs = list(AsignacionIA.objects.exclude(duracion_ms=None).values_list('duracion_ms', flat=True))
        if durs:
            promedio_ms = sum(durs) // len(durs)
    return render(request, 'dashboard/motor_ia_metricas.html', {
        'asignaciones': asignaciones,
        'stats': {
            'total': total, 'exitosas': exitosas, 'fallidas': fallidas,
            'promedio_ms': promedio_ms,
            'tasa_exito': round((exitosas / total) * 100, 1) if total > 0 else 0,
        },
    })


# Definicion de jornadas por hora de inicio del bloque (RF-26).
# Cada jornada: (etiqueta, hora_inicio_min, hora_inicio_max_exclusiva, solo_sabado)
JORNADAS = {
    'DIURNA':   {'label': 'Diurna (07:00–10:00)',  'ini': '07:00', 'fin': '10:00', 'sabado': False},
    'ESPECIAL': {'label': 'Especial (10:00–13:00)', 'ini': '10:00', 'fin': '13:00', 'sabado': False},
    'NOCTURNA': {'label': 'Nocturna (18:00–21:00)', 'ini': '18:00', 'fin': '21:00', 'sabado': False},
    'SABADO':   {'label': 'Sábados (07:00–17:00)',  'ini': '07:00', 'fin': '17:00', 'sabado': True},
    'VIRTUAL':  {'label': 'Virtual',                'ini': None,    'fin': None,    'sabado': False},
}


def _aplicar_filtros_horarios(qs, request):
    """Aplica filtros de estado, dia, jornada y busqueda de estudiante a un queryset."""
    from datetime import datetime as _dt

    estado_filtro = (request.GET.get('estado') or '').strip().upper()
    dia_filtro    = (request.GET.get('dia') or '').strip().upper()
    jornada       = (request.GET.get('jornada') or '').strip().upper()
    q             = (request.GET.get('q') or '').strip()
    materia       = (request.GET.get('materia') or '').strip()
    docente       = (request.GET.get('docente') or '').strip()
    ciclo         = (request.GET.get('ciclo') or '').strip()
    carrera       = (request.GET.get('carrera') or '').strip()
    periodo_f     = (request.GET.get('periodo') or '').strip()

    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)
    if dia_filtro:
        qs = qs.filter(dia=dia_filtro)

    # Filtro por MATERIA (codigo o nombre)
    if materia:
        qs = qs.filter(Q(materia__codigo__icontains=materia) |
                       Q(materia__nombre__icontains=materia))
    # Filtro por DOCENTE (nombre, apellido o correo)
    if docente:
        qs = qs.filter(Q(docente__usuario__nombre__icontains=docente) |
                       Q(docente__usuario__apellido__icontains=docente) |
                       Q(docente__usuario__correo__icontains=docente))
    # Filtro por CICLO (semestre de la materia)
    if ciclo:
        try:
            qs = qs.filter(materia__ciclo=int(ciclo))
        except ValueError:
            pass
    # Filtro por CARRERA / PROGRAMA (codigo o nombre)
    if carrera:
        qs = qs.filter(Q(materia__programa__codigo__icontains=carrera) |
                       Q(materia__programa__nombre__icontains=carrera))
    # Filtro por TRIMESTRE / PERIODO (codigo, ej 2026-2)
    if periodo_f:
        qs = qs.filter(matricula__periodo__codigo__icontains=periodo_f)

    # Jornada por rango horario del bloque
    if jornada in JORNADAS:
        j = JORNADAS[jornada]
        if jornada == 'VIRTUAL':
            qs = qs.filter(Q(salon__tipo__icontains='VIRTUAL') |
                           Q(salon__nombre__icontains='VIRTUAL') |
                           Q(salon__observaciones__icontains='VIRTUAL'))
        else:
            if j['sabado']:
                qs = qs.filter(dia='SA')
            try:
                hi = _dt.strptime(j['ini'], '%H:%M').time()
                hf = _dt.strptime(j['fin'], '%H:%M').time()
                qs = qs.filter(bloque__hora_inicio__gte=hi, bloque__hora_inicio__lt=hf)
            except Exception:
                pass

    # Busqueda por estudiante: codigo, cedula, nombre o apellido
    if q:
        qs = qs.filter(
            Q(matricula__estudiante__codigo__icontains=q) |
            Q(matricula__estudiante__usuario__cedula__icontains=q) |
            Q(matricula__estudiante__usuario__nombre__icontains=q) |
            Q(matricula__estudiante__usuario__apellido__icontains=q)
        )

    return qs, {
        'estado': estado_filtro, 'dia': dia_filtro,
        'jornada': jornada, 'q': q,
        'materia': materia, 'docente': docente,
        'ciclo': ciclo, 'carrera': carrera, 'periodo': periodo_f,
    }


@staff_required
def horarios_view(request):
    base = Horario.objects.select_related(
        'matricula__estudiante__usuario', 'materia', 'docente__usuario',
        'salon__sede', 'bloque'
    )
    horarios_qs, filtros = _aplicar_filtros_horarios(base, request)
    horarios = horarios_qs.order_by('estado', 'dia', 'bloque__numero')[:500]

    # Contadores SIEMPRE sobre la tabla completa (no filtrada) para los KPIs
    conteo = {e[0]: Horario.objects.filter(estado=e[0]).count()
              for e in Horario.ESTADO_CHOICES}

    # Tarjetas de estado con color e icono
    cfg_estado = {
        'PROPUESTO': {'icon': '🤖', 'color': '#A78BFA', 'sub': 'Pendientes de revisión'},
        'APROBADO':  {'icon': '✅', 'color': '#4ADE80', 'sub': 'Listos para publicar'},
        'PUBLICADO': {'icon': '📡', 'color': '#22D3EE', 'sub': 'Activos en SISCA'},
        'CANCELADO': {'icon': '🚫', 'color': '#F87171', 'sub': 'Anulados'},
    }
    tarjetas = [{
        'codigo': e[0], 'label': e[1], 'count': conteo.get(e[0], 0),
        'icon': cfg_estado.get(e[0], {}).get('icon', '📌'),
        'color': cfg_estado.get(e[0], {}).get('color', '#9CA8BB'),
        'sub': cfg_estado.get(e[0], {}).get('sub', ''),
    } for e in Horario.ESTADO_CHOICES]

    # Pendientes de aprobar (lista corta para la sección destacada)
    pendientes = (Horario.objects.select_related(
                      'matricula__estudiante__usuario', 'materia',
                      'docente__usuario', 'salon', 'bloque')
                  .filter(estado='PROPUESTO')
                  .order_by('dia', 'bloque__numero')[:50])

    return render(request, 'dashboard/horarios.html', {
        'horarios': horarios,
        'estados': Horario.ESTADO_CHOICES,
        'dias': Horario.DIA_CHOICES,
        'jornadas': [(k, v['label']) for k, v in JORNADAS.items()],
        'filtros': filtros,
        'estado_filtro': filtros['estado'],
        'total': Horario.objects.count(),
        'total_filtrado': horarios_qs.count(),
        'tarjetas': tarjetas,
        'conteo': conteo,
        'pendientes': pendientes,
        'num_pendientes': conteo.get('PROPUESTO', 0),
        'num_aprobados': conteo.get('APROBADO', 0),
        # Catálogos para el modal de edición inline
        'cat_salones': Salon.objects.filter(activo=True).select_related('sede').order_by('sede__nombre', 'codigo'),
        'cat_docentes': Docente.objects.filter(activo=True).select_related('usuario').order_by('usuario__apellido'),
        'cat_bloques': Bloque.objects.order_by('numero'),
        # Catálogos para los filtros de carrera y ciclo
        'cat_carreras': Programa.objects.filter(activo=True).order_by('nombre'),
        # Orden cronologico (1,2,...,12), no alfabetico -- ver _ciclo_sort_key.
        'cat_ciclos': sorted(set(
            Materia.objects.exclude(ciclo=None).values_list('ciclo', flat=True)
        ), key=_ciclo_sort_key),
        'cat_periodos': Periodo.objects.order_by('-codigo'),
    })


@operacion_required
@require_http_methods(["POST"])
def generar_horarios_desde_matriculas(request):
    """Genera horarios PROPUESTO desde las matriculas activas, asignando
    dia/bloque/salon/docente SIN choques y DISTRIBUYENDO de forma equilibrada
    por toda la semana y jornadas.

    INICIALIZA DESDE CERO: borra los PROPUESTO previos del periodo (nunca toca
    APROBADO ni PUBLICADO) para no heredar asignaciones viejas (p. ej. todo en lunes).
    """
    # Jornada regular = Lunes a Viernes. El SABADO es CICLO ESPECIAL (no se mezcla):
    # los estudiantes de L-V no llevan clases el sabado.
    incluir_sabado = (request.POST.get('incluir_sabado') or '').lower() == 'true'
    DIAS = ['LU', 'MA', 'MI', 'JU', 'VI'] + (['SA'] if incluir_sabado else [])
    destino_error = request.META.get('HTTP_REFERER') or '/dashboard/carga-masiva/'

    periodo = get_periodo_seleccionado(request)
    matriculas = list(
        Matricula.objects.filter(estado='ACTIVA')
        .select_related('materia', 'estudiante').order_by('id_matricula')
    )
    if periodo:
        matriculas = [m for m in matriculas if m.periodo_id == periodo.id_periodo] or matriculas

    docentes = list(Docente.objects.filter(activo=True).select_related('usuario'))
    salones = list(Salon.objects.filter(activo=True))
    bloques = list(Bloque.objects.order_by('numero'))

    if not matriculas:
        messages.error(request, 'No hay matriculas ACTIVAS. Carga estudiantes y matriculas primero.')
        return redirect(destino_error)
    if not (docentes and salones and bloques):
        messages.error(request, f'Faltan datos base: docentes={len(docentes)}, '
                                f'salones={len(salones)}, bloques={len(bloques)}.')
        return redirect(destino_error)

    # ── INICIALIZAR DESDE CERO: limpiar PROPUESTO previos (no toca aprobados/publicados) ──
    borrados = Horario.objects.filter(estado='PROPUESTO').delete()[0]

    # Matriculas que ya tienen horario APROBADO/PUBLICADO (no se duplican)
    con_horario_firme = set(
        Horario.objects.filter(estado__in=['APROBADO', 'PUBLICADO'])
        .values_list('matricula_id', flat=True)
    )
    # Ocupacion solo de lo firme (para no chocar con lo ya aprobado/publicado)
    ocupado_salon, ocupado_docente = set(), set()
    for h in Horario.objects.filter(estado__in=['APROBADO', 'PUBLICADO']):
        ocupado_salon.add((h.dia, h.bloque_id, h.salon_id))
        ocupado_docente.add((h.dia, h.bloque_id, h.docente_id))

    # FASES 1+2 — Salon (tipo/capacidad/virtual) + docente (disponibilidad/carga/creditos).
    from siihapi.motor_ia.salones import salon_apto, es_programa_virtual
    from siihapi.motor_ia.docentes import horas_materia, cargar_disponibilidad, docente_disponible, carga_max
    _disp = cargar_disponibilidad()
    _carga_max = {d.usuario_id: carga_max(d) for d in docentes}
    _carga_usada = {d.usuario_id: 0.0 for d in docentes}
    # Salon virtual (los programas virtuales NO ocupan salon fisico)
    salon_virtual = (Salon.objects.filter(tipo__icontains='VIRT').first()
                     or Salon.objects.filter(nombre__icontains='VIRTUAL').first()
                     or Salon.objects.filter(codigo__iexact='VIRTUAL').first())
    if not salon_virtual:
        _sede = Sede.objects.first()
        if _sede:
            salon_virtual, _ = Salon.objects.get_or_create(
                sede=_sede, codigo='VIRTUAL',
                defaults={'nombre': 'Aula Virtual', 'capacidad': 999, 'tipo': 'AULA'})

    # Distribucion equilibrada: barajar dias x bloques (el salon se elige por materia)
    import random as _rnd
    slots = [(d, b) for b in bloques for d in DIAS]
    _rnd.shuffle(slots)
    salones_barajados = list(salones); _rnd.shuffle(salones_barajados)

    # nº de estudiantes por (materia, grupo) para validar capacidad
    creados = 0
    nuevos = []
    s_idx = 0
    n_slots = len(slots)
    docentes_barajados = list(docentes); _rnd.shuffle(docentes_barajados)
    for idx, mat in enumerate(matriculas):
        if mat.id_matricula in con_horario_firme:
            continue
        materia = mat.materia
        horas = horas_materia(getattr(materia, 'creditos', 0), getattr(materia, 'horas_semanales', None))
        prog = getattr(materia, 'programa', None)
        virtual = prog and es_programa_virtual(getattr(prog, 'modalidad', ''), getattr(prog, 'tipo', ''))
        colocado = False
        intentos = 0
        while not colocado and intentos < n_slots:
            dia, bloque = slots[s_idx % n_slots]
            s_idx += 1
            intentos += 1
            # 1) Elegir DOCENTE: disponible en (dia,bloque), con carga libre, sin cruce
            docente = None
            for d in docentes_barajados:
                if (dia, bloque.id_bloque, d.usuario_id) in ocupado_docente:
                    continue
                if not docente_disponible(_disp, d.usuario_id, dia, bloque.numero):
                    continue
                if _carga_usada[d.usuario_id] + horas > _carga_max[d.usuario_id]:
                    continue
                docente = d; break
            if docente is None:
                continue  # ningun docente apto/libre en este slot
            # 2) Elegir SALON apto (o virtual)
            if virtual and salon_virtual:
                salon = salon_virtual
            else:
                salon = None
                for sa in salones_barajados:
                    if not salon_apto(getattr(sa, 'tipo', 'AULA'), materia.nombre,
                                      bool(getattr(materia, 'requiere_sala_sistemas', False))):
                        continue
                    if (dia, bloque.id_bloque, sa.id_salon) in ocupado_salon:
                        continue
                    salon = sa; break
                if salon is None:
                    continue
                ocupado_salon.add((dia, bloque.id_bloque, salon.id_salon))
            ocupado_docente.add((dia, bloque.id_bloque, docente.usuario_id))
            _carga_usada[docente.usuario_id] += horas
            nuevos.append(Horario(
                matricula=mat, materia=materia, docente=docente,
                salon=salon, bloque=bloque, dia=dia, estado='PROPUESTO',
            ))
            creados += 1
            colocado = True

    if nuevos:
        Horario.objects.bulk_create(nuevos, batch_size=200)

    if creados > 0:
        messages.success(
            request,
            f'🤖 La IA reinició y generó {creados} horario(s) PROPUESTO distribuidos por '
            f'toda la semana (se limpiaron {borrados} propuestos previos). Revísalos y apruébalos.')
    else:
        messages.info(request, 'No se generaron horarios nuevos (todas las matrículas ya tienen '
                               'horario aprobado/publicado).')
    return redirect('revision_propuesta')


@operacion_required
def revision_propuesta(request):
    """Panel de revisión visual post-IA / post-carga masiva.

    Muestra TODO en orden: KPIs, matriz semanal, carga por docente,
    ocupación por aula, distribución por programa, conflictos detectados.
    """
    from collections import defaultdict, Counter

    # Filtrar por estado (default = PROPUESTO + APROBADO, lo "pendiente de publicar")
    estado_filtro = request.GET.get('estado', 'PENDIENTES')
    qs = Horario.objects.select_related(
        'matricula__estudiante__usuario', 'matricula__periodo',
        'materia__programa__facultad', 'docente__usuario', 'salon__sede', 'bloque'
    )
    if estado_filtro == 'PENDIENTES':
        qs = qs.filter(estado__in=['PROPUESTO', 'APROBADO'])
    elif estado_filtro and estado_filtro != 'TODOS':
        qs = qs.filter(estado=estado_filtro)

    # Filtrar por periodo academico (2026-09-06): esta pantalla mezclaba TODOS
    # los periodos de una vez (una generacion del Motor IA para 2026-3T junto
    # con cargas masivas de otros periodos), lo que ademas contamina el conteo
    # de "conflictos" con choques entre periodos que en la vida real nunca se
    # superponen. Default 'TODOS' preserva el comportamiento anterior.
    periodo_filtro = request.GET.get('periodo', 'TODOS')
    if periodo_filtro and periodo_filtro != 'TODOS':
        qs = qs.filter(matricula__periodo__codigo=periodo_filtro)

    periodos_disponibles = list(
        Periodo.objects.filter(matricula__horarios__isnull=False)
        .distinct().order_by('-codigo').values_list('codigo', flat=True)
    )

    horarios = list(qs[:1500])
    bloques = list(Bloque.objects.all().order_by('numero'))

    # ───── KPIs ─────
    total = len(horarios)
    propuestos = sum(1 for h in horarios if h.estado == 'PROPUESTO')
    aprobados  = sum(1 for h in horarios if h.estado == 'APROBADO')
    publicados = sum(1 for h in horarios if h.estado == 'PUBLICADO')
    docentes_unicos = len({h.docente_id for h in horarios})
    salones_unicos  = len({h.salon_id for h in horarios})
    programas_unicos = len({h.materia.programa_id for h in horarios if h.materia and h.materia.programa_id})

    # ───── Matriz Calendario (Bloque x Día) ─────
    DIAS = [('LU','Lunes'), ('MA','Martes'), ('MI','Miércoles'),
            ('JU','Jueves'), ('VI','Viernes'), ('SA','Sábado')]
    matriz = defaultdict(lambda: defaultdict(list))  # matriz[bloque_num][dia] = [horarios]
    for h in horarios:
        matriz[h.bloque.numero][h.dia].append(h)

    # Convertir a lista ordenada para template
    calendario = []
    for b in bloques:
        fila = {
            'bloque': b,
            'celdas': []
        }
        for cod, lbl in DIAS:
            fila['celdas'].append({
                'dia_cod': cod,
                'dia_lbl': lbl,
                'horarios': matriz[b.numero][cod],
            })
        calendario.append(fila)

    # ───── Carga por Docente ─────
    carga_doc = defaultdict(list)
    for h in horarios:
        carga_doc[h.docente_id].append(h)
    docentes_data = []
    for did, hs in carga_doc.items():
        if not hs: continue
        d = hs[0].docente
        try:
            nombre = d.usuario.nombre_completo
        except Exception:
            nombre = f'Docente {did}'
        materias_unicas = len({h.materia_id for h in hs})
        dias_unicos = len({h.dia for h in hs})
        # Horas REALES (creditos x 1.5) y % de ocupacion vs carga del docente
        horas_reales = 0.0
        for h in hs:
            try: horas_reales += round((int(getattr(h.materia, 'creditos', 0) or 0)) * 1.5, 1)
            except Exception: horas_reales += 1.5
        try: cmax = int(getattr(d, 'carga_horaria_max', 0) or 0)
        except Exception: cmax = 0
        if cmax <= 0: cmax = 20
        ocup_doc = round(horas_reales / cmax * 100, 1) if cmax else 0
        docentes_data.append({
            'id': did,
            'nombre': nombre,
            'horas': len(hs),
            'horas_reales': horas_reales,
            'carga_max': cmax,
            'ocupacion_pct': ocup_doc,
            'sobrecargado': horas_reales > cmax,
            'materias': materias_unicas,
            'dias': dias_unicos,
            'horarios': hs,
        })
    docentes_data.sort(key=lambda x: -x['horas'])

    # ───── Ocupación por Aula ─────
    uso_aula = defaultdict(list)
    for h in horarios:
        uso_aula[h.salon_id].append(h)
    aulas_data = []
    capacidad_total = len(bloques) * 6  # 14 bloques x 6 dias
    for sid, hs in uso_aula.items():
        if not hs: continue
        s = hs[0].salon
        try:
            sede = s.sede.nombre if s.sede else '—'
        except Exception:
            sede = '—'
        ocupacion_pct = round((len(hs) / capacidad_total) * 100, 1) if capacidad_total else 0
        aulas_data.append({
            'id': sid,
            'codigo': getattr(s, 'codigo', '—'),
            'nombre': getattr(s, 'nombre', getattr(s, 'codigo', '—')),
            'sede': sede,
            'horas': len(hs),
            'ocupacion_pct': ocupacion_pct,
            'horarios': hs,
        })
    aulas_data.sort(key=lambda x: -x['horas'])

    # ───── Ocupación por Sede (2026-09-06, agregado a pedido del usuario) ─────
    por_sede = defaultdict(list)
    for h in horarios:
        try:
            sede_id = h.salon.sede_id if h.salon else None
        except Exception:
            sede_id = None
        por_sede[sede_id].append(h)
    sedes_data = []
    for sid, hs in por_sede.items():
        if not hs: continue
        try:
            sede_obj = hs[0].salon.sede if hs[0].salon else None
        except Exception:
            sede_obj = None
        nombre = getattr(sede_obj, 'nombre', None) or 'Sin sede asignada'
        aulas_unicas = len({h.salon_id for h in hs})
        docentes_s = len({h.docente_id for h in hs})
        sedes_data.append({
            'id': sid if sid is not None else 'SIN_SEDE',
            'nombre': nombre,
            'horas': len(hs),
            'aulas': aulas_unicas,
            'docentes': docentes_s,
            'horarios': hs,
        })
    sedes_data.sort(key=lambda x: -x['horas'])

    # ───── Distribución por Programa ─────
    por_programa = defaultdict(list)
    for h in horarios:
        if h.materia and h.materia.programa_id:
            por_programa[h.materia.programa_id].append(h)
    programas_data = []
    for pid, hs in por_programa.items():
        if not hs: continue
        p = hs[0].materia.programa
        materias_unicas = len({h.materia_id for h in hs})
        docentes_p = len({h.docente_id for h in hs})
        programas_data.append({
            'id': pid,
            'codigo': getattr(p, 'codigo', '—'),
            'nombre': getattr(p, 'nombre', '—'),
            'horas': len(hs),
            'materias': materias_unicas,
            'docentes': docentes_p,
            'horarios': hs,
        })
    programas_data.sort(key=lambda x: -x['horas'])

    # ───── Distribución por Facultad (2026-09-06, agregado a pedido del usuario) ─────
    por_facultad = defaultdict(list)
    for h in horarios:
        try:
            fac_id = h.materia.programa.facultad_id if h.materia and h.materia.programa_id else None
        except Exception:
            fac_id = None
        por_facultad[fac_id].append(h)
    facultades_data = []
    for fid, hs in por_facultad.items():
        if not hs: continue
        try:
            fac_obj = hs[0].materia.programa.facultad if hs[0].materia and hs[0].materia.programa_id else None
        except Exception:
            fac_obj = None
        codigo = getattr(fac_obj, 'codigo', '—') if fac_obj else '—'
        nombre = getattr(fac_obj, 'nombre', None) or 'Sin facultad asignada'
        programas_f = len({h.materia.programa_id for h in hs if h.materia and h.materia.programa_id})
        docentes_f = len({h.docente_id for h in hs})
        facultades_data.append({
            'id': fid if fid is not None else 'SIN_FAC',
            'codigo': codigo,
            'nombre': nombre,
            'horas': len(hs),
            'programas': programas_f,
            'docentes': docentes_f,
            'horarios': hs,
        })
    facultades_data.sort(key=lambda x: -x['horas'])

    # ───── Conflictos detectados ─────
    conflictos = []
    # Docente con dos clases mismo día/bloque
    seen_doc = {}
    seen_aula = {}
    for h in horarios:
        kd = (h.docente_id, h.dia, h.bloque_id)
        if kd in seen_doc:
            conflictos.append({
                'tipo': 'DOCENTE',
                'mensaje': f'{h.docente.usuario.nombre_completo} tiene 2 clases en {h.get_dia_display()} B{h.bloque.numero}',
                'horarios': [seen_doc[kd], h],
            })
        else:
            seen_doc[kd] = h
        ka = (h.salon_id, h.dia, h.bloque_id)
        if ka in seen_aula:
            conflictos.append({
                'tipo': 'AULA',
                'mensaje': f'Aula {h.salon.codigo} usada por 2 clases en {h.get_dia_display()} B{h.bloque.numero}',
                'horarios': [seen_aula[ka], h],
            })
        else:
            seen_aula[ka] = h

    # ───── Distribución por día ─────
    dist_dias = Counter(h.dia for h in horarios)
    horarios_por_dia = defaultdict(list)
    for h in horarios:
        horarios_por_dia[h.dia].append(h)
    dist_dias_data = [
        {'dia': lbl, 'cod': cod, 'total': dist_dias.get(cod, 0), 'horarios': horarios_por_dia.get(cod, [])}
        for cod, lbl in DIAS
    ]
    max_dia = max((d['total'] for d in dist_dias_data), default=1) or 1
    for d in dist_dias_data:
        d['pct'] = round((d['total'] / max_dia) * 100, 1) if max_dia else 0

    # ───── Última asignación IA ─────
    ultima_ia = AsignacionIA.objects.order_by('-fecha_inicio').first()

    return render(request, 'dashboard/revision_propuesta.html', {
        'kpis': {
            'total': total,
            'propuestos': propuestos,
            'aprobados': aprobados,
            'publicados': publicados,
            'docentes': docentes_unicos,
            'salones': salones_unicos,
            'programas': programas_unicos,
            'conflictos': len(conflictos),
        },
        'estado_filtro': estado_filtro,
        'estados': [('PENDIENTES','Pendientes de publicar'), ('PROPUESTO','Propuestos'),
                    ('APROBADO','Aprobados'), ('PUBLICADO','Publicados'), ('TODOS','Todos')],
        'periodo_filtro': periodo_filtro,
        'periodos_disponibles': periodos_disponibles,
        'calendario': calendario,
        'dias': DIAS,
        'docentes_data': docentes_data[:50],
        'aulas_data': aulas_data[:50],
        'sedes_data': sedes_data[:50],
        'programas_data': programas_data[:50],
        'facultades_data': facultades_data[:50],
        'conflictos': conflictos[:50],
        'dist_dias': dist_dias_data,
        'ultima_ia': ultima_ia,
        'total_horarios': total,
    })


@operacion_required
@require_http_methods(["POST"])
def revision_aprobar_todos(request):
    """Aprueba los horarios PROPUESTO de un golpe -- acotado al periodo activo
    en el filtro de la pantalla (2026-09-06: antes tocaba TODOS los periodos
    a la vez, mezclando distintas generaciones del Motor IA sin querer)."""
    periodo = request.POST.get('periodo') or request.GET.get('periodo') or 'TODOS'
    qs = Horario.objects.filter(estado='PROPUESTO')
    if periodo and periodo != 'TODOS':
        qs = qs.filter(matricula__periodo__codigo=periodo)
    n = qs.update(estado='APROBADO')
    return JsonResponse({'success': True, 'aprobados': n, 'mensaje': f'{n} horarios aprobados'})


@operacion_required
@require_http_methods(["POST"])
def revision_eliminar_propuesta(request):
    """Elimina los horarios PROPUESTO sin publicar (para regenerar) -- acotado
    al periodo activo en el filtro de la pantalla (ver revision_aprobar_todos)."""
    periodo = request.POST.get('periodo') or request.GET.get('periodo') or 'TODOS'
    qs = Horario.objects.filter(estado='PROPUESTO')
    if periodo and periodo != 'TODOS':
        qs = qs.filter(matricula__periodo__codigo=periodo)
    n, _ = qs.delete()
    return JsonResponse({'success': True, 'eliminados': n, 'mensaje': f'{n} propuestas eliminadas'})


@operacion_required
def centro_publicacion(request):
    """Panel unificado: subir -> revisar -> aprobar -> publicar.

    2026-09-06: acotado al ciclo de formacion SELECCIONADO en el topbar
    (get_periodo_seleccionado -- la misma fuente de verdad que usan ya
    todas las demas vistas del app desde la Fase 3, ver periodo_utils.py).
    Antes esta pantalla mezclaba TODOS los periodos en sus contadores, Y
    el badge "Periodo: 2026-2" junto con el POST 'periodo' de los botones
    Aprobar/Publicar estaban HARDCODEADOS en el template sin importar el
    ciclo real activo -- si el usuario trabajaba en otro ciclo (ej.
    2026-3T, el que se estaba usando en el Motor IA), esta pantalla igual
    mandaba '2026-2' al aprobar/publicar, lo que fallaba silenciosamente
    en cualquier otro periodo. Ahora todo (contadores, muestra de
    horarios, aprobar, publicar) respeta el mismo periodo que el usuario
    tiene seleccionado arriba.
    """
    from .integracion_sisca_helpers import _cliente_disponible
    cfg = getattr(djsettings, 'SIIHAPI', {})
    cliente = get_cliente()
    sisca_conectado = cliente.ping()

    periodo_actual = get_periodo_seleccionado(request)
    periodo_cod = periodo_actual.codigo if periodo_actual else 'TODOS'

    horarios_qs = Horario.objects.all()
    if periodo_actual:
        horarios_qs = horarios_qs.filter(matricula__periodo=periodo_actual)

    propuestos = horarios_qs.filter(estado='PROPUESTO').count()
    aprobados = horarios_qs.filter(estado='APROBADO').count()
    publicados = horarios_qs.filter(estado='PUBLICADO').count()
    cancelados = horarios_qs.filter(estado='CANCELADO').count()

    # Tomar muestras (priorizando APROBADOS, luego PUBLICADOS, luego PROPUESTOS)
    base_qs = horarios_qs.select_related(
        'matricula', 'materia', 'docente__usuario', 'salon__sede', 'bloque'
    )
    horarios_aprobados = list(base_qs.filter(estado='APROBADO').order_by('dia', 'bloque__numero')[:30])
    if not horarios_aprobados:
        # Si no hay aprobados, muestra publicados o propuestos
        horarios_aprobados = list(base_qs.exclude(estado='CANCELADO').order_by('-estado', 'dia', 'bloque__numero')[:30])

    ultima_pub = (IntegracionLog.objects
                  .filter(operacion='PUBLICAR_HORARIOS', estado='EXITO')
                  .order_by('-fecha').first())
    ultimos_logs = IntegracionLog.objects.order_by('-fecha')[:10]

    return render(request, 'dashboard/centro_publicacion.html', {
        'sisca_url': cfg.get('SISCA_API_URL', 'http://localhost:8080'),
        'sisca_conectado': sisca_conectado,
        'periodo_cod': periodo_cod,
        'kpis': {
            'propuestos':  propuestos,
            'aprobados':   aprobados,
            'publicados':  publicados,
            'cancelados':  cancelados,
            'total':       horarios_qs.count(),
        },
        'horarios_aprobados': horarios_aprobados,
        'ultima_publicacion': ultima_pub,
        'ultimos_logs': ultimos_logs,
        'puede_aprobar':   propuestos > 0,
        'puede_publicar':  aprobados > 0 and sisca_conectado,
    })


@login_required
def horario_detalle(request, id_horario):
    """Detalle completo de un horario."""
    try:
        h = Horario.objects.select_related(
            'matricula__estudiante__usuario', 'matricula__periodo',
            'materia__programa__facultad',
            'docente__usuario',
            'salon__sede',
            'bloque'
        ).get(id_horario=id_horario)
    except Horario.DoesNotExist:
        messages.error(request, 'Horario no encontrado')
        return redirect('horarios')

    # Si es estudiante o docente, solo puede ver SU horario
    user = request.user
    if user.rol_efectivo == 'DOCENTE':
        docente = Docente.objects.filter(usuario=user).first()
        if not docente or h.docente_id != docente.usuario_id:
            messages.error(request, 'No tienes acceso a este horario')
            return redirect('docente_mi_horario')
    elif user.rol_efectivo == 'ESTUDIANTE':
        est = Estudiante.objects.filter(usuario=user).first()
        if not est or h.matricula.estudiante_id != est.usuario_id:
            messages.error(request, 'No tienes acceso a este horario')
            return redirect('estudiante_mi_horario')

    # Otros horarios del docente esa semana
    otros_docente = Horario.objects.filter(
        docente=h.docente
    ).exclude(id_horario=h.id_horario).select_related('materia', 'salon', 'bloque').order_by('dia', 'bloque__numero')[:10]

    # Otros horarios del salon
    otros_salon = Horario.objects.filter(
        salon=h.salon
    ).exclude(id_horario=h.id_horario).select_related('materia', 'docente__usuario', 'bloque').order_by('dia', 'bloque__numero')[:10]

    # Equipamiento del salon
    equipamiento = h.salon.equipamiento.all()

    return render(request, 'dashboard/horario_detalle.html', {
        'horario':        h,
        'otros_docente':  otros_docente,
        'otros_salon':    otros_salon,
        'equipamiento':   equipamiento,
    })


def _construir_pdf_politecnico_siihapi(horarios, titular=None, periodo_fechas='28/04/2026 - 04/07/2026'):
    """
    Genera un PDF estilo Politécnico Internacional con la lista de horarios.

    horarios: queryset/list de objetos Horario con select_related cargado
    titular: dict opcional con: nombre, doc_ident, periodo, centro, plan
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
                               fontSize=9, alignment=TA_LEFT)
    s_foot_r = ParagraphStyle('fr', parent=styles['Normal'], fontName='Helvetica-Oblique',
                               fontSize=9, alignment=TA_RIGHT)
    story = []

    # ─── Encabezado institucional ───
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

    # ─── Datos del titular ───
    if titular:
        info = Table([
            [Paragraph('<b>Nombre y apellidos</b>', s_label), Paragraph(titular.get('nombre','') , s_val),
             Paragraph('<b>Doc. Ident.</b>', s_label), Paragraph(titular.get('doc_ident',''), s_val)],
            [Paragraph('<b>Curso Académico</b>', s_label), Paragraph(titular.get('periodo',''), s_val),
             Paragraph('<b>Centro</b>', s_label), Paragraph(titular.get('centro',''), s_val)],
            [Paragraph('<b>Plan</b>', s_label), Paragraph(titular.get('plan',''), s_val), '', ''],
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

    # ─── Periodo de fechas ───
    fechas_tbl = Table([[Paragraph(f'<b>{periodo_fechas}</b>', s_th)]],
                        colWidths=[27*cm], rowHeights=[0.55*cm])
    fechas_tbl.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(fechas_tbl)

    # ─── Tabla principal ───
    headers = ['Dias', 'Asignatura', 'Grupo', 'Profesor', 'Aula', 'Franja Horaria']
    orden_dias = ['LU','MA','MI','JU','VI','SA','DO',
                  'LUNES','MARTES','MIERCOLES','MIÉRCOLES','JUEVES','VIERNES','SABADO','SÁBADO','DOMINGO']
    nombre_dia = {
        'LU':'LUNES','MA':'MARTES','MI':'MIÉRCOLES','JU':'JUEVES','VI':'VIERNES','SA':'SÁBADO','DO':'DOMINGO',
        'LUNES':'LUNES','MARTES':'MARTES','MIERCOLES':'MIÉRCOLES','JUEVES':'JUEVES','VIERNES':'VIERNES','SABADO':'SÁBADO',
    }
    def _key(h):
        d = getattr(h, 'dia', '') or ''
        try: idx = orden_dias.index(d.upper())
        except ValueError: idx = 99
        try: numero = h.bloque.numero if getattr(h,'bloque',None) else 0
        except Exception: numero = 0
        return (idx, numero)
    horarios_ord = sorted(list(horarios), key=_key)

    data = [[Paragraph(f'<b>{h}</b>', s_th) for h in headers]]
    span_groups = []
    row_idx = 1
    dia_actual = None
    fila_inicio_dia = None

    for h in horarios_ord:
        dia_raw = (getattr(h,'dia','') or '').upper()
        dia_display = nombre_dia.get(dia_raw, dia_raw or '—')

        # Materia
        try:
            codigo = h.materia.codigo
            nombre_mat = h.materia.nombre
        except Exception:
            codigo, nombre_mat = '—', '—'
        asignatura = f"[{codigo}] {nombre_mat}"

        # Grupo (basado en programa/codigo)
        try:
            grupo_cod = h.materia.programa.codigo if h.materia.programa else 'GRP'
        except Exception:
            grupo_cod = 'GRP'
        grupo = f"1 ({grupo_cod})"

        # Profesor
        try:
            profesor = (h.docente.usuario.nombre_completo or '').upper() if h.docente else '—'
        except Exception:
            profesor = '—'

        # Aula
        try:
            if h.salon and h.salon.nombre:
                sede = h.salon.sede.nombre if h.salon.sede else ''
                aula_full = f"{h.salon.nombre.upper()} ({sede.upper()}) -"
            else:
                aula_full = "ASIGNATURA ASISTIDA POR TECNOLOGIA CON ENCUENTROS SINCRONICOS (CAMPUS) -"
        except Exception:
            aula_full = "—"

        # Franja
        try:
            hi = h.bloque.hora_inicio.strftime('%H:%M')
            hf = h.bloque.hora_fin.strftime('%H:%M')
            franja = f"{hi}  -  {hf}"
        except Exception:
            franja = "--:--  -  --:--"

        # El dia se muestra solo en la primera fila de cada grupo para mantener
        # la lectura limpia; pero como no hay SPAN, si el grupo cruza un salto de
        # pagina se vuelve a imprimir en la primera fila visible de la pagina.
        if dia_actual != dia_raw:
            dia_actual = dia_raw
            celda_dia = Paragraph(f'<b>{dia_display}</b>', s_dia)
        else:
            celda_dia = Paragraph(f'<font color="#94A3B8">{dia_display}</font>', s_dia)

        data.append([
            celda_dia,
            Paragraph(asignatura, s_td),
            Paragraph(grupo, s_td),
            Paragraph(profesor, s_td),
            Paragraph(aula_full, s_td),
            Paragraph(franja, s_td),
        ])
        row_idx += 1

    if len(data) == 1:
        data.append([Paragraph('—', s_td)] * 6)

    # Anchos reducidos para caber en el marco de A4 apaisado (suma = 25.3 cm,
    # el marco util ronda 26.5 cm tras margenes; deja holgura y evita overflow).
    col_widths = [2.0*cm, 7.0*cm, 2.8*cm, 4.7*cm, 6.0*cm, 2.8*cm]
    tabla = Table(data, colWidths=col_widths, repeatRows=1)
    estilo = [
        ('BACKGROUND', (0,0), (-1,0), AZUL_CLARO),
        ('LINEBELOW', (0,0), (-1,0), 0.7, AZUL),
        ('LINEABOVE', (0,0), (-1,0), 0.7, GRIS_BORDE),
        ('GRID', (0,1), (-1,-1), 0.4, GRIS_BORDE),
        ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,1), (0,-1), colors.white),
    ]
    # NOTA: no se usa SPAN en la columna de dias. Un SPAN que agrupa muchas filas
    # genera una celda mas alta que la pagina y ReportLab no puede partirla
    # ("too large on page 2"). En su lugar el dia se repite/marca por fila, lo que
    # permite que la tabla se divida correctamente en multiples paginas.
    tabla.setStyle(TableStyle(estilo))
    story.append(tabla)

    # ─── Footer: numero de pagina real dibujado en cada pagina ───
    def _pie_pagina(canvas, documento):
        canvas.saveState()
        canvas.setFont('Helvetica-Oblique', 9)
        # Linea separadora
        ancho, _alto = landscape(A4)
        y = 0.7*cm
        canvas.setStrokeColor(colors.HexColor('#9CA3AF'))
        canvas.line(documento.leftMargin, y + 0.35*cm,
                    ancho - documento.rightMargin, y + 0.35*cm)
        canvas.setFillColor(colors.black)
        canvas.drawString(documento.leftMargin, y, 'Leyenda de abreviaturas.')
        canvas.drawRightString(ancho - documento.rightMargin, y,
                               f'Pag. {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_pie_pagina, onLaterPages=_pie_pagina)
    buf.seek(0)
    return buf.read()


def _titular_desde_request_siihapi(request, horario_ref=None):
    """Construye dict titular para el PDF."""
    u = request.user
    nombre = (getattr(u, 'nombre_completo', None) or f"{u.nombre} {u.apellido}").upper()
    # Para estudiantes: usar código + programa, si no, usar el del horario
    doc_id = ''
    plan = ''
    centro = 'SEDE CALLE 73'
    try:
        if u.rol_efectivo == 'ESTUDIANTE':
            from .models import Estudiante
            est = Estudiante.objects.select_related('programa').filter(usuario=u).first()
            if est:
                doc_id = str(est.codigo)
                plan = est.programa.nombre if est.programa else ''
        else:
            doc_id = str(u.id_usuario)
    except Exception:
        doc_id = str(getattr(u, 'id_usuario', ''))
    if not plan and horario_ref is not None:
        try:
            plan = horario_ref.materia.programa.nombre
        except Exception:
            pass
    try:
        if horario_ref and horario_ref.salon and horario_ref.salon.sede:
            centro = horario_ref.salon.sede.nombre
    except Exception:
        pass
    return {
        'nombre':    nombre.strip() or 'USUARIO SIIHAPI',
        'doc_ident': doc_id or '—',
        'periodo':   '2026-2T',
        'centro':    centro,
        'plan':      plan or 'TECNOLOGIA EN DESARROLLO DE SOFTWARE Y APLICATIVOS MOVILES SEDE CALLE 73',
    }


@login_required
def horario_exportar_pdf(request, id_horario):
    """Exporta UN horario en formato Politécnico Internacional."""
    from django.http import HttpResponse

    try:
        h = Horario.objects.select_related(
            'matricula__estudiante__usuario', 'matricula__periodo',
            'materia__programa__facultad', 'docente__usuario',
            'salon__sede', 'bloque'
        ).get(id_horario=id_horario)
    except Horario.DoesNotExist:
        messages.error(request, 'Horario no encontrado')
        return redirect('horarios')

    try:
        titular = _titular_desde_request_siihapi(request, horario_ref=h)
        pdf_bytes = _construir_pdf_politecnico_siihapi([h], titular=titular)
    except ImportError:
        messages.error(request, 'Falta libreria reportlab. Instala: pip install reportlab')
        return redirect('horario_detalle', id_horario=id_horario)
    except Exception as e:
        import logging
        logging.exception('PDF politecnico error')
        messages.error(request, f'Error generando PDF: {e}')
        return redirect('horario_detalle', id_horario=id_horario)

    filename = f"horario_{h.materia.codigo}_{h.get_dia_display()}.pdf"
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@login_required
def horarios_exportar_pdf_completo(request):
    """Exporta TODOS los horarios (con filtros opcionales) en formato Politécnico."""
    from django.http import HttpResponse
    from .models import Facultad, Programa

    qs = Horario.objects.select_related(
        'matricula__estudiante__usuario', 'matricula__periodo',
        'materia__programa__facultad', 'docente__usuario',
        'salon__sede', 'bloque'
    )

    # Filtros (mismos del panel: estado, dia, jornada, materia, docente,
    # estudiante (q), ciclo, carrera) para que la descarga respete lo filtrado.
    qs, _filtros = _aplicar_filtros_horarios(qs, request)
    # compatibilidad con el parametro antiguo 'codigo'
    codigo = (request.GET.get('codigo') or '').strip()
    if codigo:
        qs = qs.filter(materia__codigo__icontains=codigo)

    # ── Filtros por CATEGORÍA ──
    facultad_id  = (request.GET.get('facultad_id') or '').strip()
    programa_id  = (request.GET.get('programa_id') or '').strip()
    ciclo_cat    = (request.GET.get('ciclo_cat') or '').strip()
    modalidad    = (request.GET.get('modalidad') or '').strip().upper()

    titulo_partes = []

    if facultad_id:
        try:
            fac = Facultad.objects.get(pk=int(facultad_id))
            qs = qs.filter(materia__programa__facultad=fac)
            titulo_partes.append(fac.nombre)
        except (Facultad.DoesNotExist, ValueError):
            pass
    if programa_id:
        try:
            prog = Programa.objects.get(pk=int(programa_id))
            qs = qs.filter(materia__programa=prog)
            titulo_partes.append(prog.nombre)
        except (Programa.DoesNotExist, ValueError):
            pass
    if ciclo_cat:
        try:
            qs = qs.filter(materia__ciclo=int(ciclo_cat))
            titulo_partes.append(f'Ciclo {ciclo_cat}')
        except ValueError:
            pass
    if modalidad:
        qs = qs.filter(materia__programa__modalidad=modalidad)
        _MOD = {'PRES': 'Presencial', 'VIRT': 'Virtual', 'HIB': 'Híbrida'}
        titulo_partes.append(_MOD.get(modalidad, modalidad))
    # Jornada (ya aplicada por _aplicar_filtros_horarios) reflejada en el título
    _jorn = _filtros.get('jornada')
    if _jorn in JORNADAS:
        titulo_partes.append(JORNADAS[_jorn]['label'].split('(')[0].strip())

    # Si es estudiante, filtrar solo sus matrículas
    try:
        if request.user.rol_efectivo == 'ESTUDIANTE':
            from .models import Estudiante
            est = Estudiante.objects.filter(usuario=request.user).first()
            if est:
                qs = qs.filter(matricula__estudiante=est)
        elif request.user.rol_efectivo == 'DOCENTE':
            from .models import Docente
            doc = Docente.objects.filter(usuario=request.user).first()
            if doc:
                qs = qs.filter(docente=doc)
    except Exception:
        pass

    horarios_list = list(qs[:500])

    # Tomar el primero como referencia para titular
    h_ref = horarios_list[0] if horarios_list else None

    try:
        titular = _titular_desde_request_siihapi(request, horario_ref=h_ref)
        # Sobreescribir el campo 'plan' con la categoría seleccionada
        if titulo_partes:
            titular['plan'] = ' · '.join(titulo_partes)
        pdf_bytes = _construir_pdf_politecnico_siihapi(horarios_list, titular=titular)
    except ImportError:
        messages.error(request, 'Falta libreria reportlab. Instala: pip install reportlab')
        return redirect('horarios')
    except Exception as e:
        import logging
        logging.exception('PDF completo error')
        messages.error(request, f'Error generando PDF: {e}')
        return redirect('horarios')

    # Nombre de archivo descriptivo según categoría
    slug_parts = [p.replace(' ', '_')[:20] for p in titulo_partes] if titulo_partes else ['completo']
    filename = 'horario_' + '_'.join(slug_parts) + '.pdf'
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def _filtrar_horarios_categoria(request):
    """Aplica TODOS los filtros (panel + categoría: facultad/programa/ciclo/
    modalidad/jornada) y devuelve (queryset, lista de partes del título)."""
    qs = Horario.objects.select_related(
        'matricula__estudiante__usuario', 'matricula__periodo',
        'materia__programa__facultad', 'docente__usuario',
        'salon__sede', 'bloque')
    qs, _filtros = _aplicar_filtros_horarios(qs, request)

    facultad_id = (request.GET.get('facultad_id') or '').strip()
    programa_id = (request.GET.get('programa_id') or '').strip()
    ciclo_cat   = (request.GET.get('ciclo_cat') or '').strip()
    modalidad   = (request.GET.get('modalidad') or '').strip().upper()
    partes = []

    if facultad_id:
        fac = Facultad.objects.filter(pk=facultad_id).first()
        if fac:
            qs = qs.filter(materia__programa__facultad=fac)
            partes.append(fac.nombre)
    if programa_id:
        prog = Programa.objects.filter(pk=programa_id).first()
        if prog:
            qs = qs.filter(materia__programa=prog)
            partes.append(prog.nombre)
    if ciclo_cat:
        try:
            qs = qs.filter(materia__ciclo=int(ciclo_cat))
            partes.append(f'Ciclo {ciclo_cat}')
        except ValueError:
            pass
    if modalidad:
        qs = qs.filter(materia__programa__modalidad=modalidad)
        _MOD = {'PRES': 'Presencial', 'VIRT': 'Virtual', 'HIB': 'Híbrida'}
        partes.append(_MOD.get(modalidad, modalidad))
    _jorn = _filtros.get('jornada')
    if _jorn in JORNADAS:
        partes.append(JORNADAS[_jorn]['label'].split('(')[0].strip())

    # Restringir por rol (estudiante ve solo lo suyo; docente lo suyo)
    try:
        if request.user.rol_efectivo == 'ESTUDIANTE':
            est = Estudiante.objects.filter(usuario=request.user).first()
            if est:
                qs = qs.filter(matricula__estudiante=est)
        elif request.user.rol_efectivo == 'DOCENTE':
            doc = Docente.objects.filter(usuario=request.user).first()
            if doc:
                qs = qs.filter(docente=doc)
    except Exception:
        pass
    return qs, partes


@login_required
def horarios_exportar_excel_completo(request):
    """Exporta los horarios filtrados a Excel (.xlsx) — para enviar a estudiantes."""
    from io import BytesIO
    from django.http import HttpResponse

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        messages.error(request, 'Falta la librería openpyxl. Instala: pip install openpyxl')
        return redirect('reportes_categoria')

    qs, partes = _filtrar_horarios_categoria(request)

    _DIA = {'LU': 'Lunes', 'MA': 'Martes', 'MI': 'Miércoles', 'JU': 'Jueves',
            'VI': 'Viernes', 'SA': 'Sábado', 'DO': 'Domingo'}
    _MOD = {'PRES': 'Presencial', 'VIRT': 'Virtual', 'HIB': 'Híbrida'}
    _orden = {'LU': 0, 'MA': 1, 'MI': 2, 'JU': 3, 'VI': 4, 'SA': 5, 'DO': 6}

    horarios = sorted(
        list(qs[:3000]),
        key=lambda h: (_orden.get(h.dia, 9),
                       getattr(h.bloque, 'numero', 0) if h.bloque_id else 0))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Horario'

    AZUL = 'FF1F4988'
    titulo = 'Horario — ' + (' · '.join(partes) if partes else 'Politécnico Internacional')
    ws.merge_cells('A1:M1')
    c = ws['A1']
    c.value = titulo
    c.font = Font(bold=True, size=14, color='FFFFFFFF')
    c.fill = PatternFill('solid', fgColor=AZUL)
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 26

    encabezados = ['Día', 'Bloque', 'Hora', 'Asignatura', 'Código', 'Ciclo',
                   'Programa', 'Modalidad', 'Docente', 'Salón', 'Sede',
                   'Grupo / Estudiante', 'Estado']
    ws.append(encabezados)
    thin = Side(style='thin', color='FFB0B0B0')
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col, _ in enumerate(encabezados, start=1):
        cell = ws.cell(row=2, column=col)
        cell.font = Font(bold=True, color='FFFFFFFF')
        cell.fill = PatternFill('solid', fgColor='FF2C5BA0')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = borde

    for h in horarios:
        hora = ''
        if h.bloque_id and h.bloque:
            try:
                hora = f'{h.bloque.hora_inicio:%H:%M} - {h.bloque.hora_fin:%H:%M}'
            except Exception:
                hora = ''
        prog = getattr(getattr(h.materia, 'programa', None), 'nombre', '') if h.materia_id else ''
        mod_cod = getattr(getattr(h.materia, 'programa', None), 'modalidad', '') if h.materia_id else ''
        docente = ''
        if h.docente_id and h.docente and h.docente.usuario_id:
            docente = h.docente.usuario.nombre_completo
        salon = h.salon.codigo if h.salon_id else ''
        sede = h.salon.sede.nombre if (h.salon_id and h.salon.sede_id) else ''
        grupo = ''
        if h.matricula_id and h.matricula and h.matricula.estudiante_id:
            est = h.matricula.estudiante
            grupo = est.usuario.nombre_completo if est.usuario_id else (est.codigo or '')
        ws.append([
            _DIA.get(h.dia, h.dia), getattr(h.bloque, 'numero', '') if h.bloque_id else '',
            hora, h.materia.nombre if h.materia_id else '',
            h.materia.codigo if h.materia_id else '',
            h.materia.ciclo if h.materia_id else '',
            prog, _MOD.get(mod_cod, mod_cod), docente, salon, sede, grupo,
            h.get_estado_display() if hasattr(h, 'get_estado_display') else h.estado,
        ])

    anchos = [11, 7, 15, 34, 10, 7, 30, 12, 26, 12, 14, 28, 12]
    for i, w in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(encabezados)):
        for cell in row:
            cell.border = borde
            if cell.row > 2:
                cell.alignment = Alignment(vertical='center', wrap_text=True)
    ws.freeze_panes = 'A3'

    bio = BytesIO()
    wb.save(bio)
    slug = '_'.join(p.replace(' ', '_')[:20] for p in partes) if partes else 'completo'
    resp = HttpResponse(
        bio.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="horario_{slug}.xlsx"'
    return resp



@login_required
def _horario_exportar_pdf_legacy(request, id_horario):
    """Versión anterior preservada (no se usa)."""
    from django.http import HttpResponse
    from io import BytesIO

    try:
        h = Horario.objects.select_related(
            'matricula__estudiante__usuario', 'matricula__periodo',
            'materia__programa__facultad', 'docente__usuario',
            'salon__sede', 'bloque'
        ).get(id_horario=id_horario)
    except Horario.DoesNotExist:
        messages.error(request, 'Horario no encontrado')
        return redirect('horarios')

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        )
        from reportlab.lib.enums import TA_CENTER
    except ImportError:
        messages.error(request, 'Falta libreria reportlab. Instala: pip install reportlab')
        return redirect('horario_detalle', id_horario=id_horario)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=2*cm, rightMargin=2*cm,
                             topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    AZUL = colors.HexColor('#1F6FEB')

    title_style = ParagraphStyle('title', parent=styles['Heading1'],
                                   fontSize=22, textColor=AZUL,
                                   alignment=TA_CENTER, spaceAfter=14)
    sub_style = ParagraphStyle('sub', parent=styles['Heading2'],
                                  fontSize=14, textColor=AZUL, spaceAfter=10)
    centro = ParagraphStyle('centro', parent=styles['Normal'],
                              alignment=TA_CENTER, fontSize=11, textColor=colors.grey)

    story = []

    # Portada / encabezado
    story.append(Paragraph('SIIHAPI', title_style))
    story.append(Paragraph('Detalle de Horario Académico', title_style))
    story.append(Paragraph('Politécnico Internacional', centro))
    story.append(Spacer(1, 0.8*cm))

    # ── Materia ──
    story.append(Paragraph('1. Información de la Materia', sub_style))
    tabla_mat = [
        ['Código', h.materia.codigo],
        ['Nombre', h.materia.nombre],
        ['Programa', f'{h.materia.programa.codigo} — {h.materia.programa.nombre}'],
        ['Facultad', h.materia.programa.facultad.nombre],
        ['Ciclo', str(h.materia.ciclo)],
        ['Créditos', str(h.materia.creditos)],
        ['Horas/semana', str(h.materia.horas_semanales)],
    ]
    t = Table(tabla_mat, colWidths=[5*cm, 12*cm])
    t.setStyle(_estilo_tabla_detalle(AZUL))
    story.append(t)
    story.append(Spacer(1, 0.6*cm))

    # ── Horario ──
    story.append(Paragraph('2. Día y Hora', sub_style))
    tabla_horario = [
        ['Día', h.get_dia_display()],
        ['Bloque', f'B{h.bloque.numero}'],
        ['Hora de inicio', h.bloque.hora_inicio.strftime('%H:%M')],
        ['Hora de fin', h.bloque.hora_fin.strftime('%H:%M')],
        ['Estado', h.get_estado_display()],
        ['Periodo', h.matricula.periodo.codigo],
    ]
    t = Table(tabla_horario, colWidths=[5*cm, 12*cm])
    t.setStyle(_estilo_tabla_detalle(AZUL))
    story.append(t)
    story.append(Spacer(1, 0.6*cm))

    # ── Docente ──
    story.append(Paragraph('3. Docente Asignado', sub_style))
    tabla_doc = [
        ['Nombre completo', h.docente.usuario.nombre_completo],
        ['Correo', h.docente.usuario.correo],
        ['Tipo de contrato', h.docente.get_tipo_contrato_display()],
        ['Carga máxima', f'{h.docente.carga_horaria_max} horas/semana'],
    ]
    t = Table(tabla_doc, colWidths=[5*cm, 12*cm])
    t.setStyle(_estilo_tabla_detalle(AZUL))
    story.append(t)
    story.append(Spacer(1, 0.6*cm))

    # ── Salón ──
    story.append(Paragraph('4. Salón / Aula', sub_style))
    tabla_salon = [
        ['Código', h.salon.codigo],
        ['Nombre', h.salon.nombre],
        ['Sede', h.salon.sede.nombre],
        ['Dirección sede', h.salon.sede.direccion],
        ['Planta / Piso', h.salon.planta],
        ['Capacidad', f'{h.salon.capacidad} estudiantes'],
        ['Tipo', h.salon.get_tipo_display()],
    ]
    t = Table(tabla_salon, colWidths=[5*cm, 12*cm])
    t.setStyle(_estilo_tabla_detalle(AZUL))
    story.append(t)
    story.append(Spacer(1, 0.6*cm))

    # ── Estudiante (solo si rol estudiante o admin/coord) ──
    if request.user.rol_efectivo in ('ADMINISTRADOR', 'COORDINADOR', 'ESTUDIANTE'):
        story.append(Paragraph('5. Estudiante', sub_style))
        est = h.matricula.estudiante
        tabla_est = [
            ['Código', est.codigo],
            ['Nombre', est.usuario.nombre_completo],
            ['Correo', est.usuario.correo],
            ['Programa', est.programa.nombre],
            ['Semestre actual', str(est.semestre_actual)],
        ]
        t = Table(tabla_est, colWidths=[5*cm, 12*cm])
        t.setStyle(_estilo_tabla_detalle(AZUL))
        story.append(t)
        story.append(Spacer(1, 0.6*cm))

    # ── ID SISCA si está publicado ──
    if h.estado == 'PUBLICADO' and h.id_sisca:
        story.append(Paragraph('6. Integración SISCA', sub_style))
        tabla_sisca = [
            ['ID en SISCA', h.id_sisca],
            ['Publicado el', h.publicado_sisca_fecha.strftime('%d/%m/%Y %H:%M:%S') if h.publicado_sisca_fecha else '—'],
            ['Estado', 'Activo en SISCA'],
        ]
        t = Table(tabla_sisca, colWidths=[5*cm, 12*cm])
        t.setStyle(_estilo_tabla_detalle(AZUL))
        story.append(t)

    # Pie de página
    from datetime import datetime
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        f'Generado el {datetime.now().strftime("%d/%m/%Y a las %H:%M:%S")} · SIIHAPI v1.0',
        centro
    ))

    doc.build(story)
    buf.seek(0)

    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="horario_{h.materia.codigo}_{h.get_dia_display()}_B{h.bloque.numero}.pdf"'
    return resp


def _estilo_tabla_detalle(color_primario):
    from reportlab.platypus import TableStyle
    from reportlab.lib import colors
    return TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0F4FB')),
        ('TEXTCOLOR', (0, 0), (0, -1), color_primario),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ])


@operacion_required
def horarios_gestionar(request):
    """Vista de edicion inline de horarios asignados."""
    estado_filtro = request.GET.get('estado', '')
    docente_filtro = request.GET.get('docente', '')
    dia_filtro = request.GET.get('dia', '')

    qs = Horario.objects.select_related(
        'matricula__estudiante__usuario', 'materia__programa',
        'docente__usuario', 'salon__sede', 'bloque'
    )
    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)
    if docente_filtro:
        qs = qs.filter(docente__usuario_id=docente_filtro)
    if dia_filtro:
        qs = qs.filter(dia=dia_filtro)

    horarios = qs.order_by('dia', 'bloque__numero', 'docente__usuario__apellido')[:300]

    return render(request, 'dashboard/horarios_gestionar.html', {
        'horarios':       horarios,
        'estados':        Horario.ESTADO_CHOICES,
        'dias':           Horario.DIA_CHOICES,
        'estado_filtro':  estado_filtro,
        'docente_filtro': docente_filtro,
        'dia_filtro':     dia_filtro,
        'docentes':       Docente.objects.filter(activo=True).select_related('usuario')[:200],
        'salones':        Salon.objects.filter(activo=True).select_related('sede')[:300],
        'bloques':        Bloque.objects.order_by('numero'),
        'materias':       Materia.objects.filter(activa=True)[:300],
        'total':          Horario.objects.count(),
    })


@operacion_required
@require_http_methods(["POST"])
def horario_actualizar(request, id_horario):
    """API JSON para editar un horario."""
    try:
        h = Horario.objects.get(id_horario=id_horario)
    except Horario.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Horario no existe'}, status=404)

    cambios = {}
    if 'docente' in request.POST:
        try:
            h.docente = Docente.objects.get(usuario_id=request.POST['docente'])
            cambios['docente'] = h.docente.usuario.nombre_completo
        except Docente.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Docente invalido'}, status=400)
    if 'salon' in request.POST:
        try:
            h.salon = Salon.objects.get(id_salon=request.POST['salon'])
            cambios['salon'] = h.salon.codigo
        except Salon.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Salon invalido'}, status=400)
    if 'bloque' in request.POST:
        try:
            h.bloque = Bloque.objects.get(numero=request.POST['bloque'])
            cambios['bloque'] = h.bloque.numero
        except Bloque.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Bloque invalido'}, status=400)
    if 'dia' in request.POST:
        if request.POST['dia'] not in dict(Horario.DIA_CHOICES):
            return JsonResponse({'success': False, 'error': 'Dia invalido'}, status=400)
        h.dia = request.POST['dia']
        cambios['dia'] = h.dia
    if 'estado' in request.POST:
        if request.POST['estado'] not in dict(Horario.ESTADO_CHOICES):
            return JsonResponse({'success': False, 'error': 'Estado invalido'}, status=400)
        h.estado = request.POST['estado']
        cambios['estado'] = h.estado

    # Verificar choque despues del cambio -- mismas 3 dimensiones que el
    # Motor IA (ocupado_doc/ocupado_sal/ocupado_mat en motor_ia/solver.py):
    # docente, salon y matricula/estudiante (Sprint 1, RF 1.2, 2026-09-06).
    choque = Horario.objects.exclude(id_horario=h.id_horario).filter(
        dia=h.dia, bloque=h.bloque
    ).filter(Q(docente=h.docente) | Q(salon=h.salon) | Q(matricula=h.matricula))
    if choque.exists():
        primer = choque.first()
        if primer.matricula_id == h.matricula_id:
            detalle = f'el estudiante {h.matricula.estudiante.usuario.nombre_completo} ya tiene otra clase'
        elif primer.docente_id == h.docente_id:
            detalle = f'el docente {primer.docente.usuario.nombre_completo} ya tiene clase'
        else:
            detalle = f'el salón {primer.salon.codigo} ya está ocupado'
        return JsonResponse({
            'success': False,
            'error': f'Conflicto: {detalle} en {h.get_dia_display()} bloque {h.bloque.numero}',
        }, status=400)

    h.save()
    return JsonResponse({
        'success': True,
        'mensaje': f'Horario {h.id_horario} actualizado',
        'cambios': cambios,
    })


@operacion_required
@require_http_methods(["POST"])
def horario_eliminar(request, id_horario):
    """API JSON para eliminar un horario."""
    try:
        h = Horario.objects.get(id_horario=id_horario)
        info = f'{h.materia.codigo} · {h.get_dia_display()} B{h.bloque.numero}'
        h.delete()
        return JsonResponse({'success': True, 'mensaje': f'Eliminado: {info}'})
    except Horario.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'No existe'}, status=404)


@operacion_required
@require_http_methods(["POST"])
def aprobar_horarios(request):
    """RF-33 - El COORDINADOR aprueba todos los horarios PROPUESTOS del periodo."""
    periodo_cod = request.POST.get('periodo', '2026-2')
    ui = request.POST.get('ui')  # si viene de un formulario de la interfaz
    destino = request.META.get('HTTP_REFERER') or '/dashboard/horarios/'
    try:
        periodo = Periodo.objects.get(codigo=periodo_cod)
    except Periodo.DoesNotExist:
        if ui:
            messages.error(request, f'El periodo {periodo_cod} no existe.')
            return redirect(destino)
        return JsonResponse({'success': False, 'error': 'Periodo no existe'}, status=400)
    qs = Horario.objects.filter(matricula__periodo=periodo, estado='PROPUESTO')
    n = qs.update(estado='APROBADO')
    msg = f'{n} horario(s) aprobados en {periodo_cod}. Listos para publicar a SISCA.'
    if ui:
        if n > 0:
            messages.success(request, '✅ ' + msg)
        else:
            messages.info(request, 'No había horarios propuestos pendientes de aprobar.')
        return redirect(destino)
    return JsonResponse({'success': True, 'aprobados': n, 'mensaje': msg})


@bloquear_solo_consulta
def integracion_sisca(request):
    cfg = getattr(djsettings, 'SIIHAPI', {})
    return render(request, 'dashboard/integracion_sisca.html', {
        'sisca_url': cfg.get('SISCA_API_URL', 'http://localhost:8080'),
    })


@operacion_required
@require_http_methods(["POST"])
def sisca_publicar(request):
    """RF-40 - Publica horarios APROBADOS del periodo a SISCA.

    Si no hay APROBADOS pero hay PUBLICADOS, ofrece re-publicar.
    Parametro opcional 'republicar=true' para forzar re-envio de los publicados.
    """
    periodo_cod = request.POST.get('periodo', '2026-2')
    republicar = request.POST.get('republicar', '').lower() == 'true'

    try:
        periodo = Periodo.objects.get(codigo=periodo_cod)
    except Periodo.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Periodo no existe'}, status=400)

    # Estrategia inteligente: APROBADOS primero, si no hay y republicar=True usar PUBLICADOS
    estados_target = ['APROBADO']
    if republicar:
        estados_target.append('PUBLICADO')

    horarios = Horario.objects.filter(
        matricula__periodo=periodo, estado__in=estados_target
    ).select_related('matricula__estudiante__usuario', 'materia', 'docente__usuario', 'salon', 'bloque')

    # Filtro por JORNADA (opcional): publica por separado diurna/especial/nocturna/sabado.
    # Asi se evita mezclar jornadas o enviar sabado a estudiantes de L-V.
    jornada_pub = (request.POST.get('jornada') or '').strip().upper()
    _VENTANAS = {'DIURNA': ('07:00', '10:00'), 'ESPECIAL': ('10:00', '13:00'),
                 'NOCTURNA': ('18:00', '21:00')}
    from datetime import datetime as _dtp
    if jornada_pub == 'SABADO':
        horarios = horarios.filter(dia='SA')
    elif jornada_pub in _VENTANAS:
        ini, fin = _VENTANAS[jornada_pub]
        horarios = horarios.exclude(dia='SA').filter(
            bloque__hora_inicio__gte=_dtp.strptime(ini, '%H:%M').time(),
            bloque__hora_inicio__lt=_dtp.strptime(fin, '%H:%M').time())
    horarios = horarios[:500]

    # Si no hay aprobados pero SI hay publicados, informar y ofrecer re-publicar
    if not horarios.exists():
        publicados_existentes = Horario.objects.filter(
            matricula__periodo=periodo, estado='PUBLICADO'
        ).count()
        if publicados_existentes > 0 and not republicar:
            return JsonResponse({
                'success': False,
                'error': f'No hay horarios APROBADOS pendientes en {periodo_cod}. Ya tienes {publicados_existentes} publicados.',
                'sugerencia': 'Si quieres reenviar los publicados a SISCA, envia con republicar=true',
                'puede_republicar': True,
                'publicados_existentes': publicados_existentes,
            }, status=400)

        propuestos = Horario.objects.filter(
            matricula__periodo=periodo, estado='PROPUESTO'
        ).count()
        return JsonResponse({
            'success': False,
            'error': f'No hay horarios para publicar en {periodo_cod}.',
            'sugerencia': (f'Tienes {propuestos} PROPUESTOS sin aprobar. Aprueba primero.'
                          if propuestos > 0
                          else 'Ejecuta el Motor IA primero para generar horarios.'),
            'propuestos_pendientes': propuestos,
        }, status=400)

    payload = []
    for h in horarios:
        payload.append({
            'id_horario':      h.id_horario,
            'codigo_materia':  h.materia.codigo,
            'nombre_materia':  h.materia.nombre,
            'docente':         h.docente.usuario.nombre_completo,
            'docente_email':   h.docente.usuario.correo,
            'salon':           h.salon.codigo,
            'sede':            h.salon.sede.nombre,
            'dia':             h.dia,
            'bloque':          h.bloque.numero,
            'hora_inicio':     h.bloque.hora_inicio.strftime('%H:%M'),
            'hora_fin':        h.bloque.hora_fin.strftime('%H:%M'),
            'estudiante_correo': h.matricula.estudiante.usuario.correo,
        })

    cliente = get_cliente()
    try:
        resp = cliente.publicar_horarios(periodo_cod, payload)
        # Marcar como PUBLICADO y guardar id_sisca si vino
        sesiones = resp.get('sesiones', [])
        for i, h in enumerate(horarios):
            h.estado = 'PUBLICADO'
            h.publicado_sisca_fecha = timezone.now()
            if i < len(sesiones):
                h.id_sisca = sesiones[i]
            h.save(update_fields=['estado', 'publicado_sisca_fecha', 'id_sisca'])
        return JsonResponse({
            'success': True,
            'mensaje': f'{len(payload)} horarios publicados a SISCA',
            'total_publicados': len(payload),
            'sisca_respuesta': resp,
        })
    except ClienteSISCAError as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'sugerencia': 'Verifica que SISCA este corriendo en http://localhost:8080',
            'total_payload': len(payload),
        }, status=502)



@operacion_required
@require_http_methods(["POST"])
def sisca_publicar_ui(request):
    """Wrapper de sisca_publicar para formularios de la interfaz: ejecuta la
    publicacion y redirige de vuelta con un mensaje (en vez de mostrar JSON)."""
    import json as _json
    resp = sisca_publicar(request)
    destino = request.META.get('HTTP_REFERER') or '/dashboard/horarios/'
    try:
        data = _json.loads(resp.content.decode('utf-8'))
    except Exception:
        data = {}
    if data.get('success'):
        messages.success(request, '📡 ' + (data.get('mensaje') or 'Horarios publicados en SISCA.'))
    else:
        msg = data.get('error') or 'No se pudo publicar en SISCA.'
        if data.get('sugerencia'):
            msg += ' ' + data['sugerencia']
        messages.error(request, msg)
    return redirect(destino)

@bloquear_solo_consulta
def sisca_estado(request):
    """JSON con el estado actual de la integracion (consumido por JS)."""
    cliente = get_cliente()
    conectado = cliente.ping()
    ultima_pub = (IntegracionLog.objects
                  .filter(operacion='PUBLICAR_HORARIOS', estado='EXITO')
                  .order_by('-fecha').first())
    hace_24h = timezone.now() - timedelta(hours=24)
    logs_24h = IntegracionLog.objects.filter(fecha__gte=hace_24h)
    return JsonResponse({
        'conectado': conectado,
        'base_url': cliente.base_url,
        'ultima_publicacion': ultima_pub.fecha.isoformat() if ultima_pub else None,
        'logs_24h': {
            'total': logs_24h.count(),
            'exitos': logs_24h.filter(estado='EXITO').count(),
            'errores': logs_24h.filter(estado='ERROR').count(),
        },
        'total_logs': IntegracionLog.objects.count(),
        'horarios_aprobados': Horario.objects.filter(estado='APROBADO').count(),
        'horarios_publicados': Horario.objects.filter(estado='PUBLICADO').count(),
    })


@bloquear_solo_consulta
def sisca_logs(request):
    """JSON con los ultimos logs para la tabla del panel."""
    try:
        limit = int(request.GET.get('limit', 30))
        qs = IntegracionLog.objects.order_by('-fecha')[:limit]
        return JsonResponse({
            'logs': [{
                'id': l.id_log,
                'operacion': l.get_operacion_display(),
                'operacion_codigo': l.operacion,
                'estado': l.estado,
                'endpoint': l.endpoint or '',
                'codigo_http': l.codigo_http,
                'intentos': l.intentos,
                'duracion_ms': l.duracion_ms or 0,
                'error_msg': (l.error_msg or '')[:200],
                'fecha': l.fecha.isoformat() if l.fecha else '',
            } for l in qs]
        })
    except Exception as e:
        return JsonResponse({
            'logs': [],
            'error': f'Error cargando logs: {str(e)[:200]}'
        }, status=200)  # 200 para que el JS no truene


# ════════════════════════════════════════════════════════════════
#  Carga masiva CSV/Excel (RF-15, RF-20, RF-23, RF-25, RF-30)
# ════════════════════════════════════════════════════════════════

@operacion_required
def carga_masiva_view(request):
    """Pagina principal de carga masiva."""
    if request.method == 'POST':
        from . import cargas_masivas
        tipo = request.POST.get('tipo')
        archivo = request.FILES.get('archivo')

        if not tipo or tipo not in cargas_masivas.HANDLERS:
            messages.error(request, f'Tipo de carga invalido: {tipo}')
            return redirect('carga_masiva')

        if not archivo:
            messages.error(request, 'Debes subir un archivo CSV o XLSX')
            return redirect('carga_masiva')

        if archivo.size > 5 * 1024 * 1024:
            messages.error(request, 'Archivo demasiado grande (max 5 MB)')
            return redirect('carga_masiva')

        # ── Enrutamiento inteligente ──
        # Si es "horarios" pero el archivo trae formato Motor IA (codigo_materia/
        # hora_inicio y SIN matricula_id), lo procesamos con el pipeline de IA.
        if tipo == 'horarios':
            try:
                _raw = archivo.read()
                archivo.seek(0)
                _cab = _raw.decode('utf-8-sig', errors='replace').splitlines()
                _cab = (_cab[0].lower() if _cab else '')
                _es_ia = (('codigo_materia' in _cab or 'hora_inicio' in _cab)
                          and 'matricula_id' not in _cab)
            except Exception:
                _raw, _es_ia = None, False
            if _es_ia and _raw:
                from siihapi.motor_ia.pipeline import analizar_archivo_pipeline
                _per = get_periodo_seleccionado(request)
                _res = analizar_archivo_pipeline(
                    contenido=_raw, nombre_archivo=archivo.name,
                    periodo=_per.codigo if _per else '2026-2',
                    usuario_id=getattr(request.user, 'id_usuario', None) or request.user.pk,
                )
                if _res.get('horarios_creados', 0) > 0:
                    messages.success(
                        request,
                        f"🤖 Detecté formato Motor IA. La IA procesó tu archivo y creó "
                        f"{_res['horarios_creados']} horario(s) (confianza {_res.get('confianza', 0)}%). "
                        f"Abriendo el Panel Inteligente para revisar, editar, aprobar y publicar."
                    )
                    return redirect('revision_propuesta')
                messages.error(
                    request,
                    '⚠ Detecté formato Motor IA pero no se pudieron crear horarios: '
                    + (_res.get('error') or f"confianza {_res.get('confianza', 0)}% (mínimo 50%).")
                )
                for _e in (_res.get('errores_detalle') or [])[:8]:
                    messages.error(request, str(_e))
                return redirect('carga_masiva')

        try:
            resultado = cargas_masivas.HANDLERS[tipo](archivo)
            if resultado.get('tipo') == 'ERROR':
                for e in resultado['errores']:
                    messages.error(request, e)
            else:
                messages.success(request,
                    f"Carga '{tipo}': {resultado['creados']} creados, "
                    f"{resultado['actualizados']} actualizados, "
                    f"{len(resultado['errores'])} errores en {resultado['total_filas']} filas.")
                if resultado['errores']:
                    request.session['carga_errores'] = resultado['errores'][:50]
                # Guardar contexto para el chat IA
                request.session['carga_contexto'] = {
                    'tipo':         tipo,
                    'archivo':      archivo.name,
                    'total_filas':  resultado['total_filas'],
                    'creados':      resultado['creados'],
                    'actualizados': resultado['actualizados'],
                    'errores':      len(resultado['errores']),
                }
        except Exception as e:
            messages.error(request, f'Error procesando archivo: {str(e)[:300]}')

        # Si la carga de horarios fue exitosa y validada, abrir el panel inteligente
        # (revision_propuesta) donde se puede aprobar, editar y publicar.
        try:
            if (tipo == 'horarios'
                    and resultado.get('tipo') != 'ERROR'
                    and (resultado.get('creados', 0) > 0 or resultado.get('actualizados', 0) > 0)):
                messages.success(
                    request,
                    '✅ Carga validada. Abriendo el Panel Inteligente para revisar, '
                    'editar, aprobar y publicar los horarios.'
                )
                return redirect('revision_propuesta')
        except (UnboundLocalError, NameError):
            pass
        return redirect('carga_masiva')

    errores_previos = request.session.pop('carga_errores', [])
    contexto_carga = request.session.pop('carga_contexto', None)
    return render(request, 'dashboard/carga_masiva.html', {
        'errores_previos': errores_previos,
        'contexto_carga': contexto_carga,
    })


@operacion_required
def descargar_plantilla(request, tipo):
    """Descarga una plantilla CSV de ejemplo."""
    from . import cargas_masivas
    from django.http import HttpResponse

    contenido = cargas_masivas.plantilla_csv(tipo)
    if not contenido:
        messages.error(request, f'Tipo no valido: {tipo}')
        return redirect('carga_masiva')

    resp = HttpResponse(contenido, content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="plantilla_{tipo}.csv"'
    return resp


# ════════════════════════════════════════════════════════════════
#  5. ADMIN - Reportes y Auditoria
# ════════════════════════════════════════════════════════════════

@admin_required
def dashboard_ejecutivo(request):
    por_sede = Sede.objects.filter(estado='A').annotate(num_salones=Count('salones'))
    por_tipo_prog = {}
    for t, label in Programa.TIPO_CHOICES:
        por_tipo_prog[t] = {'label': label, 'programas': Programa.objects.filter(tipo=t, activo=True).count()}
    return render(request, 'dashboard/ejecutivo.html', {
        'por_sede': por_sede,
        'por_tipo_prog': por_tipo_prog,
        'ultimas_ia': AsignacionIA.objects.order_by('-fecha_inicio')[:5],
        'ultimos_logs': IntegracionLog.objects.order_by('-fecha')[:10],
        'totales': {
            'sedes': Sede.objects.filter(estado='A').count(),
            'salones': Salon.objects.filter(activo=True).count(),
            'programas': Programa.objects.filter(activo=True).count(),
            'docentes': Docente.objects.filter(activo=True).count(),
            'estudiantes': Estudiante.objects.filter(activo=True).count(),
            'matriculas': Matricula.objects.filter(estado='ACTIVA').count(),
            'horarios': Horario.objects.count(),
            'horarios_publicados': Horario.objects.filter(estado='PUBLICADO').count(),
            'usuarios': Usuario.objects.filter(is_active=True).count(),
        },
    })


@admin_required
def exportar_auditoria_view(request, formato):
    """RF-44 - Exporta la auditoria en formato xlsx, pdf, docx o pptx."""
    from . import exportar_auditoria as ea
    from django.http import HttpResponse

    formato = formato.lower()
    if formato not in ea.HANDLERS:
        messages.error(request, f'Formato no soportado: {formato}')
        return redirect('auditoria')

    handler, filename = ea.HANDLERS[formato]
    try:
        contenido, mime = handler()
    except ImportError as e:
        messages.error(request, f'Falta libreria para {formato.upper()}: {str(e)[:200]}. Instala con: pip install python-docx python-pptx reportlab openpyxl')
        return redirect('auditoria')
    except Exception as e:
        messages.error(request, f'Error generando {formato.upper()}: {str(e)[:300]}')
        return redirect('auditoria')

    resp = HttpResponse(contenido, content_type=mime)
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@admin_required
def auditoria_view(request):
    return render(request, 'dashboard/auditoria.html', {
        'intentos': IntentoLogin.objects.order_by('-fecha')[:100],
        'logs_sisca': IntegracionLog.objects.order_by('-fecha')[:50],
        'asignaciones': AsignacionIA.objects.order_by('-fecha_inicio')[:20],
        'stats': {
            'logins_exitosos': IntentoLogin.objects.filter(exitoso=True).count(),
            'logins_fallidos': IntentoLogin.objects.filter(exitoso=False).count(),
            'eventos_sisca': IntegracionLog.objects.count(),
            'ejecuciones_ia': AsignacionIA.objects.count(),
        },
        'facultades': Facultad.objects.filter(activa=True).order_by('nombre'),
        'programas': (Programa.objects.filter(activo=True)
                      .select_related('facultad').order_by('nombre')),
    })


# ════════════════════════════════════════════════════════════════
#  6b. REPORTES POR CATEGORÍA (facultad · programa · ciclo)
# ════════════════════════════════════════════════════════════════

def _resumen_horarios_por_categoria(facultad_id=None, programa_id=None):
    """Devuelve una lista de dicts agrupada por programa con conteos de
    horarios, docentes y estudiantes (distintos). Filtros opcionales."""
    qs = Horario.objects.all()
    if facultad_id:
        qs = qs.filter(materia__programa__facultad_id=facultad_id)
    if programa_id:
        qs = qs.filter(materia__programa_id=programa_id)
    filas = (qs
             .values('materia__programa__facultad__nombre',
                     'materia__programa_id',
                     'materia__programa__nombre')
             .annotate(total=Count('id_horario'),
                       docentes=Count('docente', distinct=True),
                       estudiantes=Count('matricula__estudiante', distinct=True))
             .order_by('materia__programa__facultad__nombre',
                       'materia__programa__nombre'))
    resultado = []
    for f in filas:
        resultado.append({
            'facultad': f['materia__programa__facultad__nombre'] or 'Sin facultad',
            'programa_id': f['materia__programa_id'],
            'programa': f['materia__programa__nombre'] or 'Sin programa',
            'total': f['total'],
            'docentes': f['docentes'],
            'estudiantes': f['estudiantes'],
        })
    return resultado


@staff_required
def reportes_categoria_view(request):
    """Página de Reportes por Categoría: selectores + descargas + resumen.

    2026-09-06: abierta a ADMINISTRADOR y COORDINADOR (antes @admin_required
    dejaba a Coordinador sin ningun modulo de reportes -- ver comentario en
    apps.autenticacion.models.Usuario.ROL_EQUIVALENCIAS, que ya documentaba
    esta intencion: Coordinador ve reportes/academico, NO el panel ejecutivo
    ni auditoria, que siguen reservados a ADMINISTRADOR mas abajo."""
    facultades = Facultad.objects.filter(activa=True).order_by('nombre')
    programas = (Programa.objects.filter(activo=True)
                 .select_related('facultad').order_by('nombre'))
    # Orden cronologico (1,2,...,12), no alfabetico -- .order_by('ciclo') a
    # nivel de BD ordena como texto (2026-09-06, ver _ciclo_sort_key).
    # OJO: se usa set() en vez de .distinct() -- Materia tiene Meta.ordering
    # = ['programa','ciclo','nombre'], y sin un .order_by() explicito que lo
    # reemplace, Django arrastra ese ordering por defecto a la consulta;
    # Postgres entonces exige esas columnas en el SELECT para el DISTINCT,
    # lo que en la practica hace el distinct() sobre (ciclo, programa,
    # nombre) en vez de solo ciclo -- devuelve duplicados. set() en Python
    # no tiene ese problema.
    ciclos = set(Materia.objects.values_list('ciclo', flat=True))
    ciclos = sorted([c for c in ciclos if c], key=_ciclo_sort_key)

    resumen = _resumen_horarios_por_categoria()
    kpis = {
        'total_horarios': Horario.objects.count(),
        'total_programas': programas.count(),
        'total_facultades': facultades.count(),
        'total_materias': Materia.objects.count(),
    }
    jornadas = [(k, v['label']) for k, v in JORNADAS.items()]
    modalidades = list(Programa.MODALIDAD_CHOICES)
    return render(request, 'dashboard/reportes_categoria.html', {
        'facultades': facultades,
        'programas': programas,
        'ciclos': ciclos,
        'resumen': resumen,
        'kpis': kpis,
        'jornadas': jornadas,
        'modalidades': modalidades,
        'active': 'reportes',
    })


@staff_required
def auditoria_pdf_categorias(request):
    """Exporta en PDF (ReportLab) la auditoría/resumen de horarios filtrado
    por facultad y/o programa, con encabezado del Politécnico Internacional.

    2026-09-06: abierta a ADMINISTRADOR y COORDINADOR -- es el boton "PDF
    Auditoria" del propio modulo de Reportes por categoria (reportes_categoria.html),
    no la auditoria completa (login/SISCA/Motor IA), que sigue en
    auditoria_view bajo @admin_required."""
    from io import BytesIO
    from django.http import HttpResponse

    facultad_id = (request.GET.get('facultad_id') or '').strip() or None
    programa_id = (request.GET.get('programa_id') or '').strip() or None

    # Construir descripción del filtro para el título
    partes = []
    if facultad_id:
        fac = Facultad.objects.filter(pk=facultad_id).first()
        if fac:
            partes.append(fac.nombre)
        else:
            facultad_id = None
    if programa_id:
        prog = Programa.objects.filter(pk=programa_id).first()
        if prog:
            partes.append(prog.nombre)
        else:
            programa_id = None
    filtro_txt = ' · '.join(partes) if partes else 'Todas las categorías'

    resumen = _resumen_horarios_por_categoria(facultad_id, programa_id)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle)
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        messages.error(request, 'Falta librería reportlab. Instala: pip install reportlab')
        return redirect('reportes_categoria')

    AZUL = colors.HexColor('#1F4988')
    AZUL_CLARO = colors.HexColor('#E8EEF7')
    GRIS_BORDE = colors.HexColor('#9CA3AF')

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.2*cm, bottomMargin=1.2*cm,
                            title='Auditoria por Categoria - Politecnico Internacional')
    styles = getSampleStyleSheet()
    s_title = ParagraphStyle('t', parent=styles['Normal'], fontName='Helvetica-BoldOblique',
                             fontSize=15, textColor=AZUL, alignment=TA_CENTER)
    s_sub = ParagraphStyle('sub', parent=styles['Normal'], fontName='Helvetica-Bold',
                           fontSize=10, textColor=colors.black, alignment=TA_LEFT)
    s_small = ParagraphStyle('sm', parent=styles['Normal'], fontName='Helvetica',
                             fontSize=8, textColor=colors.HexColor('#444444'))
    s_th = ParagraphStyle('th', parent=styles['Normal'], fontName='Helvetica-Bold',
                          fontSize=8, textColor=colors.white, alignment=TA_LEFT)
    s_td = ParagraphStyle('td', parent=styles['Normal'], fontName='Helvetica',
                          fontSize=8, textColor=colors.black, leading=10)
    story = []

    # Encabezado institucional
    enc = Table([[Paragraph('<i>POLITECNICO INTERNACIONAL</i>', s_title)]],
                colWidths=[18*cm], rowHeights=[1.1*cm])
    enc.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.7, GRIS_BORDE),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(enc)
    story.append(Spacer(1, 0.25*cm))
    story.append(Paragraph('Reporte de Auditoría de Horarios por Categoría', s_sub))
    story.append(Paragraph(f'Filtro: <b>{filtro_txt}</b>', s_small))
    story.append(Paragraph('Generado: ' + timezone.now().strftime('%d/%m/%Y %H:%M'), s_small))
    story.append(Spacer(1, 0.3*cm))

    # Estadísticas globales del sistema (auditoría)
    stats = [
        ['Logins exitosos', str(IntentoLogin.objects.filter(exitoso=True).count())],
        ['Logins fallidos', str(IntentoLogin.objects.filter(exitoso=False).count())],
        ['Eventos SISCA', str(IntegracionLog.objects.count())],
        ['Ejecuciones Motor IA', str(AsignacionIA.objects.count())],
    ]
    st_tbl = Table([[Paragraph('<b>Indicador</b>', s_td), Paragraph('<b>Valor</b>', s_td)]] +
                   [[Paragraph(a, s_td), Paragraph(b, s_td)] for a, b in stats],
                   colWidths=[10*cm, 8*cm])
    st_tbl.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, GRIS_BORDE),
        ('BACKGROUND', (0,0), (-1,0), AZUL_CLARO),
        ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(st_tbl)
    story.append(Spacer(1, 0.4*cm))

    # Tabla resumen por categoría
    story.append(Paragraph('Horarios por Facultad / Programa', s_sub))
    story.append(Spacer(1, 0.15*cm))
    data = [[Paragraph('Facultad', s_th), Paragraph('Programa', s_th),
             Paragraph('Horarios', s_th), Paragraph('Docentes', s_th),
             Paragraph('Estudiantes', s_th)]]
    tot_h = tot_d = tot_e = 0
    for r in resumen:
        data.append([Paragraph(str(r['facultad']), s_td), Paragraph(str(r['programa']), s_td),
                     Paragraph(str(r['total']), s_td), Paragraph(str(r['docentes']), s_td),
                     Paragraph(str(r['estudiantes']), s_td)])
        tot_h += r['total']; tot_d += r['docentes']; tot_e += r['estudiantes']
    if not resumen:
        data.append([Paragraph('Sin horarios para el filtro seleccionado.', s_td),
                     '', '', '', ''])
    else:
        data.append([Paragraph('<b>TOTAL</b>', s_td), Paragraph('', s_td),
                     Paragraph(f'<b>{tot_h}</b>', s_td), Paragraph(f'<b>{tot_d}</b>', s_td),
                     Paragraph(f'<b>{tot_e}</b>', s_td)])
    res_tbl = Table(data, colWidths=[5.0*cm, 6.0*cm, 2.4*cm, 2.4*cm, 2.6*cm], repeatRows=1)
    estilo = [
        ('GRID', (0,0), (-1,-1), 0.5, GRIS_BORDE),
        ('BACKGROUND', (0,0), (-1,0), AZUL),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
    ]
    if resumen:
        estilo.append(('BACKGROUND', (0,-1), (-1,-1), AZUL_CLARO))
    res_tbl.setStyle(TableStyle(estilo))
    story.append(res_tbl)

    try:
        doc.build(story)
    except Exception as e:
        import logging
        logging.exception('PDF auditoria categorias error')
        messages.error(request, f'Error generando PDF: {e}')
        return redirect('reportes_categoria')

    slug = '_'.join(p.replace(' ', '_')[:20] for p in partes) if partes else 'todas'
    resp = HttpResponse(buf.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="auditoria_{slug}.pdf"'
    return resp


# ════════════════════════════════════════════════════════════════
#  7. DOCENTE — Mi horario, disponibilidad, materias, asistencia
# ════════════════════════════════════════════════════════════════

@docente_required
def docente_mi_horario(request):
    """Vista del docente para ver sus bloques asignados.
    Sprint 1 (2026-09-06): admite ?vista=semanal|diaria|mensual (RF 1.5) --
    mismos datos de 'horarios', solo reagrupados; diaria/mensual además
    resuelven SolicitudReprogramacion APROBADA para la(s) fecha(s) mostradas."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente para este usuario.')
        return redirect('dashboard')

    horarios = Horario.objects.select_related(
        'materia__programa', 'salon__sede', 'bloque', 'matricula__periodo'
    ).filter(docente=docente).order_by('dia', 'bloque__numero')

    # Agrupar por día para la grilla
    dias = ['LU', 'MA', 'MI', 'JU', 'VI', 'SA']
    grilla = {d: list(horarios.filter(dia=d)) for d in dias}

    vista = request.GET.get('vista', 'semanal')
    contexto_extra = {}
    if vista == 'diaria':
        contexto_extra = _contexto_vista_diaria(request, horarios)
    elif vista == 'mensual':
        contexto_extra = _contexto_vista_mensual(request, horarios)

    return render(request, 'dashboard/docente_mi_horario.html', {
        'docente':  docente,
        'horarios': horarios,
        'grilla':   grilla,
        'vista':    vista,
        **contexto_extra,
    })


@docente_required
def docente_mis_materias(request):
    """Vista del docente para ver sus materias asignadas."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    horarios = Horario.objects.select_related(
        'materia__programa__facultad', 'matricula__periodo'
    ).filter(docente=docente).order_by('materia__nombre')

    # Agrupar materias únicas
    materias_ids = horarios.values_list('materia', flat=True).distinct()
    from apps.academico.models import Materia as MateriaModel
    materias = MateriaModel.objects.filter(id_materia__in=materias_ids).select_related('programa__facultad')

    return render(request, 'dashboard/docente_mis_materias.html', {
        'docente':  docente,
        'materias': materias,
        'horarios': horarios,
        'total':    materias.count(),
    })


@docente_required
def docente_disponibilidad(request):
    """Vista del docente para gestionar su disponibilidad horaria."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    if request.method == 'POST':
        # Reemplazar disponibilidades existentes
        DisponibilidadDocente.objects.filter(docente=docente).delete()
        dias = request.POST.getlist('dias')
        bloques = request.POST.getlist('bloques')
        for dia in dias:
            for bloque_num in bloques:
                try:
                    bloque = Bloque.objects.get(numero=int(bloque_num))
                    DisponibilidadDocente.objects.get_or_create(
                        docente=docente, dia=dia, bloque=bloque
                    )
                except (Bloque.DoesNotExist, ValueError):
                    pass
        messages.success(request, 'Disponibilidad actualizada correctamente.')
        return redirect('docente_disponibilidad')

    disponibilidades = DisponibilidadDocente.objects.filter(docente=docente).select_related('bloque')
    bloques = Bloque.objects.order_by('numero')
    dias_choices = Horario.DIA_CHOICES

    return render(request, 'dashboard/docente_disponibilidad.html', {
        'docente':          docente,
        'disponibilidades': disponibilidades,
        'bloques':          bloques,
        'dias_choices':     dias_choices,
    })


@docente_required
def docente_mis_estudiantes(request):
    """Vista del docente para ver sus estudiantes por materia."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    horarios = Horario.objects.select_related(
        'matricula__estudiante__usuario', 'matricula__estudiante__programa',
        'materia', 'matricula__periodo'
    ).filter(docente=docente).order_by('materia__nombre')

    # Agrupar por materia
    from collections import defaultdict
    por_materia = defaultdict(list)
    for h in horarios:
        por_materia[h.materia].append(h.matricula.estudiante)

    return render(request, 'dashboard/docente_mis_estudiantes.html', {
        'docente':     docente,
        'por_materia': dict(por_materia),
        'total':       sum(len(v) for v in por_materia.values()),
    })


def _resumen_asistencia_hibrido(horarios_qs, filtrar_por_matricula=False):
    """RF 2.1 -- modo HÍBRIDO (Sprint 2, 2026-09-06): si SISCA responde
    para el id_sisca de un Horario se usa ese dato tal cual (autoridad);
    si no, se calcula localmente desde asistencias.AsistenciaEstudiante.
    filtrar_por_matricula=True limita el cálculo local a la matrícula
    exacta de cada Horario (vista de UN estudiante); False agrega sobre
    todos los estudiantes de ese Horario (vista de un docente).
    Corrige además un desvío ya existente: docente_asistencia/
    estudiante_asistencia pasaban 'horarios'/'asistencia_sisca' a un
    template que en realidad esperaba 'materias_resumen'/'error_sisca'
    (encontrado 2026-09-06 al implementar el modo híbrido)."""
    error_sisca = None
    sisca_por_horario = {}
    try:
        cliente = get_cliente()
        if cliente.ping():
            for h in horarios_qs:
                if h.id_sisca:
                    try:
                        sisca_por_horario[h.id_horario] = cliente.get_asistencia(h.id_sisca)
                    except ClienteSISCAError:
                        pass
        else:
            error_sisca = 'SISCA no respondió al ping.'
    except ClienteSISCAError as exc:
        error_sisca = str(exc)
    except Exception:
        error_sisca = 'No fue posible conectar con SISCA.'

    materias_resumen = []
    materias_vistas = set()
    for h in horarios_qs:
        if h.materia_id in materias_vistas:
            continue
        materias_vistas.add(h.materia_id)

        if h.id_horario in sisca_por_horario:
            data = dict(sisca_por_horario[h.id_horario])
            data.setdefault('origen', 'SISCA')
        else:
            qs_local = AsistenciaEstudiante.objects.filter(horario__materia_id=h.materia_id, horario__docente_id=h.docente_id)
            if filtrar_por_matricula:
                qs_local = qs_local.filter(matricula_id=h.matricula_id)
            sesiones_totales = qs_local.values('fecha').distinct().count()
            total_registros = qs_local.count()
            presentes = qs_local.filter(estado__in=['PRESENTE', 'TARDANZA', 'JUSTIFICADO']).count()
            pct = round((presentes / total_registros) * 100, 1) if total_registros else None
            if filtrar_por_matricula:
                en_riesgo = 0
            else:
                por_estudiante = qs_local.values('matricula').annotate(
                    total=Count('id_asistencia'),
                    presentes=Count('id_asistencia', filter=Q(estado__in=['PRESENTE', 'TARDANZA', 'JUSTIFICADO'])),
                )
                en_riesgo = sum(1 for e in por_estudiante if e['total'] and (e['presentes'] / e['total']) * 100 < 80)
            data = {
                'sesiones_realizadas':  sesiones_totales,
                'sesiones_totales':     sesiones_totales,
                'porcentaje_asistencia_promedio': pct,
                'estudiantes_en_riesgo': en_riesgo,
                'origen': 'LOCAL',
            }
        materias_resumen.append({'materia': h.materia, 'data': data})

    return materias_resumen, error_sisca


@docente_required
def docente_asistencia(request):
    """Vista del docente para consultar asistencia de sus estudiantes.
    Modo HÍBRIDO (Sprint 2, 2026-09-06): ver _resumen_asistencia_hibrido."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    horarios = Horario.objects.select_related(
        'materia', 'matricula__estudiante__usuario', 'bloque'
    ).filter(docente=docente, estado='PUBLICADO').order_by('materia__nombre')

    materias_resumen, error_sisca = _resumen_asistencia_hibrido(horarios, filtrar_por_matricula=False)

    return render(request, 'dashboard/docente_asistencia.html', {
        'docente':         docente,
        'materias_resumen': materias_resumen,
        'error_sisca':     error_sisca,
    })


@docente_required
def docente_reportes(request):
    """Reportes del docente (2026-09-06): resumen de su carga horaria,
    materias y horas por dia, con botones de descarga en PDF/Excel.

    Los botones reutilizan los endpoints ya existentes
    horarios_exportar_pdf_completo / horarios_exportar_excel_completo, que
    YA auto-filtran por docente=request.user cuando rol_efectivo ==
    'DOCENTE' (ver _filtrar_horarios_categoria) -- no hace falta escribir
    generacion de PDF/Excel nueva."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    periodo_actual = get_periodo_seleccionado(request)
    horarios = Horario.objects.select_related(
        'materia__programa', 'salon__sede', 'bloque', 'matricula__periodo'
    ).filter(docente=docente)
    if periodo_actual:
        horarios = horarios.filter(matricula__periodo=periodo_actual)

    dias = ['LU', 'MA', 'MI', 'JU', 'VI', 'SA']
    horas_por_dia = [(d, label, horarios.filter(dia=d).count()) for d, label in Horario.DIA_CHOICES if d in dias]

    total_materias = horarios.values('materia').distinct().count()
    total_estudiantes = horarios.values('matricula__estudiante').distinct().count()
    total_horas = horarios.count()
    carga_max = docente.carga_horaria_max or 20
    ocupacion_pct = round((total_horas / carga_max) * 100) if carga_max else 0
    sobrecargado = total_horas > carga_max

    return render(request, 'dashboard/docente_reportes.html', {
        'docente':          docente,
        'periodo_actual':   periodo_actual,
        'horas_por_dia':    horas_por_dia,
        'total_materias':   total_materias,
        'total_estudiantes': total_estudiantes,
        'total_horas':      total_horas,
        'carga_max':        carga_max,
        'ocupacion_pct':    ocupacion_pct,
        'sobrecargado':     sobrecargado,
        'active':           'reportes',
    })


# ════════════════════════════════════════════════════════════════
#  8. ESTUDIANTE — Mi horario, mis materias, asistencia, notas
# ════════════════════════════════════════════════════════════════

@estudiante_required
def estudiante_mi_horario(request):
    """Vista del estudiante para ver su horario del periodo activo.
    Sprint 1 (2026-09-06): admite ?vista=semanal|diaria|mensual (RF 1.5)."""
    try:
        estudiante = Estudiante.objects.select_related('usuario', 'programa').get(usuario=request.user)
    except Estudiante.DoesNotExist:
        messages.error(request, 'No se encontró perfil de estudiante.')
        return redirect('dashboard')

    periodo_actual = get_periodo_seleccionado(request)
    horarios = Horario.objects.select_related(
        'materia__programa', 'docente__usuario', 'salon__sede', 'bloque', 'matricula__periodo'
    ).filter(matricula__estudiante=estudiante).order_by('dia', 'bloque__numero')

    if periodo_actual:
        horarios = horarios.filter(matricula__periodo=periodo_actual)

    dias = ['LU', 'MA', 'MI', 'JU', 'VI', 'SA']
    grilla = {d: list(horarios.filter(dia=d)) for d in dias}

    vista = request.GET.get('vista', 'semanal')
    contexto_extra = {}
    if vista == 'diaria':
        contexto_extra = _contexto_vista_diaria(request, horarios)
    elif vista == 'mensual':
        contexto_extra = _contexto_vista_mensual(request, horarios)

    return render(request, 'dashboard/estudiante_mi_horario.html', {
        'estudiante':    estudiante,
        'horarios':      horarios,
        'grilla':        grilla,
        'periodo_actual': periodo_actual,
        'vista':         vista,
        **contexto_extra,
    })


@estudiante_required
def estudiante_mis_materias(request):
    """Vista del estudiante para ver sus materias matriculadas."""
    try:
        estudiante = Estudiante.objects.select_related('usuario', 'programa').get(usuario=request.user)
    except Estudiante.DoesNotExist:
        messages.error(request, 'No se encontró perfil de estudiante.')
        return redirect('dashboard')

    periodo_actual = get_periodo_seleccionado(request)
    horarios = Horario.objects.select_related(
        'materia__programa__facultad', 'docente__usuario', 'bloque'
    ).filter(matricula__estudiante=estudiante).order_by('materia__nombre')

    if periodo_actual:
        horarios = horarios.filter(matricula__periodo=periodo_actual)

    return render(request, 'dashboard/estudiante_mis_materias.html', {
        'estudiante':    estudiante,
        'horarios':      horarios,
        'periodo_actual': periodo_actual,
        'total':         horarios.count(),
    })


@estudiante_required
def estudiante_asistencia(request):
    """Vista del estudiante para consultar su asistencia. Modo HÍBRIDO
    (Sprint 2, 2026-09-06): ver _resumen_asistencia_hibrido."""
    try:
        estudiante = Estudiante.objects.select_related('usuario', 'programa').get(usuario=request.user)
    except Estudiante.DoesNotExist:
        messages.error(request, 'No se encontró perfil de estudiante.')
        return redirect('dashboard')

    horarios = Horario.objects.select_related(
        'materia', 'docente__usuario', 'bloque'
    ).filter(
        matricula__estudiante=estudiante,
        estado='PUBLICADO'
    ).order_by('materia__nombre')

    materias_resumen, error_sisca = _resumen_asistencia_hibrido(horarios, filtrar_por_matricula=True)

    return render(request, 'dashboard/estudiante_asistencia.html', {
        'estudiante':      estudiante,
        'materias_resumen': materias_resumen,
        'error_sisca':     error_sisca,
    })


@estudiante_required
def estudiante_notas(request):
    """Vista del estudiante para consultar sus notas y calificaciones."""
    try:
        estudiante = Estudiante.objects.select_related('usuario', 'programa').get(usuario=request.user)
    except Estudiante.DoesNotExist:
        messages.error(request, 'No se encontró perfil de estudiante.')
        return redirect('dashboard')

    periodo_actual = get_periodo_seleccionado(request)
    matriculas = Matricula.objects.select_related(
        'periodo', 'estudiante'
    ).filter(estudiante=estudiante).order_by('-periodo__codigo')

    horarios = Horario.objects.select_related(
        'materia__programa', 'docente__usuario', 'matricula__periodo'
    ).filter(matricula__estudiante=estudiante).order_by('materia__nombre')

    if periodo_actual:
        horarios_periodo = horarios.filter(matricula__periodo=periodo_actual)
    else:
        horarios_periodo = horarios
    return render(request, 'dashboard/estudiante_notas.html', {
        'estudiante':      estudiante,
        'horarios':        horarios_periodo,
        'todas_matriculas': matriculas,
        'periodo_actual':  periodo_actual,
        'total_materias':  horarios_periodo.count(),
    })


@estudiante_required
def estudiante_reportes(request):
    """Reportes del estudiante (2026-09-06): resumen de su horario,
    materias y asistencia del periodo, con botones de descarga en PDF/Excel.

    Los botones reutilizan los endpoints ya existentes
    horarios_exportar_pdf_completo / horarios_exportar_excel_completo, que
    YA auto-filtran por matricula__estudiante=request.user cuando
    rol_efectivo == 'ESTUDIANTE' (ver _filtrar_horarios_categoria) -- no
    hace falta escribir generacion de PDF/Excel nueva."""
    try:
        estudiante = Estudiante.objects.select_related('usuario', 'programa').get(usuario=request.user)
    except Estudiante.DoesNotExist:
        messages.error(request, 'No se encontró perfil de estudiante.')
        return redirect('dashboard')

    periodo_actual = get_periodo_seleccionado(request)
    horarios = Horario.objects.select_related(
        'materia__programa', 'docente__usuario', 'bloque'
    ).filter(matricula__estudiante=estudiante)
    if periodo_actual:
        horarios = horarios.filter(matricula__periodo=periodo_actual)

    total_materias = horarios.values('materia').distinct().count()
    total_horas = horarios.count()

    sisca_conectado = False
    resumen_asistencia = {}
    try:
        cliente = get_cliente()
        if cliente.ping():
            sisca_conectado = True
            for h in horarios.filter(estado='PUBLICADO'):
                if h.id_sisca:
                    try:
                        resumen_asistencia[h.id_horario] = cliente.get_asistencia(h.id_sisca)
                    except Exception:
                        pass
    except Exception:
        pass

    return render(request, 'dashboard/estudiante_reportes.html', {
        'estudiante':        estudiante,
        'periodo_actual':    periodo_actual,
        'total_materias':    total_materias,
        'total_horas':       total_horas,
        'sisca_conectado':   sisca_conectado,
        'resumen_asistencia': resumen_asistencia,
        'active':            'reportes',
    })



# ════════════════════════════════════════════════════════════════
#  9. ADMIN — Base de datos (CRUD, backup/restore) y gestion de usuarios
#     Fase 3 (2026-09-04). Todo bajo @admin_required: nunca staff_required
#     (Coordinador NO debe tener acceso a esto).
# ════════════════════════════════════════════════════════════════

# Apps propias del proyecto cuyos modelos se exponen en el panel de Base de
# Datos. Se excluyen deliberadamente las apps internas de Django (admin,
# auth, contenttypes, sessions) -- esas se administran solas.
APPS_PROYECTO = [
    'autenticacion', 'academico', 'infraestructura', 'matriculas',
    'horarios', 'personal', 'integracion_sisca', 'reportes',
]

BACKUPS_DIR = djsettings.BASE_DIR / 'backups'


def _inventario_modelos():
    """Recorre las apps del proyecto y arma, por cada modelo registrado,
    su conteo de filas y la URL de Django Admin para administrarlo (CRUD
    completo: ver, crear, modificar, eliminar) -- se reutiliza el admin de
    Django en vez de construir un editor de SQL a mano, para no arriesgar
    la integridad de la base de datos con un CRUD generico sin validacion."""
    inventario = []
    for label in APPS_PROYECTO:
        try:
            app_config = django_apps.get_app_config(label)
        except LookupError:
            continue
        modelos = []
        for model in app_config.get_models():
            try:
                total = model.objects.count()
            except Exception:
                total = None
            modelos.append({
                'nombre':      model._meta.verbose_name_plural.title(),
                'tabla':       model._meta.db_table,
                'total':       total,
                'admin_url':   f'/admin/{model._meta.app_label}/{model._meta.model_name}/',
                'registrado':  _esta_registrado_en_admin(model),
            })
        if modelos:
            inventario.append({
                'app': app_config.verbose_name,
                'modelos': sorted(modelos, key=lambda m: m['nombre']),
            })
    return inventario


def _esta_registrado_en_admin(model):
    from django.contrib import admin as django_admin
    return model in django_admin.site._registry


@admin_required
def base_datos_view(request):
    """Panel central de Administracion de Base de Datos: inventario de
    tablas con acceso a CRUD completo (via Django Admin), y punto de
    entrada a Backup/Restore y a Gestion de Usuarios."""
    backups = _listar_backups()
    inventario = _inventario_modelos()
    total_tablas = sum(len(grupo['modelos']) for grupo in inventario)
    return render(request, 'dashboard/base_datos.html', {
        'inventario': inventario,
        'total_tablas': total_tablas,
        'backups': backups,
        'total_usuarios': Usuario.objects.count(),
        'total_usuarios_activos': Usuario.objects.filter(is_active=True).count(),
    })


def _listar_backups():
    if not BACKUPS_DIR.exists():
        return []
    archivos = sorted(BACKUPS_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    salida = []
    for p in archivos:
        stat = p.stat()
        salida.append({
            'nombre': p.name,
            'tamano_kb': round(stat.st_size / 1024, 1),
            'fecha': timezone.datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
        })
    return salida


@admin_required
@require_http_methods(['POST'])
def bd_backup_ejecutar(request):
    """Genera una copia de seguridad completa (dumpdata JSON) de todas las
    apps del proyecto, la guarda en backend/backups/ y la entrega como
    descarga inmediata. Usa el comando nativo de Django (dumpdata) en vez
    de un mysqldump/pg_dump a mano: ya maneja relaciones, encoding y
    modelos managed=False de forma segura."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    marca = timezone.now().strftime('%Y%m%d_%H%M%S')
    nombre = f'siihapi_backup_{marca}.json'
    ruta = BACKUPS_DIR / nombre

    try:
        with open(ruta, 'w', encoding='utf-8') as fh:
            call_command(
                'dumpdata', *APPS_PROYECTO,
                indent=2,
                use_natural_foreign_keys=True,
                use_natural_primary_keys=False,
                stdout=fh,
            )
    except Exception as e:
        if ruta.exists():
            ruta.unlink(missing_ok=True)
        messages.error(request, f'No se pudo generar la copia de seguridad: {e}')
        return redirect('base_datos')

    messages.success(request, f'Copia de seguridad creada: {nombre}')
    return redirect('bd_backup_descargar', filename=nombre)


@admin_required
def bd_backup_descargar(request, filename):
    ruta = BACKUPS_DIR / filename
    if '..' in filename or '/' in filename or not ruta.exists():
        raise Http404('Copia de seguridad no encontrada.')
    return FileResponse(open(ruta, 'rb'), as_attachment=True, filename=filename)


@admin_required
@require_http_methods(['POST'])
def bd_backup_eliminar(request, filename):
    ruta = BACKUPS_DIR / filename
    if '..' in filename or '/' in filename:
        raise Http404('Nombre de archivo invalido.')
    if ruta.exists():
        ruta.unlink()
        messages.success(request, f'Copia de seguridad {filename} eliminada.')
    else:
        messages.error(request, 'Esa copia de seguridad ya no existe.')
    return redirect('base_datos')


@admin_required
@require_http_methods(['POST'])
def bd_restore_view(request):
    """Restaura la base de datos desde un fixture JSON (generado por
    'Crear copia de seguridad' arriba) -- ya sea subiendo un archivo nuevo
    o eligiendo una copia ya guardada en el servidor. Exige que el
    administrador escriba la palabra RESTAURAR como confirmacion explicita,
    porque loaddata puede sobrescribir filas existentes (misma PK) y no es
    reversible por si solo -- por eso conviene generar SIEMPRE una copia de
    seguridad nueva justo antes de restaurar."""
    confirmacion = request.POST.get('confirmacion', '').strip().upper()
    if confirmacion != 'RESTAURAR':
        messages.error(request, 'Debes escribir RESTAURAR en el campo de confirmación para continuar.')
        return redirect('base_datos')

    archivo_subido = request.FILES.get('archivo')
    nombre_existente = request.POST.get('backup_existente', '').strip()

    tmp_path = None
    try:
        if archivo_subido:
            if not archivo_subido.name.lower().endswith('.json'):
                messages.error(request, 'El archivo de restauración debe ser un .json generado por este mismo panel.')
                return redirect('base_datos')
            fd, tmp_path = tempfile.mkstemp(suffix='.json')
            with os.fdopen(fd, 'wb') as fh:
                for chunk in archivo_subido.chunks():
                    fh.write(chunk)
            ruta_fixture = tmp_path
            origen = archivo_subido.name
        elif nombre_existente:
            if '..' in nombre_existente or '/' in nombre_existente:
                raise Http404('Nombre de archivo invalido.')
            ruta_candidata = BACKUPS_DIR / nombre_existente
            if not ruta_candidata.exists():
                messages.error(request, 'Esa copia de seguridad ya no existe en el servidor.')
                return redirect('base_datos')
            ruta_fixture = str(ruta_candidata)
            origen = nombre_existente
        else:
            messages.error(request, 'Sube un archivo .json o elige una copia de seguridad existente para restaurar.')
            return redirect('base_datos')

        with transaction.atomic():
            call_command('loaddata', ruta_fixture)

        messages.success(request, f'Base de datos restaurada desde «{origen}» correctamente.')
    except Exception as e:
        messages.error(request, f'La restauración falló y no se aplicó ningún cambio: {e}')
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    return redirect('base_datos')


# ── Gestion de usuarios (ver, crear, modificar, inactivar) ─────────

@admin_required
def usuarios_admin_view(request):
    q = request.GET.get('q', '').strip()
    rol_filtro = request.GET.get('rol', '')
    estado_filtro = request.GET.get('estado', '')

    usuarios = Usuario.objects.all()
    if q:
        usuarios = usuarios.filter(
            Q(correo__icontains=q) | Q(nombre__icontains=q) |
            Q(apellido__icontains=q) | Q(cedula__icontains=q)
        )
    if rol_filtro:
        usuarios = usuarios.filter(rol=rol_filtro)
    if estado_filtro:
        usuarios = usuarios.filter(estado=estado_filtro)

    return render(request, 'dashboard/usuarios_admin.html', {
        'usuarios': usuarios.order_by('apellido', 'nombre')[:300],
        'total': usuarios.count(),
        'q': q,
        'rol_filtro': rol_filtro,
        'estado_filtro': estado_filtro,
        'roles': Usuario.ROL_CHOICES,
        'estados': Usuario._meta.get_field('estado').choices,
    })


@admin_required
def usuario_crear_view(request):
    if request.method == 'POST':
        correo = request.POST.get('correo', '').strip().lower()
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        cedula = request.POST.get('cedula', '').strip() or None
        telefono = request.POST.get('telefono', '').strip()
        rol = request.POST.get('rol', 'ESTUDIANTE')
        password = request.POST.get('password', '').strip()

        errores = []
        if not correo:
            errores.append('El correo es obligatorio.')
        elif Usuario.objects.filter(correo=correo).exists():
            errores.append('Ya existe un usuario con ese correo.')
        if not nombre or not apellido:
            errores.append('Nombre y apellido son obligatorios.')
        if cedula and Usuario.objects.filter(cedula=cedula).exists():
            errores.append('Ya existe un usuario con esa cédula.')
        if not password or len(password) < 8:
            errores.append('La contraseña debe tener al menos 8 caracteres.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'dashboard/usuario_form.html', {
                'modo': 'crear', 'roles': Usuario.ROL_CHOICES,
                'valores': request.POST,
            })

        nuevo = Usuario.objects.create_user(correo=correo, password=password, rol=rol)
        nuevo.nombre = nombre
        nuevo.apellido = apellido
        nuevo.cedula = cedula
        nuevo.telefono = telefono
        # Rol ADMINISTRADOR = "acceso total" (ver siihapi/permisos.py) -> se le
        # da tambien acceso de superusuario a Django Admin (CRUD completo de
        # la base de datos), no solo a las vistas propias de SIIHAPI.
        es_admin_rol = rol in ('ADMINISTRADOR', 'ADMIN')
        nuevo.is_staff = es_admin_rol
        nuevo.is_superuser = es_admin_rol
        nuevo.save()

        messages.success(request, f'Usuario {nuevo.nombre} {nuevo.apellido} creado correctamente.')
        return redirect('usuarios_admin')

    return render(request, 'dashboard/usuario_form.html', {
        'modo': 'crear', 'roles': Usuario.ROL_CHOICES, 'valores': {},
    })


@admin_required
def usuario_editar_view(request, id_usuario):
    usuario_obj = get_object_or_404(Usuario, id_usuario=id_usuario)

    if request.method == 'POST':
        correo = request.POST.get('correo', '').strip().lower()
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        cedula = request.POST.get('cedula', '').strip() or None
        telefono = request.POST.get('telefono', '').strip()
        rol = request.POST.get('rol', usuario_obj.rol)
        password = request.POST.get('password', '').strip()

        errores = []
        if not correo:
            errores.append('El correo es obligatorio.')
        elif Usuario.objects.filter(correo=correo).exclude(id_usuario=usuario_obj.id_usuario).exists():
            errores.append('Ya existe otro usuario con ese correo.')
        if cedula and Usuario.objects.filter(cedula=cedula).exclude(id_usuario=usuario_obj.id_usuario).exists():
            errores.append('Ya existe otro usuario con esa cédula.')
        if password and len(password) < 8:
            errores.append('La nueva contraseña debe tener al menos 8 caracteres.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'dashboard/usuario_form.html', {
                'modo': 'editar', 'roles': Usuario.ROL_CHOICES,
                'usuario_obj': usuario_obj, 'valores': request.POST,
            })

        usuario_obj.correo = correo
        usuario_obj.nombre = nombre
        usuario_obj.apellido = apellido
        usuario_obj.cedula = cedula
        usuario_obj.telefono = telefono
        usuario_obj.rol = rol
        es_admin_rol = rol in ('ADMINISTRADOR', 'ADMIN')
        usuario_obj.is_staff = es_admin_rol
        usuario_obj.is_superuser = es_admin_rol
        if password:
            usuario_obj.set_password(password)
        usuario_obj.save()

        messages.success(request, f'Usuario {usuario_obj.nombre} {usuario_obj.apellido} actualizado correctamente.')
        return redirect('usuarios_admin')

    return render(request, 'dashboard/usuario_form.html', {
        'modo': 'editar', 'roles': Usuario.ROL_CHOICES, 'usuario_obj': usuario_obj,
        'valores': {
            'correo': usuario_obj.correo, 'nombre': usuario_obj.nombre,
            'apellido': usuario_obj.apellido, 'cedula': usuario_obj.cedula or '',
            'telefono': usuario_obj.telefono, 'rol': usuario_obj.rol,
        },
    })


@admin_required
@require_http_methods(['POST'])
def usuario_inactivar_view(request, id_usuario):
    """Inactivacion NO destructiva (activo/inactivo), igual que el resto
    del sistema (Programa, Sede, etc.): nunca se borra un Usuario, solo se
    bloquea el acceso (is_active=False, estado='I')."""
    usuario_obj = get_object_or_404(Usuario, id_usuario=id_usuario)
    if usuario_obj.id_usuario == request.user.id_usuario:
        messages.error(request, 'No puedes inactivar tu propia cuenta.')
        return redirect('usuarios_admin')

    usuario_obj.is_active = False
    usuario_obj.estado = 'I'
    usuario_obj.save(update_fields=['is_active', 'estado'])
    messages.success(request, f'Usuario {usuario_obj.nombre} {usuario_obj.apellido} inactivado.')
    return redirect('usuarios_admin')


@admin_required
@require_http_methods(['POST'])
def usuario_reactivar_view(request, id_usuario):
    usuario_obj = get_object_or_404(Usuario, id_usuario=id_usuario)
    usuario_obj.is_active = True
    usuario_obj.estado = 'A'
    usuario_obj.save(update_fields=['is_active', 'estado'])
    messages.success(request, f'Usuario {usuario_obj.nombre} {usuario_obj.apellido} reactivado.')
    return redirect('usuarios_admin')



# ════════════════════════════════════════════════════════════════
#  10. SOLICITUDES DE REPROGRAMACION + VISTAS DIARIA/MENSUAL
#      (Sprint 1 de la Especificacion Roles+Decano, RF 1.2/1.4/1.5,
#      2026-09-06)
# ════════════════════════════════════════════════════════════════

_DIA_CODES_POR_WEEKDAY = ['LU', 'MA', 'MI', 'JU', 'VI', 'SA', None]  # date.weekday(): 0=Lunes..6=Domingo (domingo no se programa)


def _resolver_reprogramaciones_aprobadas(horarios_qs, fecha_desde=None, fecha_hasta=None):
    """Trae las SolicitudReprogramacion APROBADA que caen en el rango de
    fechas dado, para los horarios de horarios_qs. Usado por las vistas
    diaria y mensual."""
    qs = SolicitudReprogramacion.objects.filter(
        horario__in=horarios_qs, estado='APROBADA'
    ).select_related('horario__materia', 'salon_propuesto', 'docente_sustituto_propuesto__usuario')
    if fecha_desde:
        qs = qs.filter(fecha_afectada__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_afectada__lte=fecha_hasta)
    return qs


def _contexto_vista_diaria(request, horarios_qs):
    """RF 1.5 -- misma info que la vista semanal, reagrupada a UN día
    calendario concreto (?fecha=YYYY-MM-DD, hoy por defecto), con las
    reprogramaciones puntuales aprobadas para esa fecha superpuestas."""
    fecha_str = request.GET.get('fecha')
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else timezone.localdate()
    except ValueError:
        fecha = timezone.localdate()
    dia_code = _DIA_CODES_POR_WEEKDAY[fecha.weekday()]
    horarios_del_dia = list(horarios_qs.filter(dia=dia_code)) if dia_code else []
    reprogramaciones = list(_resolver_reprogramaciones_aprobadas(horarios_qs, fecha_desde=fecha, fecha_hasta=fecha))
    return {
        'fecha_diaria':            fecha,
        'dia_diaria_code':         dia_code,
        'horarios_del_dia':        horarios_del_dia,
        'reprogramaciones_del_dia': reprogramaciones,
    }


def _contexto_vista_mensual(request, horarios_qs):
    """RF 1.5 -- misma info que la vista semanal, reagrupada en una
    grilla de calendario mensual (?mes=YYYY-MM, mes actual por defecto),
    con conteo de bloques por día y reprogramaciones aprobadas marcadas."""
    mes_str = request.GET.get('mes')
    hoy = timezone.localdate()
    try:
        anio, mes = (int(x) for x in mes_str.split('-')) if mes_str else (hoy.year, hoy.month)
    except (ValueError, AttributeError):
        anio, mes = hoy.year, hoy.month
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

    reprogramaciones_mes = list(_resolver_reprogramaciones_aprobadas(horarios_qs, fecha_desde=primer_dia, fecha_hasta=ultimo_dia))
    reprog_por_fecha = {}
    for r in reprogramaciones_mes:
        reprog_por_fecha.setdefault(r.fecha_afectada, []).append(r)

    semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(anio, mes)
    dias_mes = []
    for semana in semanas:
        fila = []
        for f in semana:
            dia_code = _DIA_CODES_POR_WEEKDAY[f.weekday()] if f.month == mes else None
            fila.append({
                'fecha':            f,
                'en_mes':           f.month == mes,
                'total_bloques':    horarios_qs.filter(dia=dia_code).count() if dia_code else 0,
                'reprogramaciones': reprog_por_fecha.get(f, []),
            })
        dias_mes.append(fila)

    return {
        'mes_actual':          primer_dia,
        'dias_mes':            dias_mes,
        'reprogramaciones_mes': reprogramaciones_mes,
    }


@docente_required
def docente_solicitudes_reprogramacion(request):
    """RF 1.4 -- el Docente titular de un Horario solicita una
    reprogramación puntual (cambio de aula / sustitución de docente /
    cambio de horario para UNA fecha) -- NO modifica el Horario base,
    que sigue siendo el horario regular del resto del ciclo."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            horario = Horario.objects.get(id_horario=request.POST.get('horario'), docente=docente)
        except (Horario.DoesNotExist, ValueError, TypeError):
            messages.error(request, 'Ese horario no existe o no te pertenece.')
            return redirect('docente_solicitudes_reprogramacion')

        tipo = request.POST.get('tipo')
        if tipo not in dict(SolicitudReprogramacion.TIPO_CHOICES):
            messages.error(request, 'Tipo de solicitud inválido.')
            return redirect('docente_solicitudes_reprogramacion')

        fecha_afectada = request.POST.get('fecha_afectada')
        motivo = request.POST.get('motivo', '').strip()
        if not fecha_afectada or not motivo:
            messages.error(request, 'Fecha afectada y motivo son obligatorios.')
            return redirect('docente_solicitudes_reprogramacion')

        solicitud = SolicitudReprogramacion(
            horario=horario, tipo=tipo, fecha_afectada=fecha_afectada,
            motivo=motivo, solicitado_por=request.user,
        )
        if tipo == 'CAMBIO_AULA' and request.POST.get('salon_propuesto'):
            solicitud.salon_propuesto = get_object_or_404(Salon, id_salon=request.POST['salon_propuesto'])
        if tipo == 'SUSTITUCION_DOCENTE' and request.POST.get('docente_sustituto_propuesto'):
            solicitud.docente_sustituto_propuesto = get_object_or_404(Docente, usuario_id=request.POST['docente_sustituto_propuesto'])
        solicitud.save()
        messages.success(request, 'Solicitud enviada. Quedará pendiente de aprobación de Coordinación/Secretaría/Decanatura.')
        return redirect('docente_solicitudes_reprogramacion')

    mis_horarios = Horario.objects.select_related('materia', 'bloque').filter(docente=docente).order_by('dia', 'bloque__numero')
    mis_solicitudes = SolicitudReprogramacion.objects.select_related(
        'horario__materia', 'salon_propuesto', 'docente_sustituto_propuesto__usuario', 'revisado_por'
    ).filter(solicitado_por=request.user).order_by('-created_at')

    return render(request, 'dashboard/solicitudes_reprogramacion.html', {
        'docente':         docente,
        'mis_horarios':    mis_horarios,
        'mis_solicitudes': mis_solicitudes,
        'salones':         Salon.objects.filter(activo=True).select_related('sede')[:300],
        'docentes':        Docente.objects.filter(activo=True).exclude(usuario=request.user).select_related('usuario')[:300],
    })


@operacion_required
def solicitudes_reprogramacion_gestionar(request):
    """RF 1.4 -- Coordinador/Secretaría Académica/Decano/Admin aprueban o
    rechazan solicitudes pendientes. @operacion_required == @staff_required
    (rol_efectivo in ADMINISTRADOR/COORDINADOR) + bloqueo de solo-consulta;
    rol_efectivo=='COORDINADOR' ya cubre a Secretaría/Decano vía
    ROL_EQUIVALENCIAS (ver Entregable 5 de la especificación) -- no hace
    falta un decorador nuevo para esta vista."""
    estado_filtro = request.GET.get('estado', 'PENDIENTE')
    qs = SolicitudReprogramacion.objects.select_related(
        'horario__materia', 'horario__docente__usuario', 'salon_propuesto',
        'docente_sustituto_propuesto__usuario', 'solicitado_por',
    ).order_by('-created_at')
    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)

    return render(request, 'dashboard/solicitudes_reprogramacion_gestionar.html', {
        'solicitudes':   qs[:300],
        'estado_filtro': estado_filtro,
        'estados':       SolicitudReprogramacion.ESTADO_CHOICES,
    })


@operacion_required
@require_http_methods(['POST'])
def solicitud_reprogramacion_resolver(request, id_solicitud):
    solicitud = get_object_or_404(SolicitudReprogramacion, id_solicitud=id_solicitud)
    accion = request.POST.get('accion')
    if accion not in ('aprobar', 'rechazar'):
        messages.error(request, 'Acción inválida.')
        return redirect('solicitudes_reprogramacion_gestionar')

    if solicitud.estado != 'PENDIENTE':
        messages.warning(request, 'Esa solicitud ya fue resuelta.')
        return redirect('solicitudes_reprogramacion_gestionar')

    solicitud.estado = 'APROBADA' if accion == 'aprobar' else 'RECHAZADA'
    solicitud.revisado_por = request.user
    solicitud.fecha_revision = timezone.now()
    solicitud.save(update_fields=['estado', 'revisado_por', 'fecha_revision'])
    messages.success(request, f'Solicitud #{solicitud.id_solicitud} {solicitud.get_estado_display().lower()}.')
    return redirect('solicitudes_reprogramacion_gestionar')



# ════════════════════════════════════════════════════════════════
#  11. ASISTENCIAS: registro local, justificaciones, alertas de riesgo,
#      dashboard de Bienestar/Mentoría (Sprint 2 de la Especificación
#      Roles+Decano, RF 2.1/2.2/2.3, 2026-09-06)
# ════════════════════════════════════════════════════════════════

@docente_required
def docente_marcar_asistencia(request):
    """RF 2.1 -- el Docente registra asistencia LOCAL de su clase para una
    fecha concreta (origen=LOCAL_DOCENTE), y su propia AsistenciaDocente
    para esa sesión. Complementa (no reemplaza) la lectura híbrida de
    docente_asistencia: si SISCA reporta el mismo dato más adelante, SISCA
    sigue teniendo prioridad de lectura (ver _resumen_asistencia_hibrido)."""
    try:
        docente = Docente.objects.select_related('usuario').get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    mis_horarios = Horario.objects.select_related('materia', 'bloque').filter(docente=docente).order_by('materia__nombre', 'dia')

    horario_id = request.GET.get('horario') or request.POST.get('horario')
    fecha = request.GET.get('fecha') or request.POST.get('fecha') or timezone.localdate().isoformat()
    horario_sel = None
    matriculas = []
    asistencias_previas = {}

    if horario_id:
        try:
            horario_sel = Horario.objects.select_related('materia', 'bloque', 'matricula__periodo').get(id_horario=horario_id, docente=docente)
        except Horario.DoesNotExist:
            messages.error(request, 'Ese horario no existe o no te pertenece.')
            return redirect('docente_marcar_asistencia')

        matriculas = Matricula.objects.select_related('estudiante__usuario').filter(
            materia=horario_sel.materia, periodo=horario_sel.matricula.periodo, estado='ACTIVA'
        ).order_by('estudiante__usuario__apellido')

        if request.method == 'POST':
            for mat in matriculas:
                estado_val = request.POST.get(f'estado_{mat.id_matricula}')
                if estado_val not in dict(AsistenciaEstudiante.ESTADO_CHOICES):
                    continue
                AsistenciaEstudiante.objects.update_or_create(
                    matricula=mat, horario=horario_sel, fecha=fecha,
                    defaults={
                        'estado': estado_val, 'origen': 'LOCAL_DOCENTE',
                        'registrado_por': request.user, 'hora_registro': timezone.localtime().time(),
                    },
                )
            estado_docente = request.POST.get('estado_docente', 'DICTADA')
            if estado_docente in dict(AsistenciaDocente.ESTADO_CHOICES):
                AsistenciaDocente.objects.update_or_create(
                    horario=horario_sel, fecha=fecha,
                    defaults={'docente': docente, 'estado': estado_docente},
                )
            messages.success(request, f'Asistencia registrada para {horario_sel.materia.codigo} el {fecha}.')
            return redirect(f"{reverse('docente_marcar_asistencia')}?horario={horario_id}&fecha={fecha}")

        asistencias_previas = {
            a.matricula_id: a for a in AsistenciaEstudiante.objects.filter(horario=horario_sel, fecha=fecha)
        }
        for mat in matriculas:
            previa = asistencias_previas.get(mat.id_matricula)
            mat.estado_previo = previa.estado if previa else ''

    estado_docente_previo = ''
    if horario_sel:
        asistencia_docente_previa = AsistenciaDocente.objects.filter(horario=horario_sel, fecha=fecha).first()
        if asistencia_docente_previa:
            estado_docente_previo = asistencia_docente_previa.estado

    return render(request, 'dashboard/docente_marcar_asistencia.html', {
        'docente':               docente,
        'mis_horarios':          mis_horarios,
        'horario_sel':           horario_sel,
        'matriculas':            matriculas,
        'fecha':                 fecha,
        'estados':               AsistenciaEstudiante.ESTADO_CHOICES,
        'estados_docente':       AsistenciaDocente.ESTADO_CHOICES,
        'estado_docente_previo': estado_docente_previo,
    })


@login_required
def mis_justificaciones(request):
    """RF 2.2 -- Docente o Estudiante sube una justificación con soporte
    para una AsistenciaDocente/AsistenciaEstudiante propia."""
    if es_docente(request.user):
        asistencias_propias = AsistenciaDocente.objects.filter(docente__usuario=request.user).select_related('horario__materia').order_by('-fecha')[:100]
        justificaciones = Justificacion.objects.filter(creado_por=request.user).select_related('asistencia_docente__horario__materia').order_by('-created_at')
    elif es_estudiante(request.user):
        asistencias_propias = AsistenciaEstudiante.objects.filter(matricula__estudiante__usuario=request.user).select_related('horario__materia').order_by('-fecha')[:100]
        justificaciones = Justificacion.objects.filter(creado_por=request.user).select_related('asistencia_estudiante__horario__materia').order_by('-created_at')
    else:
        messages.error(request, 'Esta sección es solo para Docentes y Estudiantes.')
        return redirect('dashboard')

    if request.method == 'POST':
        tipo_asistencia = request.POST.get('tipo_asistencia')
        asistencia_id = request.POST.get('asistencia_id')
        motivo = request.POST.get('motivo', '').strip()
        if not motivo or not asistencia_id:
            messages.error(request, 'Motivo y la clase afectada son obligatorios.')
            return redirect('mis_justificaciones')

        kwargs = {'motivo': motivo, 'creado_por': request.user}
        if request.FILES.get('soporte_archivo'):
            kwargs['soporte_archivo'] = request.FILES['soporte_archivo']

        if tipo_asistencia == 'docente' and es_docente(request.user):
            kwargs['asistencia_docente'] = get_object_or_404(AsistenciaDocente, id_asistencia=asistencia_id, docente__usuario=request.user)
        elif tipo_asistencia == 'estudiante' and es_estudiante(request.user):
            kwargs['asistencia_estudiante'] = get_object_or_404(AsistenciaEstudiante, id_asistencia=asistencia_id, matricula__estudiante__usuario=request.user)
        else:
            messages.error(request, 'Tipo de asistencia inválido.')
            return redirect('mis_justificaciones')

        Justificacion.objects.create(**kwargs)
        messages.success(request, 'Justificación enviada. Quedará pendiente de revisión.')
        return redirect('mis_justificaciones')

    return render(request, 'dashboard/mis_justificaciones.html', {
        'asistencias_propias': asistencias_propias,
        'justificaciones':     justificaciones,
        'es_docente_flag':     es_docente(request.user),
    })


@operacion_required
def justificaciones_gestionar(request):
    """RF 2.2 -- Secretaría Académica/Coordinador/Decano/Admin aprueban o
    rechazan justificaciones pendientes (rol_efectivo=='COORDINADOR' ya
    cubre a Secretaría/Decano vía ROL_EQUIVALENCIAS)."""
    estado_filtro = request.GET.get('estado', 'PENDIENTE')
    qs = Justificacion.objects.select_related(
        'asistencia_estudiante__matricula__estudiante__usuario', 'asistencia_estudiante__horario__materia',
        'asistencia_docente__docente__usuario', 'asistencia_docente__horario__materia', 'creado_por',
    ).order_by('-created_at')
    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)

    return render(request, 'dashboard/justificaciones_gestionar.html', {
        'justificaciones': qs[:300],
        'estado_filtro':   estado_filtro,
        'estados':         Justificacion.ESTADO_CHOICES,
    })


@operacion_required
@require_http_methods(['POST'])
def justificacion_resolver(request, id_justificacion):
    just = get_object_or_404(Justificacion, id_justificacion=id_justificacion)
    accion = request.POST.get('accion')
    if accion not in ('aprobar', 'rechazar'):
        messages.error(request, 'Acción inválida.')
        return redirect('justificaciones_gestionar')
    if just.estado != 'PENDIENTE':
        messages.warning(request, 'Esa justificación ya fue resuelta.')
        return redirect('justificaciones_gestionar')

    just.estado = 'APROBADA' if accion == 'aprobar' else 'RECHAZADA'
    just.revisado_por = request.user
    just.fecha_revision = timezone.now()
    just.save(update_fields=['estado', 'revisado_por', 'fecha_revision'])

    if just.estado == 'APROBADA' and just.asistencia_estudiante_id:
        just.asistencia_estudiante.estado = 'JUSTIFICADO'
        just.asistencia_estudiante.save(update_fields=['estado'])

    messages.success(request, f'Justificación #{just.id_justificacion} {just.get_estado_display().lower()}.')
    return redirect('justificaciones_gestionar')


def _es_bienestar_o_mentoria(user):
    """RF 2.3 -- dashboard compartido: BIENESTAR_ACADEMICO y MENTORIAS
    (ambos hoy en permisos.ROLES_SOLO_CONSULTA para el resto del sistema)
    más ADMIN/ADMINISTRADOR."""
    return user.is_authenticated and user.rol in ('BIENESTAR_ACADEMICO', 'MENTORIAS', 'ADMIN', 'ADMINISTRADOR')


@login_required
def bienestar_dashboard(request):
    """RF 2.3 -- alertas de riesgo abiertas y casos de bienestar. Esta es
    la primera función de ESCRITURA propia de Bienestar/Mentoría (el resto
    del sistema los deja en solo-consulta a propósito, ver permisos.py)."""
    if not _es_bienestar_o_mentoria(request.user):
        messages.error(request, 'Acceso denegado a este módulo.')
        return redirect('dashboard')

    estado_filtro = request.GET.get('estado', 'ABIERTA')
    alertas = AlertaRiesgo.objects.select_related('estudiante__usuario').prefetch_related('materias_afectadas').order_by('-fecha_deteccion')
    if estado_filtro:
        alertas = alertas.filter(estado=estado_filtro)

    casos = CasoBienestar.objects.select_related('estudiante__usuario', 'asignado_a').order_by('-created_at')[:100]

    return render(request, 'dashboard/bienestar_dashboard.html', {
        'alertas':        alertas[:200],
        'casos':          casos,
        'estado_filtro':  estado_filtro,
        'estados_alerta': AlertaRiesgo.ESTADO_CHOICES,
    })


@login_required
@require_http_methods(['POST'])
def alerta_riesgo_actualizar_estado(request, id_alerta):
    if not _es_bienestar_o_mentoria(request.user):
        messages.error(request, 'Acceso denegado a este módulo.')
        return redirect('dashboard')

    alerta = get_object_or_404(AlertaRiesgo, id_alerta=id_alerta)
    nuevo_estado = request.POST.get('estado')
    if nuevo_estado not in dict(AlertaRiesgo.ESTADO_CHOICES):
        messages.error(request, 'Estado inválido.')
        return redirect('bienestar_dashboard')

    alerta.estado = nuevo_estado
    if nuevo_estado == 'CERRADA':
        alerta.fecha_cierre = timezone.now()
        alerta.notas_cierre = request.POST.get('notas_cierre', '')
        alerta.save(update_fields=['estado', 'fecha_cierre', 'notas_cierre'])
    else:
        alerta.save(update_fields=['estado'])

    messages.success(request, f'Alerta #{alerta.id_alerta} actualizada a {alerta.get_estado_display()}.')
    return redirect('bienestar_dashboard')


# ════════════════════════════════════════════════════════════════
#  10. REPORTES DEL DECANO Y CERTIFICADOS -- generador PDF genérico
#      (Entregable 3 de la especificación Roles+Decano, 2026-09-06)
# ════════════════════════════════════════════════════════════════

def _construir_pdf_generico_politecnico(titulo, columnas, filas, titular=None, subtitulo=None, imagen_qr_bytes=None):
    """Reutiliza el mismo membrete/estilo (logo, pie de página, colores)
    que _construir_pdf_politecnico_siihapi, factorizado para recibir una
    tabla genérica (columnas: list[str], filas: list[tuple]) en vez de
    una lista de Horario -- la usan los 7 reportes del Decano (Sprint 4)
    y los certificados de apps.eventos (Sprint 3).

    titulo: encabezado principal del documento (ej. 'CONSTANCIA DE ASISTENCIA')
    columnas: encabezados de la tabla
    filas: list de tuplas/listas con los valores de cada fila
    titular: dict opcional (ver _titular_desde_request_siihapi) con datos
             de la persona a quien va dirigido el documento
    subtitulo: texto opcional bajo el titulo (ej. periodo o nombre del evento)
    imagen_qr_bytes: bytes PNG opcionales de un QR de verificación, se
             imprime al pie del documento (usado por Certificado)
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    AZUL = colors.HexColor('#1F4988')
    AZUL_CLARO = colors.HexColor('#E8EEF7')
    GRIS_BORDE = colors.HexColor('#9CA3AF')

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm,
        title=titulo or 'Documento - Politecnico Internacional',
    )
    styles = getSampleStyleSheet()
    s_title = ParagraphStyle('inst', parent=styles['Normal'], fontName='Helvetica-BoldOblique',
                              fontSize=16, textColor=AZUL, alignment=TA_CENTER)
    s_label = ParagraphStyle('lbl', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=8, textColor=AZUL)
    s_val = ParagraphStyle('val', parent=styles['Normal'], fontName='Helvetica',
                            fontSize=8, textColor=colors.black)
    s_th = ParagraphStyle('th', parent=styles['Normal'], fontName='Helvetica-Bold',
                           fontSize=9, textColor=AZUL)
    s_td = ParagraphStyle('td', parent=styles['Normal'], fontName='Helvetica',
                           fontSize=9, textColor=colors.black, leading=11)
    s_titulo_doc = ParagraphStyle('titdoc', parent=styles['Normal'], fontName='Helvetica-Bold',
                                   fontSize=13, textColor=colors.black, alignment=TA_CENTER, spaceBefore=10, spaceAfter=4)
    s_subtitulo = ParagraphStyle('subtdoc', parent=styles['Normal'], fontName='Helvetica-Oblique',
                                  fontSize=10, textColor=colors.HexColor('#475569'), alignment=TA_CENTER, spaceAfter=10)
    story = []

    # ─── Encabezado institucional (mismo estilo que _construir_pdf_politecnico_siihapi) ───
    encabezado = Table([[
        Paragraph('<b>Polit&eacute;cnico</b><br/>Internacional', s_label),
        Paragraph('<i>POLITECNICO INTERNACIONAL</i>', s_title),
    ]], colWidths=[3.5*cm, 15.5*cm], rowHeights=[1.3*cm])
    encabezado.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.7, GRIS_BORDE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(encabezado)
    story.append(Spacer(1, 0.3*cm))

    if titulo:
        story.append(Paragraph(titulo, s_titulo_doc))
    if subtitulo:
        story.append(Paragraph(subtitulo, s_subtitulo))

    # ─── Datos del titular (opcional) ───
    if titular:
        info = Table([
            [Paragraph('<b>Nombre y apellidos</b>', s_label), Paragraph(titular.get('nombre', ''), s_val),
             Paragraph('<b>Doc. Ident.</b>', s_label), Paragraph(titular.get('doc_ident', ''), s_val)],
            [Paragraph('<b>Curso Académico</b>', s_label), Paragraph(titular.get('periodo', ''), s_val),
             Paragraph('<b>Centro</b>', s_label), Paragraph(titular.get('centro', ''), s_val)],
        ], colWidths=[3.2*cm, 5.8*cm, 2.4*cm, 7.6*cm])
        info.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.7, GRIS_BORDE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(info)
        story.append(Spacer(1, 0.4*cm))

    # ─── Tabla genérica ───
    data = [[Paragraph(f'<b>{c}</b>', s_th) for c in columnas]]
    for fila in filas:
        data.append([Paragraph(str(v) if v is not None else '—', s_td) for v in fila])
    if len(data) == 1:
        data.append([Paragraph('—', s_td)] * max(len(columnas), 1))

    ancho_util = 18.5*cm
    n_cols = max(len(columnas), 1)
    col_widths = [ancho_util / n_cols] * n_cols
    tabla = Table(data, colWidths=col_widths, repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), AZUL_CLARO),
        ('LINEBELOW', (0, 0), (-1, 0), 0.7, AZUL),
        ('LINEABOVE', (0, 0), (-1, 0), 0.7, GRIS_BORDE),
        ('GRID', (0, 1), (-1, -1), 0.4, GRIS_BORDE),
        ('BOX', (0, 0), (-1, -1), 0.7, GRIS_BORDE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(tabla)

    if imagen_qr_bytes:
        story.append(Spacer(1, 0.6*cm))
        qr_buf = BytesIO(imagen_qr_bytes)
        story.append(Paragraph('Código de verificación:', ParagraphStyle(
            'qrlbl', parent=styles['Normal'], fontName='Helvetica', fontSize=8,
            textColor=colors.HexColor('#475569'), alignment=TA_CENTER)))
        story.append(Spacer(1, 0.15*cm))
        img = Image(qr_buf, width=2.8*cm, height=2.8*cm)
        img.hAlign = 'CENTER'
        story.append(img)

    def _pie_pagina(canvas, documento):
        canvas.saveState()
        canvas.setFont('Helvetica-Oblique', 9)
        ancho, _alto = A4
        y = 0.8*cm
        canvas.setStrokeColor(colors.HexColor('#9CA3AF'))
        canvas.line(documento.leftMargin, y + 0.35*cm, ancho - documento.rightMargin, y + 0.35*cm)
        canvas.setFillColor(colors.black)
        canvas.drawString(documento.leftMargin, y, 'Politécnico Internacional · Documento generado por SIIHAPI')
        canvas.drawRightString(ancho - documento.rightMargin, y, f'Pag. {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_pie_pagina, onLaterPages=_pie_pagina)
    buf.seek(0)
    return buf.read()


def _generar_qr_png(valor):
    """PNG bytes de un QR para el `valor` dado (str/UUID). Usado tanto
    para el QR de inscripción a eventos (token_qr) como para el QR de
    verificación impreso en un Certificado (codigo_verificacion)."""
    import qrcode
    from io import BytesIO
    img = qrcode.make(str(valor))
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()

def _construir_excel_generico_politecnico(titulo, columnas, filas):
    """Excel institucional generico, mismo estilo (AZUL #1F4988, header en
    blanco/negrita, bordes finos) que horarios_exportar_excel_completo --
    factorizado para recibir una tabla generica (columnas: list[str],
    filas: list[tuple]) en vez de una lista de Horario. Usado por los 7
    reportes del Decano (Sprint 4, ver siihapi/decano_views.py)."""
    from io import BytesIO
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (titulo or 'Reporte')[:31]

    AZUL = 'FF1F4988'
    n_cols = max(len(columnas), 1)
    ultima_col = get_column_letter(n_cols)
    ws.merge_cells(f'A1:{ultima_col}1')
    c = ws['A1']
    c.value = titulo or 'Politecnico Internacional'
    c.font = Font(bold=True, size=14, color='FFFFFFFF')
    c.fill = PatternFill('solid', fgColor=AZUL)
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 26

    ws.append(list(columnas))
    thin = Side(style='thin', color='FFB0B0B0')
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=2, column=col)
        cell.font = Font(bold=True, color='FFFFFFFF')
        cell.fill = PatternFill('solid', fgColor='FF2C5BA0')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = borde

    for fila in filas:
        ws.append([v if v is not None else '\u2014' for v in fila])

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=n_cols):
        for cell in row:
            cell.border = borde
            if cell.row > 2:
                cell.alignment = Alignment(vertical='center', wrap_text=True)
    for i in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(i)].width = 20
    ws.freeze_panes = 'A3'

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ════════════════════════════════════════════════════════════════
#  11. APPS.EVENTOS -- calendario, reservas, inscripciones QR,
#      asistencia por escaneo, certificados (Sprint 3, 2026-09-06)
# ════════════════════════════════════════════════════════════════

def _parse_datetime_local_aware(valor):
    """Convierte el string de un <input type=datetime-local> ('YYYY-MM-DDTHH:MM')
    en un datetime timezone-aware (America/Bogota, ver settings.TIME_ZONE)
    -- evita guardar datetimes naive con USE_TZ=True (apps.eventos.models
    usa DateTimeField en Evento/ReservaRecurso/AsistenciaEvento)."""
    if not valor:
        return None
    dt = datetime.fromisoformat(valor)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _hay_conflicto_reserva(salon, fecha_inicio, fecha_fin, excluir_id=None):
    """Misma lógica de detección de cruces que ya usa horario_actualizar
    para Horario (RF 1.2), aplicada a ReservaRecurso: dos reservas del
    mismo salón se solapan si el intervalo [fecha_inicio, fecha_fin) de
    una cae dentro del de la otra."""
    qs = ReservaRecurso.objects.filter(
        salon=salon, estado__in=['SOLICITADA', 'CONFIRMADA'],
        fecha_inicio__lt=fecha_fin, fecha_fin__gt=fecha_inicio,
    )
    if excluir_id:
        qs = qs.exclude(id_reserva=excluir_id)
    return qs.exists()


def _puede_gestionar_eventos(user):
    """Admin/Coordinador/Decano/Secretaría (via rol_efectivo=='COORDINADOR'
    u 'ADMINISTRADOR') -- Bienestar/Mentoría quedan fuera (solo consulta,
    igual que en el resto del sistema, ver permisos.operacion_required)."""
    return user.is_authenticated and user.rol_efectivo in ('ADMINISTRADOR', 'COORDINADOR') and not es_solo_consulta(user)


def _puede_escanear_evento(user, evento):
    """Quién puede operar el escáner QR de un evento concreto: el staff
    operativo (mismo criterio que @operacion_required) o el propio
    Docente que propuso el evento (organizador natural de su actividad)."""
    if _puede_gestionar_eventos(user):
        return True
    return es_docente(user) and evento.propuesto_por_id == user.id_usuario


@login_required
def calendario_eventos(request):
    """RF 3.1/3.5 -- calendario institucional, visible a todos los roles
    (lectura). BORRADOR solo lo ve quien puede gestionar eventos o quien
    lo propuso."""
    qs = Evento.objects.select_related('facultad', 'programa', 'materia', 'propuesto_por').order_by('fecha_inicio')
    if not _puede_gestionar_eventos(request.user):
        qs = qs.exclude(estado='BORRADOR') | qs.filter(estado='BORRADOR', propuesto_por=request.user)
        qs = qs.distinct().order_by('fecha_inicio')

    tipo_filtro = request.GET.get('tipo', '')
    if tipo_filtro:
        qs = qs.filter(tipo=tipo_filtro)

    ahora = timezone.now()
    return render(request, 'dashboard/calendario_eventos.html', {
        'eventos':          qs[:200],
        'tipo_filtro':      tipo_filtro,
        'tipos':            Evento.TIPO_CHOICES,
        'ahora':            ahora,
        'puede_gestionar':  _puede_gestionar_eventos(request.user),
    })


@login_required
def evento_detalle(request, id_evento):
    evento = get_object_or_404(
        Evento.objects.select_related('facultad', 'programa', 'materia', 'propuesto_por', 'aprobado_por'),
        id_evento=id_evento,
    )
    if evento.estado == 'BORRADOR' and not _puede_gestionar_eventos(request.user) and evento.propuesto_por_id != request.user.id_usuario:
        messages.error(request, 'Este evento aún no está publicado.')
        return redirect('calendario_eventos')

    mi_inscripcion = InscripcionEvento.objects.filter(evento=evento, usuario=request.user).first()
    reservas = evento.reservas.select_related('salon__sede').all()
    n_inscritos = evento.inscripciones.filter(estado='INSCRITO').count()
    cupo_lleno = bool(evento.cupo_maximo) and n_inscritos >= evento.cupo_maximo

    inscritos = None
    if _puede_gestionar_eventos(request.user) or (es_docente(request.user) and evento.propuesto_por_id == request.user.id_usuario):
        inscritos = evento.inscripciones.select_related('usuario').order_by('usuario__apellido')

    return render(request, 'dashboard/evento_detalle.html', {
        'evento':          evento,
        'reservas':        reservas,
        'mi_inscripcion':  mi_inscripcion,
        'n_inscritos':     n_inscritos,
        'cupo_lleno':      cupo_lleno,
        'inscritos':       inscritos,
        'puede_gestionar': _puede_gestionar_eventos(request.user),
        'puede_escanear':  _puede_escanear_evento(request.user, evento),
    })


@docente_required
def docente_proponer_evento(request):
    """RF 3.1 -- un Docente propone un evento para una de las materias que
    dicta (criterio de aceptación del Sprint 3). Nace en estado BORRADOR;
    lo publica un Coordinador/Decano/Secretaría vía eventos_gestionar."""
    try:
        docente = Docente.objects.get(usuario=request.user)
    except Docente.DoesNotExist:
        messages.error(request, 'No se encontró perfil de docente.')
        return redirect('dashboard')

    mis_materias = Materia.objects.filter(
        id_materia__in=Horario.objects.filter(docente=docente).values_list('materia_id', flat=True).distinct()
    ).order_by('nombre')

    if request.method == 'POST':
        materia_id = request.POST.get('materia')
        nombre = request.POST.get('nombre', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        modalidad = request.POST.get('modalidad', 'PRESENCIAL')
        fecha_inicio_raw = request.POST.get('fecha_inicio')
        fecha_fin_raw = request.POST.get('fecha_fin')
        cupo_maximo = request.POST.get('cupo_maximo') or None

        if not (nombre and fecha_inicio_raw and fecha_fin_raw):
            messages.error(request, 'Nombre, fecha de inicio y fecha de fin son obligatorios.')
            return redirect('docente_proponer_evento')

        fecha_inicio = _parse_datetime_local_aware(fecha_inicio_raw)
        fecha_fin = _parse_datetime_local_aware(fecha_fin_raw)
        materia_obj = mis_materias.filter(id_materia=materia_id).first() if materia_id else None
        Evento.objects.create(
            nombre=nombre, descripcion=descripcion, tipo='ACADEMICO', modalidad=modalidad,
            materia=materia_obj, programa=materia_obj.programa if materia_obj else None,
            facultad=materia_obj.programa.facultad if materia_obj and materia_obj.programa else None,
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, cupo_maximo=cupo_maximo,
            estado='BORRADOR', propuesto_por=request.user,
        )
        messages.success(request, f'Evento "{nombre}" propuesto. Queda pendiente de aprobación.')
        return redirect('docente_proponer_evento')

    mis_eventos = Evento.objects.filter(propuesto_por=request.user).order_by('-created_at')[:50]
    return render(request, 'dashboard/docente_proponer_evento.html', {
        'mis_materias': mis_materias,
        'mis_eventos':  mis_eventos,
    })


@operacion_required
def eventos_gestionar(request):
    """RF 3.1/3.2 -- Coordinador/Decano/Secretaría/Admin aprueban eventos
    propuestos por Docentes y pueden crear eventos propios directamente,
    con reserva de salón (choque validado con la misma lógica de horarios)."""
    estado_filtro = request.GET.get('estado', 'BORRADOR')
    qs = Evento.objects.select_related('materia', 'propuesto_por').order_by('-created_at')
    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        tipo = request.POST.get('tipo')
        modalidad = request.POST.get('modalidad', 'PRESENCIAL')
        fecha_inicio_raw = request.POST.get('fecha_inicio')
        fecha_fin_raw = request.POST.get('fecha_fin')
        cupo_maximo = request.POST.get('cupo_maximo') or None
        salon_id = request.POST.get('salon')

        if not (nombre and tipo and fecha_inicio_raw and fecha_fin_raw):
            messages.error(request, 'Nombre, tipo y fechas son obligatorios.')
            return redirect('eventos_gestionar')

        fecha_inicio = _parse_datetime_local_aware(fecha_inicio_raw)
        fecha_fin = _parse_datetime_local_aware(fecha_fin_raw)

        evento = Evento.objects.create(
            nombre=nombre, tipo=tipo, modalidad=modalidad,
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, cupo_maximo=cupo_maximo,
            estado='PUBLICADO', propuesto_por=request.user, aprobado_por=request.user, fecha_aprobacion=timezone.now(),
        )
        if salon_id:
            salon = get_object_or_404(Salon, id_salon=salon_id)
            if _hay_conflicto_reserva(salon, fecha_inicio, fecha_fin):
                messages.warning(request, f'Evento creado, pero el salón {salon.codigo} ya tiene otra reserva en ese horario -- revisa la reserva manualmente.')
            else:
                ReservaRecurso.objects.create(
                    evento=evento, salon=salon, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                    estado='CONFIRMADA', solicitado_por=request.user,
                )
        messages.success(request, f'Evento "{nombre}" creado y publicado.')
        return redirect('eventos_gestionar')

    return render(request, 'dashboard/eventos_gestionar.html', {
        'eventos':       qs[:200],
        'estado_filtro': estado_filtro,
        'estados':       Evento.ESTADO_CHOICES,
        'tipos':         Evento.TIPO_CHOICES,
        'salones':       Salon.objects.filter(activo=True).select_related('sede').order_by('sede__nombre', 'codigo'),
    })


@operacion_required
@require_http_methods(['POST'])
def evento_resolver(request, id_evento):
    evento = get_object_or_404(Evento, id_evento=id_evento)
    accion = request.POST.get('accion')
    if accion not in ('aprobar', 'rechazar'):
        messages.error(request, 'Acción inválida.')
        return redirect('eventos_gestionar')
    if evento.estado != 'BORRADOR':
        messages.warning(request, 'Ese evento ya fue resuelto.')
        return redirect('eventos_gestionar')

    if accion == 'aprobar':
        evento.estado = 'PUBLICADO'
        evento.aprobado_por = request.user
        evento.fecha_aprobacion = timezone.now()
        evento.save(update_fields=['estado', 'aprobado_por', 'fecha_aprobacion'])
        messages.success(request, f'Evento "{evento.nombre}" aprobado y publicado.')
    else:
        evento.estado = 'CANCELADO'
        evento.save(update_fields=['estado'])
        messages.success(request, f'Evento "{evento.nombre}" rechazado.')
    return redirect('eventos_gestionar')


@login_required
@require_http_methods(['POST'])
def evento_inscribirse(request, id_evento):
    evento = get_object_or_404(Evento, id_evento=id_evento)
    if evento.estado not in ('PUBLICADO', 'EN_CURSO'):
        messages.error(request, 'Este evento no admite inscripciones en su estado actual.')
        return redirect('evento_detalle', id_evento=id_evento)

    inscripcion, creada = InscripcionEvento.objects.get_or_create(
        evento=evento, usuario=request.user, defaults={'estado': 'INSCRITO'},
    )
    if not creada and inscripcion.estado == 'CANCELADO':
        inscripcion.estado = 'INSCRITO'
        inscripcion.save(update_fields=['estado'])
        creada = True

    if creada:
        n_inscritos = evento.inscripciones.filter(estado='INSCRITO').count()
        if evento.cupo_maximo and n_inscritos > evento.cupo_maximo:
            inscripcion.estado = 'LISTA_ESPERA'
            inscripcion.save(update_fields=['estado'])
            messages.warning(request, 'Cupo lleno -- quedaste en lista de espera.')
        else:
            messages.success(request, f'Te inscribiste a "{evento.nombre}". Tu código QR ya está disponible.')
    else:
        messages.info(request, 'Ya estabas inscrito a este evento.')
    return redirect('evento_detalle', id_evento=id_evento)


@login_required
def mis_inscripciones_eventos(request):
    """RF 3.3 -- listado de inscripciones propias con acceso al QR y,
    para eventos ya finalizados con asistencia registrada, al certificado."""
    inscripciones = InscripcionEvento.objects.filter(usuario=request.user).select_related('evento').order_by('-fecha_inscripcion')
    for insc in inscripciones:
        insc.asistio = insc.asistencias.filter(direccion='IN').exists()
        insc.tiene_certificado = hasattr(insc, 'certificado')
    return render(request, 'dashboard/mis_inscripciones_eventos.html', {'inscripciones': inscripciones})


@login_required
def inscripcion_qr_imagen(request, id_inscripcion):
    """Devuelve el PNG del QR de una inscripción. Solo el propio inscrito
    o quien pueda gestionar/escanear eventos puede verlo."""
    inscripcion = get_object_or_404(InscripcionEvento.objects.select_related('evento'), id_inscripcion=id_inscripcion)
    if inscripcion.usuario_id != request.user.id_usuario and not _puede_escanear_evento(request.user, inscripcion.evento):
        raise Http404()
    png = _generar_qr_png(inscripcion.token_qr)
    return HttpResponse(png, content_type='image/png')


@login_required
def evento_escanear_qr(request, id_evento):
    """RF 3.3 -- registro de asistencia por escaneo de QR (criterio de
    aceptación del Sprint 3: 'un escaneo de prueba registra
    AsistenciaEvento(direccion=IN)'). La dirección se resuelve sola: la
    última fila por inscripción decide si el próximo escaneo es entrada o
    salida (mismo patrón de attendance-system)."""
    evento = get_object_or_404(Evento, id_evento=id_evento)
    if not _puede_escanear_evento(request.user, evento):
        messages.error(request, 'No tienes permiso para escanear asistencia de este evento.')
        return redirect('evento_detalle', id_evento=id_evento)

    ultimos_escaneos = AsistenciaEvento.objects.filter(inscripcion__evento=evento).select_related('inscripcion__usuario').order_by('-timestamp')[:20]

    if request.method == 'POST':
        token = request.POST.get('token_qr', '').strip()
        try:
            inscripcion = InscripcionEvento.objects.get(evento=evento, token_qr=token)
        except (InscripcionEvento.DoesNotExist, ValueError, ValidationError):
            messages.error(request, 'Código QR no reconocido para este evento.')
            return redirect('evento_escanear_qr', id_evento=id_evento)

        if inscripcion.estado == 'CANCELADO':
            messages.error(request, 'Esta inscripción fue cancelada.')
            return redirect('evento_escanear_qr', id_evento=id_evento)

        ultima = inscripcion.asistencias.order_by('-timestamp').first()
        direccion = 'OUT' if (ultima and ultima.direccion == 'IN') else 'IN'
        AsistenciaEvento.objects.create(
            inscripcion=inscripcion, direccion=direccion, timestamp=timezone.now(), escaneado_por=request.user,
        )
        messages.success(request, f'{inscripcion.usuario.nombre_completo}: {"Entrada" if direccion == "IN" else "Salida"} registrada.')
        return redirect('evento_escanear_qr', id_evento=id_evento)

    return render(request, 'dashboard/evento_escanear_qr.html', {
        'evento':           evento,
        'ultimos_escaneos': ultimos_escaneos,
    })


@operacion_required
def evento_certificados(request, id_evento):
    """RF 3.4 -- emisión de certificados para inscritos que sí asistieron
    (al menos un AsistenciaEvento con direccion='IN'). El PDF se genera al
    vuelo en certificado_descargar; aquí solo se crea el registro."""
    evento = get_object_or_404(Evento, id_evento=id_evento)
    inscripciones = InscripcionEvento.objects.filter(evento=evento, estado='INSCRITO').select_related('usuario').order_by('usuario__apellido')
    for insc in inscripciones:
        insc.asistio = insc.asistencias.filter(direccion='IN').exists()
        insc.certificado_existente = getattr(insc, 'certificado', None)

    if request.method == 'POST':
        id_inscripcion = request.POST.get('id_inscripcion')
        tipo = request.POST.get('tipo', 'ASISTENCIA')
        insc = get_object_or_404(InscripcionEvento, id_inscripcion=id_inscripcion, evento=evento)
        if not insc.asistencias.filter(direccion='IN').exists():
            messages.error(request, f'{insc.usuario.nombre_completo} no registra asistencia (IN) a este evento -- no se puede emitir certificado.')
            return redirect('evento_certificados', id_evento=id_evento)

        Certificado.objects.update_or_create(
            inscripcion=insc,
            defaults={'tipo': tipo, 'pdf_generado': True, 'fecha_emision': timezone.now(), 'emitido_por': request.user},
        )
        messages.success(request, f'Certificado emitido para {insc.usuario.nombre_completo}.')
        return redirect('evento_certificados', id_evento=id_evento)

    return render(request, 'dashboard/evento_certificados.html', {
        'evento':        evento,
        'inscripciones': inscripciones,
        'tipos':         Certificado.TIPO_CHOICES,
    })


@login_required
def certificado_descargar(request, id_certificado):
    """Genera el PDF del certificado al vuelo con
    _construir_pdf_generico_politecnico + el QR de codigo_verificacion.
    Solo el propio dueño de la inscripción o quien pueda gestionar
    eventos puede descargarlo."""
    certificado = get_object_or_404(
        Certificado.objects.select_related('inscripcion__usuario', 'inscripcion__evento'),
        id_certificado=id_certificado,
    )
    inscripcion = certificado.inscripcion
    if inscripcion.usuario_id != request.user.id_usuario and not _puede_gestionar_eventos(request.user):
        raise Http404()

    evento = inscripcion.evento
    titular = _titular_desde_request_siihapi(request) if inscripcion.usuario_id == request.user.id_usuario else {
        'nombre': inscripcion.usuario.nombre_completo.upper(), 'doc_ident': '—', 'periodo': '2026-2T', 'centro': '',
    }
    columnas = ['Evento', 'Tipo', 'Fecha', 'Modalidad']
    filas = [(evento.nombre, certificado.get_tipo_display(), f'{evento.fecha_inicio:%d/%m/%Y}', evento.get_modalidad_display())]
    qr_png = _generar_qr_png(certificado.codigo_verificacion)

    pdf_bytes = _construir_pdf_generico_politecnico(
        titulo=f'CONSTANCIA DE {certificado.get_tipo_display().upper()}',
        subtitulo=evento.nombre,
        columnas=columnas, filas=filas, titular=titular, imagen_qr_bytes=qr_png,
    )
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="certificado_{certificado.id_certificado}.pdf"'
    return resp
