"""
SIIHAPI · apps/aula_virtual — API REST (modularización, 2026-10-05).

Mismo estilo que `apps/infraestructura/views.py`: vistas de función con
`@api_view` y respuesta `{'success', 'total', 'data'}`.

Quién ve qué (`_puede_ver_canal`): el docente dueño del canal, el staff
(Admin/Coordinador/Decano/Secretaría) y los estudiantes MATRICULADOS en
esa materia. La verificación de matrícula importa de verdad aquí: la sala
de Jitsi es pública para quien tenga la URL, así que exponer `url_jitsi` a
cualquier usuario autenticado equivaldría a dejar la clase abierta.
"""
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import CanalVirtual, ParticipanteSesion, RecursoCanal, SesionVirtual
from .serializers import (
    CanalVirtualSerializer, ParticipanteSesionSerializer, RecursoCanalSerializer,
    SesionVirtualSerializer,
)

log = logging.getLogger(__name__)

LIMITE_LISTADO = 300

# La página HTML de la sala (ver frontend.py / aula_virtual_sala.html) llama
# a estos mismos endpoints desde el navegador con la cookie de sesión, no con
# un JWT. Por eso aquí se acepta SessionAuthentication ADEMÁS del JWT por
# defecto -- sólo en esta app, para no cambiar el comportamiento (ni las
# pruebas de 401) del resto de la API, que es JWT puro. SessionAuthentication
# exige CSRF, que la plantilla ya envía en X-CSRFToken.
AUTENTICACION = [JWTAuthentication, SessionAuthentication]


# ════════════════════════════════════════════════════════════
#  Permisos
# ════════════════════════════════════════════════════════════
def _es_staff(user):
    """Admin/Coordinador reales — excluye Bienestar y Mentorías, que son
    roles de solo consulta (mismo criterio que permisos.operacion_required)."""
    from siihapi.permisos import es_solo_consulta
    return (user.is_authenticated
            and user.rol_efectivo in ('ADMINISTRADOR', 'COORDINADOR')
            and not es_solo_consulta(user))


def _es_dueno(user, canal):
    return user.is_authenticated and canal.docente_id == user.id_usuario


def _esta_matriculado(user, canal):
    from apps.matriculas.models import Matricula
    return Matricula.objects.filter(
        estudiante__usuario_id=user.id_usuario,
        materia_id=canal.materia_id,
        estado__in=('ACTIVA', 'INSCRITA'),
    ).exists()


def _puede_ver_canal(user, canal):
    return _es_staff(user) or _es_dueno(user, canal) or _esta_matriculado(user, canal)


def _puede_gestionar_canal(user, canal):
    """Crear sesiones, publicar recursos y cerrar clases: sólo el docente
    dueño o el staff. Un estudiante matriculado puede entrar, no organizar."""
    return _es_staff(user) or _es_dueno(user, canal)


def _denegado(detalle='No tienes acceso a este canal.'):
    return Response({'success': False, 'error': detalle}, status=403)


def _no_encontrado(detalle='Recurso no encontrado.'):
    return Response({'success': False, 'error': detalle}, status=404)


def _get_canal(id_canal):
    return CanalVirtual.objects.select_related(
        'materia', 'docente__usuario', 'periodo').filter(pk=id_canal).first()


# ════════════════════════════════════════════════════════════
#  Ping
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([AllowAny])
def ping(request):
    return Response({'app': 'aula_virtual', 'status': 'ok'})


