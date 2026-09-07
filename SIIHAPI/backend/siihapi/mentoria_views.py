"""
SIIHAPI · Vistas de apps.mentoria (Sprint 4, 2026-09-06).

Archivo nuevo, mismo criterio que decano_views.py. Bienestar Académico
deriva un CasoBienestar hacia un mentor (crea la AsignacionMentoria);
Mentoría gestiona sus propias sesiones y bitácoras -- por eso la creación
de la asignación se gatea con bienestar_required y el resto con
mentoria_required (ambos ya existentes desde Sprint 2, siihapi/permisos.py).
"""
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from apps.matriculas.models import Estudiante
from apps.bienestar.models import CasoBienestar
from apps.autenticacion.models import Usuario
from apps.infraestructura.models import Salon
from apps.mentoria.models import AsignacionMentoria, SesionMentoria, BitacoraMentoria

from .permisos import bienestar_required, mentoria_required


@mentoria_required
def mentoria_dashboard(request):
    """El mentor ve solo sus asignaciones; Admin ve todas (mismo patron
    que docente_mi_horario/estudiante_mi_horario: filtrar por el usuario
    autenticado salvo que sea Admin)."""
    asignaciones = AsignacionMentoria.objects.select_related('estudiante__usuario', 'mentor', 'caso_bienestar_origen')
    if request.user.rol not in ('ADMIN', 'ADMINISTRADOR'):
        asignaciones = asignaciones.filter(mentor=request.user)
    asignaciones = asignaciones.order_by('-fecha_inicio')

    proximas_sesiones = SesionMentoria.objects.select_related('asignacion__estudiante__usuario').filter(
        estado='PROGRAMADA', fecha_hora_inicio__gte=timezone.now(),
    )
    if request.user.rol not in ('ADMIN', 'ADMINISTRADOR'):
        proximas_sesiones = proximas_sesiones.filter(asignacion__mentor=request.user)
    proximas_sesiones = proximas_sesiones.order_by('fecha_hora_inicio')[:10]

    return render(request, 'dashboard/mentoria_dashboard.html', {
        'asignaciones': asignaciones,
        'proximas_sesiones': proximas_sesiones,
    })


@bienestar_required
def asignacion_mentoria_crear(request):
    if request.method == 'POST':
        try:
            estudiante = get_object_or_404(Estudiante, usuario_id=request.POST.get('estudiante'))
            mentor = get_object_or_404(Usuario, pk=request.POST.get('mentor'), rol__in=['MENTORIAS', 'ADMIN', 'ADMINISTRADOR'])
            caso_id = request.POST.get('caso_bienestar_origen')
            caso = CasoBienestar.objects.filter(id_caso=caso_id).first() if caso_id else None
            asignacion = AsignacionMentoria.objects.create(
                estudiante=estudiante, mentor=mentor, caso_bienestar_origen=caso,
                fecha_inicio=timezone.localdate(), asignado_por=request.user,
            )
            if caso:
                caso.estado = 'DERIVADO'
                caso.save(update_fields=['estado'])
            messages.success(request, 'Estudiante derivado a Mentoría.')
            return redirect('asignacion_mentoria_detalle', asignacion.id_asignacion)
        except Exception as exc:
            messages.error(request, f'No se pudo crear la asignación: {str(exc)[:200]}')
    return render(request, 'dashboard/asignacion_mentoria_form.html', {
        'casos_sin_mentor': CasoBienestar.objects.filter(estado__in=['ABIERTO', 'EN_ATENCION']).select_related('estudiante__usuario'),
        'mentores': Usuario.objects.filter(rol='MENTORIAS', is_active=True),
    })


@mentoria_required
def asignacion_mentoria_detalle(request, id_asignacion):
    asignacion = get_object_or_404(
        AsignacionMentoria.objects.select_related('estudiante__usuario', 'mentor', 'caso_bienestar_origen'),
        id_asignacion=id_asignacion,
    )
    if request.user.rol not in ('ADMIN', 'ADMINISTRADOR') and asignacion.mentor_id != request.user.pk:
        messages.error(request, 'No tienes acceso a esta asignación.')
        return redirect('mentoria_dashboard')
    sesiones = asignacion.sesiones.select_related('salon', 'bitacora').order_by('-fecha_hora_inicio')
    return render(request, 'dashboard/asignacion_mentoria_detalle.html', {
        'asignacion': asignacion,
        'sesiones': sesiones,
        'salones': Salon.objects.filter(activo=True).select_related('sede'),
    })


