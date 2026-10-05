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
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

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

    es_staff = _es_staff(request.user)
    canales = list(qs.filter(activo=True)[:200])

    # Quien puede gestionar cada canal ve dentro de su tarjeta el
    # formulario para programar una clase. Se marca aquí y no en la
    # plantilla porque el criterio es el mismo de la API.
    from .views import _puede_gestionar_canal
    for canal in canales:
        canal.puede_gestionar = _puede_gestionar_canal(request.user, canal)

    docente = _mi_docente(request.user)
    puede_crear = es_staff or docente is not None

    materias = periodos = docentes = []
    if puede_crear:
        from apps.academico.models import Materia
        from apps.matriculas.models import Periodo
        materias = Materia.objects.filter(activa=True).order_by('codigo')[:300]
        periodos = Periodo.objects.order_by('-fecha_inicio')[:10]
        if es_staff:
            from apps.personal.models import Docente
            docentes = (Docente.objects.select_related('usuario')
                        .order_by('usuario__nombre', 'usuario__apellido')[:300])

    return render(request, 'dashboard/aula_virtual_canales.html', {
        'canales': canales,
        'es_staff': es_staff,
        'puede_crear': puede_crear,
        'materias': materias,
        'periodos': periodos,
        'docentes': docentes,
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


# ════════════════════════════════════════════════════════════
#  Creación desde el dashboard (formularios HTML)
#
#  La API REST de `views.py` sigue siendo la fuente de verdad; estas dos
#  vistas sólo existen para que un docente pueda crear su canal y
#  programar una clase desde el navegador, sin pasar por el admin de
#  Django ni por un cliente REST. Reutilizan exactamente los mismos
#  chequeos de permisos que la API (`_es_staff`, `_puede_gestionar_canal`).
# ════════════════════════════════════════════════════════════
def _mi_docente(user):
    from apps.personal.models import Docente
    return Docente.objects.filter(pk=user.id_usuario).first()


@login_required
@require_POST
def crear_canal_form(request):
    """POST /dashboard/aula-virtual/crear/ — crea un canal y vuelve a la lista."""
    from apps.academico.models import Materia
    from apps.matriculas.models import Periodo

    es_staff = _es_staff(request.user)
    if es_staff:
        docente = _mi_docente_por_id(request.POST.get('docente'))
        if not docente:
            messages.error(request, 'Elige el docente responsable del canal.')
            return redirect('aula_virtual_canales')
    else:
        docente = _mi_docente(request.user)
        if not docente:
            messages.error(request, 'Sólo un docente con perfil puede crear un canal virtual.')
            return redirect('aula_virtual_canales')

    materia = Materia.objects.filter(pk=request.POST.get('materia')).first()
    if not materia:
        messages.error(request, 'Elige una materia válida.')
        return redirect('aula_virtual_canales')

    nombre = (request.POST.get('nombre') or '').strip()
    if not nombre:
        messages.error(request, 'El canal necesita un nombre.')
        return redirect('aula_virtual_canales')

    periodo = Periodo.objects.filter(pk=request.POST.get('periodo')).first()
    canal = CanalVirtual.objects.create(
        materia=materia,
        docente=docente,
        periodo=periodo,
        nombre=nombre[:150],
        descripcion=(request.POST.get('descripcion') or '').strip(),
    )
    messages.success(request, f'Canal «{canal.nombre}» creado. Ahora programa una clase.')
    return redirect('aula_virtual_canales')


def _mi_docente_por_id(valor):
    from apps.personal.models import Docente
    if not valor:
        return None
    return Docente.objects.filter(pk=valor).first()


@login_required
@require_POST
def crear_sesion_form(request, id_canal):
    """POST /dashboard/aula-virtual/<id_canal>/clase/ — programa una clase."""
    from .views import _puede_gestionar_canal

    canal = CanalVirtual.objects.filter(pk=id_canal).first()
    if not canal:
        messages.error(request, 'El canal no existe.')
        return redirect('aula_virtual_canales')
    if not _puede_gestionar_canal(request.user, canal):
        messages.error(request, 'No puedes programar clases en este canal.')
        return redirect('aula_virtual_canales')

    titulo = (request.POST.get('titulo') or '').strip()
    if not titulo:
        messages.error(request, 'La clase necesita un título.')
        return redirect('aula_virtual_canales')

    # <input type="datetime-local"> entrega 'YYYY-MM-DDTHH:MM' sin zona;
    # se interpreta en la zona del proyecto, no en UTC, o la clase
    # aparecería desplazada varias horas en el listado.
    crudo = (request.POST.get('fecha_inicio') or '').strip()
    fecha = parse_datetime(crudo) if crudo else None
    if fecha is None:
        messages.error(request, 'Indica la fecha y hora de inicio.')
        return redirect('aula_virtual_canales')
    if timezone.is_naive(fecha):
        fecha = timezone.make_aware(fecha, timezone.get_current_timezone())

    try:
        duracion = int(request.POST.get('duracion_minutos') or 60)
    except (TypeError, ValueError):
        duracion = 60
    duracion = max(5, min(duracion, 600))

    sesion = SesionVirtual.objects.create(
        canal=canal, titulo=titulo[:200], fecha_inicio=fecha, duracion_minutos=duracion)
    messages.success(request, f'Clase «{sesion.titulo}» programada.')
    return redirect('aula_virtual_canales')
