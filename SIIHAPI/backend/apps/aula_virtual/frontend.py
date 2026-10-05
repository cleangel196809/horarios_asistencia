"""
SIIHAPI · apps/aula_virtual — vistas HTML (iframe de Jitsi).

Son las dos páginas que el usuario abre desde el dashboard; toda la
lógica de negocio sigue en `views.py` (API REST) y aquí sólo se renderiza.
Se registran en `siihapi/urls.py` bajo /dashboard/aula-virtual/.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.contrib import messages
from django.utils import timezone

from .models import CanalVirtual, ParticipanteSesion, SesionVirtual
from .views import _es_staff, _puede_ver_canal


@login_required
def mis_canales(request):
    """Lista de canales visibles para el usuario (mismo criterio que la API)."""
    from apps.matriculas.models import Matricula
    from django.db.models import Q

    qs = CanalVirtual.objects.select_related('materia', 'docente__usuario', 'periodo')
    if not _es_staff(request.user):
        materias = Matricula.objects.filter(
            estudiante__usuario_id=request.user.id_usuario,
            estado__in=('ACTIVA', 'INSCRITA'),
        ).values_list('materia_id', flat=True)
        qs = qs.filter(Q(docente_id=request.user.id_usuario) | Q(materia_id__in=materias))

    return render(request, 'dashboard/aula_virtual_canales.html', {
        'canales': qs.filter(activo=True)[:200],
        'es_staff': _es_staff(request.user),
    })


@login_required
def sala_sesion(request, id_sesion):
    """Página con el iframe de Jitsi para una sesión concreta.

    Entrar por aquí cuenta como asistencia: se registra el
    `ParticipanteSesion` igual que en el endpoint `unirme`, para que la
    consolidación hacia SISCA no dependa de que el navegador llame a la
    API por separado.
    """
    sesion = SesionVirtual.objects.select_related(
        'canal__materia', 'canal__docente__usuario').filter(pk=id_sesion).first()
    if not sesion:
        messages.error(request, 'La sesión no existe.')
        return redirect('aula_virtual_canales')
    if not _puede_ver_canal(request.user, sesion.canal):
        messages.error(request, 'No tienes acceso a esta clase virtual.')
        return redirect('dashboard')
    if sesion.estado in ('FINALIZADA', 'CANCELADA'):
        messages.error(request, f'La clase está {sesion.get_estado_display().lower()}.')
        return redirect('aula_virtual_canales')

    ahora = timezone.now()
    if sesion.estado == 'PROGRAMADA':
        sesion.estado = 'EN_CURSO'
        sesion.save(update_fields=['estado'])
    participante, creado = ParticipanteSesion.objects.get_or_create(
        sesion=sesion, usuario=request.user, defaults={'hora_entrada': ahora})
    if not creado and participante.hora_salida is not None:
        participante.hora_salida = None
        participante.save(update_fields=['hora_salida'])

    return render(request, 'dashboard/aula_virtual_sala.html', {
        'sesion': sesion,
        'canal': sesion.canal,
        'url_jitsi': sesion.url_jitsi,
        'puede_cerrar': _es_staff(request.user) or sesion.canal.docente_id == request.user.id_usuario,
    })