@mentoria_required
def sesion_mentoria_crear(request, id_asignacion):
    asignacion = get_object_or_404(AsignacionMentoria, id_asignacion=id_asignacion)
    if request.user.rol not in ('ADMIN', 'ADMINISTRADOR') and asignacion.mentor_id != request.user.pk:
        messages.error(request, 'No tienes acceso a esta asignación.')
        return redirect('mentoria_dashboard')
    if request.method == 'POST':
        try:
            salon_id = request.POST.get('salon')
            salon = Salon.objects.filter(id_salon=salon_id).first() if salon_id else None
            SesionMentoria.objects.create(
                asignacion=asignacion,
                fecha_hora_inicio=fv_parse_datetime_local(request.POST.get('fecha_hora_inicio')),
                fecha_hora_fin=fv_parse_datetime_local(request.POST.get('fecha_hora_fin')),
                modalidad=request.POST.get('modalidad', 'PRESENCIAL'),
                salon=salon,
            )
            messages.success(request, 'Sesión de mentoría programada.')
        except Exception as exc:
            messages.error(request, f'No se pudo programar la sesión: {str(exc)[:200]}')
    return redirect('asignacion_mentoria_detalle', id_asignacion)


def fv_parse_datetime_local(valor):
    """Mismo helper que frontend_views._parse_datetime_local_aware (Sprint
    3) -- se reimporta perezosamente para no crear un ciclo de import a
    nivel de módulo entre frontend_views y este archivo."""
    from .frontend_views import _parse_datetime_local_aware
    return _parse_datetime_local_aware(valor)


@mentoria_required
def sesion_mentoria_actualizar_estado(request, id_sesion):
    sesion = get_object_or_404(SesionMentoria.objects.select_related('asignacion'), id_sesion=id_sesion)
    if request.user.rol not in ('ADMIN', 'ADMINISTRADOR') and sesion.asignacion.mentor_id != request.user.pk:
        messages.error(request, 'No tienes acceso a esta sesión.')
        return redirect('mentoria_dashboard')
    nuevo_estado = request.POST.get('estado')
    if request.method == 'POST' and nuevo_estado in dict(SesionMentoria.ESTADO_CHOICES):
        sesion.estado = nuevo_estado
        sesion.save(update_fields=['estado'])
        messages.success(request, 'Estado de la sesión actualizado.')
    return redirect('asignacion_mentoria_detalle', sesion.asignacion_id)


@mentoria_required
def bitacora_mentoria_crear(request, id_sesion):
    sesion = get_object_or_404(SesionMentoria.objects.select_related('asignacion'), id_sesion=id_sesion)
    if request.user.rol not in ('ADMIN', 'ADMINISTRADOR') and sesion.asignacion.mentor_id != request.user.pk:
        messages.error(request, 'No tienes acceso a esta sesión.')
        return redirect('mentoria_dashboard')
    bitacora = getattr(sesion, 'bitacora', None)
    if request.method == 'POST':
        try:
            if bitacora:
                bitacora.resumen = request.POST.get('resumen', '')
                bitacora.progreso_academico = request.POST.get('progreso_academico') or None
                bitacora.progreso_personal_notas = request.POST.get('progreso_personal_notas', '')
                bitacora.save()
            else:
                BitacoraMentoria.objects.create(
                    sesion=sesion,
                    resumen=request.POST.get('resumen', ''),
                    progreso_academico=request.POST.get('progreso_academico') or None,
                    progreso_personal_notas=request.POST.get('progreso_personal_notas', ''),
                    registrado_por=request.user,
                )
                if sesion.estado == 'PROGRAMADA':
                    sesion.estado = 'REALIZADA'
                    sesion.save(update_fields=['estado'])
            messages.success(request, 'Bitácora guardada.')
            return redirect('asignacion_mentoria_detalle', sesion.asignacion_id)
        except Exception as exc:
            messages.error(request, f'No se pudo guardar la bitácora: {str(exc)[:200]}')
    return render(request, 'dashboard/bitacora_mentoria_form.html', {'sesion': sesion, 'bitacora': bitacora})