# ════════════════════════════════════════════════════════════
#  Canales
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def listar_canales(request):
    """GET /api/aula-virtual/canales/ · filtros: materia, periodo, activo.

    Devuelve sólo los canales que el usuario puede ver. El filtrado se
    hace en la consulta (no en Python) para no traer la tabla entera.
    """
    from apps.matriculas.models import Matricula

    qs = CanalVirtual.objects.select_related('materia', 'docente__usuario', 'periodo')

    if not _es_staff(request.user):
        from django.db.models import Q
        materias_matriculadas = Matricula.objects.filter(
            estudiante__usuario_id=request.user.id_usuario,
            estado__in=('ACTIVA', 'INSCRITA'),
        ).values_list('materia_id', flat=True)
        qs = qs.filter(
            Q(docente_id=request.user.id_usuario) | Q(materia_id__in=materias_matriculadas))

    materia = request.GET.get('materia')
    periodo = request.GET.get('periodo')
    activo = request.GET.get('activo')
    if materia:
        if not str(materia).isdigit():
            return Response({'success': False, 'error': 'materia debe ser un id numérico.'}, status=400)
        qs = qs.filter(materia_id=int(materia))
    if periodo:
        if not str(periodo).isdigit():
            return Response({'success': False, 'error': 'periodo debe ser un id numérico.'}, status=400)
        qs = qs.filter(periodo_id=int(periodo))
    if activo is not None and activo != '':
        qs = qs.filter(activo=str(activo).lower() in ('1', 'true', 'si', 'sí'))

    qs = qs[:LIMITE_LISTADO]
    data = CanalVirtualSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_canal(request):
    """POST /api/aula-virtual/canales/crear/

    Un Docente crea el canal de SU materia; el staff puede crearlo en
    nombre de un docente mandando `docente` en el payload. Nadie más.
    """
    from apps.personal.models import Docente

    es_staff = _es_staff(request.user)
    if es_staff:
        docente_id = request.data.get('docente')
        if not docente_id:
            return Response(
                {'success': False, 'error': 'docente es obligatorio cuando lo crea el staff.'},
                status=400)
        docente = Docente.objects.filter(pk=docente_id).first()
        if not docente:
            return _no_encontrado('Docente no encontrado.')
    else:
        docente = Docente.objects.filter(pk=request.user.id_usuario).first()
        if not docente:
            return _denegado('Sólo un Docente con perfil puede crear un canal virtual.')

    ser = CanalVirtualSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    canal = ser.save(docente=docente)
    log.info('[aula_virtual] canal %s creado por %s', canal.pk, request.user.correo)
    return Response({'success': True, 'data': CanalVirtualSerializer(canal).data}, status=201)


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def detalle_canal(request, id_canal):
    canal = _get_canal(id_canal)
    if not canal:
        return _no_encontrado('Canal no encontrado.')
    if not _puede_ver_canal(request.user, canal):
        return _denegado()
    data = CanalVirtualSerializer(canal).data
    data['recursos'] = RecursoCanalSerializer(canal.recursos.all()[:100], many=True).data
    data['proximas_sesiones'] = SesionVirtualSerializer(
        canal.sesiones.filter(estado__in=('PROGRAMADA', 'EN_CURSO'))[:20], many=True).data
    return Response({'success': True, 'data': data})


# ════════════════════════════════════════════════════════════
#  Recursos del canal
# ════════════════════════════════════════════════════════════
@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_recurso(request, id_canal):
    canal = _get_canal(id_canal)
    if not canal:
        return _no_encontrado('Canal no encontrado.')
    if not _puede_gestionar_canal(request.user, canal):
        return _denegado('Publicar material requiere ser el docente del canal o staff.')

    datos = dict(request.data)
    datos['canal'] = canal.pk
    ser = RecursoCanalSerializer(data=datos)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    recurso = ser.save(canal=canal, publicado_por=request.user)
    return Response({'success': True, 'data': RecursoCanalSerializer(recurso).data}, status=201)


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def listar_recursos(request, id_canal):
    canal = _get_canal(id_canal)
    if not canal:
        return _no_encontrado('Canal no encontrado.')
    if not _puede_ver_canal(request.user, canal):
        return _denegado()
    qs = RecursoCanal.objects.filter(canal=canal)[:LIMITE_LISTADO]
    data = RecursoCanalSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


# ════════════════════════════════════════════════════════════
#  Sesiones
# ════════════════════════════════════════════════════════════
@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_sesion(request, id_canal):
    canal = _get_canal(id_canal)
    if not canal:
        return _no_encontrado('Canal no encontrado.')
    if not _puede_gestionar_canal(request.user, canal):
        return _denegado('Programar una clase requiere ser el docente del canal o staff.')
    if not canal.activo:
        return Response({'success': False, 'error': 'El canal está inactivo.'}, status=409)

    datos = dict(request.data)
    datos['canal'] = canal.pk
    ser = SesionVirtualSerializer(data=datos)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    sesion = ser.save(canal=canal, estado='PROGRAMADA')
    return Response({'success': True, 'data': SesionVirtualSerializer(sesion).data}, status=201)


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def listar_sesiones(request, id_canal):
    canal = _get_canal(id_canal)
    if not canal:
        return _no_encontrado('Canal no encontrado.')
    if not _puede_ver_canal(request.user, canal):
        return _denegado()
    qs = SesionVirtual.objects.filter(canal=canal).select_related('canal__materia')
    estado = request.GET.get('estado')
    if estado:
        if estado not in dict(SesionVirtual.ESTADO_CHOICES):
            return Response({'success': False, 'error': f'estado inválido: {estado}'}, status=400)
        qs = qs.filter(estado=estado)
    qs = qs[:LIMITE_LISTADO]
    data = SesionVirtualSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def unirse_sesion(request, id_sesion):
    """POST /api/aula-virtual/sesiones/<id>/unirme/

    Registra la entrada y devuelve la URL de Jitsi. Reentrar en la misma
    clase NO crea una segunda fila: se limpia `hora_salida` (el usuario
    volvió a estar dentro) y se conserva la entrada original.
    """
    sesion = SesionVirtual.objects.select_related(
        'canal__materia', 'canal__docente__usuario').filter(pk=id_sesion).first()
    if not sesion:
        return _no_encontrado('Sesión no encontrada.')
    if not _puede_ver_canal(request.user, sesion.canal):
        return _denegado()
    if sesion.estado in ('FINALIZADA', 'CANCELADA'):
        return Response({
            'success': False,
            'error': f'La sesión está {sesion.get_estado_display().lower()}.',
        }, status=409)

    ahora = timezone.now()
    with transaction.atomic():
        if sesion.estado == 'PROGRAMADA':
            sesion.estado = 'EN_CURSO'
            sesion.save(update_fields=['estado'])
        participante, creado = ParticipanteSesion.objects.get_or_create(
            sesion=sesion, usuario=request.user,
            defaults={'hora_entrada': ahora},
        )
        if not creado and participante.hora_salida is not None:
            participante.hora_salida = None
            participante.save(update_fields=['hora_salida'])

    return Response({'success': True, 'data': {
        'sesion': SesionVirtualSerializer(sesion).data,
        'participante': ParticipanteSesionSerializer(participante).data,
        'url_jitsi': sesion.url_jitsi,
    }}, status=201 if creado else 200)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def salir_sesion(request, id_sesion):
    """POST /api/aula-virtual/sesiones/<id>/salir/ · marca la hora de salida."""
    participante = ParticipanteSesion.objects.filter(
        sesion_id=id_sesion, usuario=request.user).first()
    if not participante:
        return _no_encontrado('No estás registrado en esta sesión.')

    ahora = timezone.now()
    participante.hora_salida = ahora
    participante.minutos_acumulados = _minutos(participante.hora_entrada, ahora)
    participante.save(update_fields=['hora_salida', 'minutos_acumulados'])
    return Response({'success': True, 'data': ParticipanteSesionSerializer(participante).data})


def _minutos(entrada, salida) -> int:
    """Minutos entre dos marcas, nunca negativo (un reloj desfasado no
    puede producir asistencia negativa)."""
    if not entrada or not salida:
        return 0
    return max(int((salida - entrada).total_seconds() // 60), 0)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def cerrar_sesion_virtual(request, id_sesion):
    """POST /api/aula-virtual/sesiones/<id>/cerrar/

    Cierra la clase, consolida los minutos de cada participante y envía la
    asistencia a SISCA. El envío NO puede tumbar el cierre: si SISCA está
    caído (o el circuit breaker abierto) la sesión queda cerrada igual, con
    `sincronizada_sisca=False`, y se reintenta después.
    """
    sesion = SesionVirtual.objects.select_related(
        'canal__materia', 'canal__docente__usuario', 'canal__periodo').filter(pk=id_sesion).first()
    if not sesion:
        return _no_encontrado('Sesión no encontrada.')
    if not _puede_gestionar_canal(request.user, sesion.canal):
        return _denegado('Cerrar la clase requiere ser el docente del canal o staff.')
    if sesion.estado in ('FINALIZADA', 'CANCELADA'):
        return Response({
            'success': False,
            'error': f'La sesión ya está {sesion.get_estado_display().lower()}.',
        }, status=409)

    ahora = timezone.now()
    with transaction.atomic():
        for p in sesion.participantes.all():
            # A quien nunca marcó salida se le cierra en el momento del
            # cierre de la clase, no se le descarta: estuvo hasta el final.
            if p.hora_salida is None:
                p.hora_salida = ahora
            p.minutos_acumulados = _minutos(p.hora_entrada, p.hora_salida)
            p.save(update_fields=['hora_salida', 'minutos_acumulados'])

        sesion.estado = 'FINALIZADA'
        sesion.fecha_cierre = ahora
        sesion.cerrada_por = request.user
        sesion.save(update_fields=['estado', 'fecha_cierre', 'cerrada_por'])

    from .sisca_sync import enviar_asistencia
    ok, detalle = enviar_asistencia(sesion)

    sesion.refresh_from_db()
    return Response({'success': True, 'data': {
        'sesion': SesionVirtualSerializer(sesion).data,
        'sincronizacion_sisca': {'enviada': ok, 'detalle': detalle},
    }})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def reintentar_sincronizacion(request, id_sesion):
    """POST /api/aula-virtual/sesiones/<id>/reintentar-sisca/

    Reenvía a SISCA la asistencia de una sesión ya cerrada que quedó sin
    sincronizar. Sirve para vaciar la cola cuando SISCA vuelve a estar
    arriba, sin tener que reabrir la clase.
    """
    sesion = SesionVirtual.objects.select_related(
        'canal__materia', 'canal__docente__usuario', 'canal__periodo').filter(pk=id_sesion).first()
    if not sesion:
        return _no_encontrado('Sesión no encontrada.')
    if not _puede_gestionar_canal(request.user, sesion.canal):
        return _denegado()
    if sesion.estado != 'FINALIZADA':
        return Response(
            {'success': False, 'error': 'Sólo se reintenta una sesión ya finalizada.'}, status=409)
    if sesion.sincronizada_sisca:
        return Response({'success': True, 'ya_sincronizada': True,
                         'data': SesionVirtualSerializer(sesion).data})

    from .sisca_sync import enviar_asistencia
    ok, detalle = enviar_asistencia(sesion)
    sesion.refresh_from_db()
    return Response({'success': True, 'data': {
        'sesion': SesionVirtualSerializer(sesion).data,
        'sincronizacion_sisca': {'enviada': ok, 'detalle': detalle},
    }})


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def asistencia_sesion(request, id_sesion):
    """GET /api/aula-virtual/sesiones/<id>/asistencia/"""
    sesion = SesionVirtual.objects.select_related('canal').filter(pk=id_sesion).first()
    if not sesion:
        return _no_encontrado('Sesión no encontrada.')
    if not _puede_gestionar_canal(request.user, sesion.canal):
        return _denegado('El listado de asistencia es para el docente del canal o el staff.')

    qs = sesion.participantes.select_related('usuario').all()
    data = ParticipanteSesionSerializer(qs, many=True).data
    umbral = sesion.duracion_minutos / 2
    asistieron = sum(1 for p in qs if p.minutos_acumulados >= umbral)
    total = len(data)
    return Response({
        'success': True,
        'total': total,
        'resumen': {
            'sesion': sesion.titulo,
            'duracion_minutos': sesion.duracion_minutos,
            'participantes': total,
            'asistieron': asistieron,
            'criterio': 'Al menos la mitad de la duración de la clase.',
            'sincronizada_sisca': sesion.sincronizada_sisca,
        },
        'data': data,
    })
