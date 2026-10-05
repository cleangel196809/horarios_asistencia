"""
SIIHAPI · apps/eventos — API REST (modularización, 2026-10-05).

Mismo estilo que `apps/infraestructura/views.py`: vistas de función con
`@api_view`, respuesta `{'success', 'total', 'data'}` y permisos
explícitos por vista.

Esta capa REST convive con el frontend HTML del Sprint 3
(`siihapi/frontend_views.py`): las reglas de negocio que ya existían allí
(conflicto de salón, quién puede gestionar un evento, quién puede escanear)
se IMPORTAN de ahí en vez de reescribirse, para que las dos rutas no puedan
divergir. El import es diferido (dentro de la función) a propósito:
`siihapi.urls` ya carga `frontend_views` al arrancar, y hacerlo a nivel de
módulo crearía un ciclo innecesario entre el paquete del proyecto y la app.
"""
import logging

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import (
    AsistenciaEvento, Evento, InscripcionEvento, ReservaRecurso,
)
from .throttling import EscaneoQRThrottle
from .serializers import (
    AsistenciaEventoSerializer, EventoSerializer, InscripcionEventoSerializer,
    ReservaRecursoSerializer,
)

log = logging.getLogger(__name__)

# Tope defensivo para los listados: el mismo criterio de
# apps/infraestructura/views.py (qs[:500]) -- ningún endpoint devuelve la
# tabla entera aunque el cliente no pagine.
LIMITE_LISTADO = 300


# ════════════════════════════════════════════════════════════
#  Helpers de permisos (una sola fuente de verdad: frontend_views)
# ════════════════════════════════════════════════════════════
def _puede_gestionar(user):
    from siihapi.frontend_views import _puede_gestionar_eventos
    return _puede_gestionar_eventos(user)


def _puede_escanear(user, evento):
    from siihapi.frontend_views import _puede_escanear_evento
    return _puede_escanear_evento(user, evento)


def _denegado(detalle='No tienes permiso para esta operación.'):
    return Response({'success': False, 'error': detalle}, status=403)


def _no_encontrado(detalle='Recurso no encontrado.'):
    return Response({'success': False, 'error': detalle}, status=404)


# ════════════════════════════════════════════════════════════
#  Ping
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    return Response({'app': 'eventos', 'status': 'ok'})


# ════════════════════════════════════════════════════════════
#  Eventos
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_eventos(request):
    """GET /api/eventos/  · filtros: tipo, estado, modalidad, desde, hasta.

    Un usuario sin rol de gestión sólo ve eventos ya publicados (o los que
    él mismo propuso): los borradores ajenos no se filtran en el cliente.
    """
    qs = Evento.objects.select_related('propuesto_por', 'facultad', 'programa', 'materia')

    if not _puede_gestionar(request.user):
        from django.db.models import Q
        qs = qs.filter(
            Q(estado__in=['PUBLICADO', 'EN_CURSO', 'FINALIZADO'])
            | Q(propuesto_por=request.user)
        )

    tipo = request.GET.get('tipo')
    estado = request.GET.get('estado')
    modalidad = request.GET.get('modalidad')
    desde = request.GET.get('desde')
    hasta = request.GET.get('hasta')

    # Los choices se validan contra el modelo: un valor inventado devuelve
    # 400 en vez de una lista vacía silenciosa (que parece "no hay eventos").
    if tipo:
        if tipo not in dict(Evento.TIPO_CHOICES):
            return Response({'success': False, 'error': f'tipo inválido: {tipo}'}, status=400)
        qs = qs.filter(tipo=tipo)
    if estado:
        if estado not in dict(Evento.ESTADO_CHOICES):
            return Response({'success': False, 'error': f'estado inválido: {estado}'}, status=400)
        qs = qs.filter(estado=estado)
    if modalidad:
        if modalidad not in dict(Evento.MODALIDAD_CHOICES):
            return Response({'success': False, 'error': f'modalidad inválida: {modalidad}'}, status=400)
        qs = qs.filter(modalidad=modalidad)
    if desde:
        dt = parse_datetime(desde)
        if not dt:
            return Response({'success': False, 'error': 'desde: formato ISO-8601 esperado.'}, status=400)
        qs = qs.filter(fecha_inicio__gte=dt)
    if hasta:
        dt = parse_datetime(hasta)
        if not dt:
            return Response({'success': False, 'error': 'hasta: formato ISO-8601 esperado.'}, status=400)
        qs = qs.filter(fecha_inicio__lte=dt)

    qs = qs[:LIMITE_LISTADO]
    data = EventoSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalle_evento(request, id_evento):
    try:
        ev = Evento.objects.select_related(
            'propuesto_por', 'facultad', 'programa', 'materia').get(pk=id_evento)
    except Evento.DoesNotExist:
        return _no_encontrado('Evento no encontrado.')
    if ev.estado == 'BORRADOR' and not (
            _puede_gestionar(request.user) or ev.propuesto_por_id == request.user.id_usuario):
        return _denegado('Este evento todavía está en borrador.')
    return Response({'success': True, 'data': EventoSerializer(ev).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def crear_evento(request):
    """POST /api/eventos/crear/

    Crear lo puede hacer cualquier usuario autenticado (un Docente propone
    una actividad para su materia, igual que en `docente_proponer_evento`),
    pero SIEMPRE nace en BORRADOR: publicar exige rol de gestión y pasa por
    `aprobar_evento`.
    """
    ser = EventoSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    ev = ser.save(propuesto_por=request.user, estado='BORRADOR')
    log.info('[eventos] evento %s creado por %s', ev.pk, request.user.correo)
    return Response({'success': True, 'data': EventoSerializer(ev).data}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def aprobar_evento(request, id_evento):
    """POST /api/eventos/<id>/aprobar/  body: {"estado": "PUBLICADO"|"CANCELADO"}

    Sólo ADMINISTRADOR/COORDINADOR (incluye Decano y Secretaría Académica
    vía `rol_efectivo`; Bienestar y Mentorías quedan fuera por ser roles de
    solo consulta).
    """
    if not _puede_gestionar(request.user):
        return _denegado('Aprobar o cancelar un evento requiere rol de Administrador o Coordinador.')
    try:
        ev = Evento.objects.get(pk=id_evento)
    except Evento.DoesNotExist:
        return _no_encontrado('Evento no encontrado.')

    nuevo = (request.data.get('estado') or '').strip().upper()
    if nuevo not in ('PUBLICADO', 'CANCELADO'):
        return Response(
            {'success': False, 'error': 'estado debe ser PUBLICADO o CANCELADO.'}, status=400)

    ev.estado = nuevo
    ev.aprobado_por = request.user
    ev.fecha_aprobacion = timezone.now()
    ev.save(update_fields=['estado', 'aprobado_por', 'fecha_aprobacion', 'updated_at'])
    log.info('[eventos] evento %s -> %s por %s', ev.pk, nuevo, request.user.correo)
    return Response({'success': True, 'data': EventoSerializer(ev).data})


# ════════════════════════════════════════════════════════════
#  Reservas de recurso
# ════════════════════════════════════════════════════════════
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def crear_reserva(request, id_evento):
    """POST /api/eventos/<id>/reservas/ · reserva un salón para el evento.

    Rechaza el cruce de salón con la MISMA función que usa el flujo HTML
    (`_hay_conflicto_reserva`), no con una copia.
    """
    if not _puede_gestionar(request.user):
        return _denegado('Reservar un salón requiere rol de Administrador o Coordinador.')
    try:
        ev = Evento.objects.get(pk=id_evento)
    except Evento.DoesNotExist:
        return _no_encontrado('Evento no encontrado.')

    datos = dict(request.data)
    datos['evento'] = ev.pk
    ser = ReservaRecursoSerializer(data=datos)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)

    from siihapi.frontend_views import _hay_conflicto_reserva
    salon = ser.validated_data['salon']
    inicio = ser.validated_data['fecha_inicio']
    fin = ser.validated_data['fecha_fin']
    if _hay_conflicto_reserva(salon, inicio, fin):
        return Response({
            'success': False,
            'error': f'El salón {salon.codigo} ya está reservado en ese rango horario.',
        }, status=409)

    reserva = ser.save(solicitado_por=request.user, estado='SOLICITADA')
    return Response({'success': True, 'data': ReservaRecursoSerializer(reserva).data}, status=201)


# ════════════════════════════════════════════════════════════
#  Inscripciones y QR
# ════════════════════════════════════════════════════════════
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def inscribirse(request, id_evento):
    """POST /api/eventos/<id>/inscribirme/ · cualquier usuario autenticado.

    El usuario inscrito es SIEMPRE `request.user`: no se acepta un
    `usuario` en el payload, para que nadie pueda inscribir a terceros (ni
    generarles un token QR) desde la API.
    """
    try:
        ev = Evento.objects.get(pk=id_evento)
    except Evento.DoesNotExist:
        return _no_encontrado('Evento no encontrado.')

    if ev.estado not in ('PUBLICADO', 'EN_CURSO'):
        return Response(
            {'success': False, 'error': 'El evento no está abierto a inscripciones.'}, status=409)

    with transaction.atomic():
        # select_for_update sobre el evento serializa las inscripciones
        # concurrentes: sin esto dos peticiones simultáneas pueden leer el
        # mismo conteo y sobrepasar el cupo.
        ev = Evento.objects.select_for_update().get(pk=ev.pk)
        ya = InscripcionEvento.objects.filter(evento=ev, usuario=request.user).first()
        if ya:
            return Response({
                'success': True, 'ya_inscrito': True,
                'data': InscripcionEventoSerializer(ya).data,
            })

        estado = 'INSCRITO'
        if ev.cupo_maximo is not None:
            ocupados = InscripcionEvento.objects.filter(evento=ev, estado='INSCRITO').count()
            if ocupados >= ev.cupo_maximo:
                estado = 'LISTA_ESPERA'

        insc = InscripcionEvento.objects.create(evento=ev, usuario=request.user, estado=estado)

    return Response({
        'success': True, 'ya_inscrito': False,
        'data': InscripcionEventoSerializer(insc).data,
    }, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def qr_inscripcion(request, id_inscripcion):
    """GET /api/eventos/inscripciones/<id>/qr/

    Devuelve el token y el PNG del QR en base64. Sólo lo ve el dueño de la
    inscripción o quien pueda escanear ese evento — el token es la
    credencial de asistencia, no un dato público del evento.
    """
    import base64

    try:
        insc = InscripcionEvento.objects.select_related('evento', 'usuario').get(pk=id_inscripcion)
    except InscripcionEvento.DoesNotExist:
        return _no_encontrado('Inscripción no encontrada.')

    if insc.usuario_id != request.user.id_usuario and not _puede_escanear(request.user, insc.evento):
        return _denegado('Sólo el inscrito o el organizador pueden ver este QR.')

    from siihapi.frontend_views import _generar_qr_png
    png = _generar_qr_png(insc.token_qr)
    return Response({'success': True, 'data': {
        'id_inscripcion': insc.id_inscripcion,
        'evento': insc.evento.nombre,
        'usuario': insc.usuario.nombre_completo,
        'token_qr': str(insc.token_qr),
        'estado': insc.estado,
        'qr_png_base64': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
    }})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([EscaneoQRThrottle])
def registrar_escaneo(request, id_evento):
    """POST /api/eventos/<id>/escanear/  body: {"token_qr": "...", ...}

    La dirección (IN/OUT) NO la manda el cliente: se deduce del último
    registro de esa inscripción, igual que en `evento_escanear_qr` del
    flujo HTML. Así un escáner offline que reenvía la cola no puede
    inventarse entradas ni salidas.

    Acepta `timestamp` para la cola offline del scanner PWA, pero sólo
    hacia el pasado: un timestamp futuro se ignora y se usa la hora del
    servidor (si no, un cliente con el reloj adelantado ensucia el reporte).
    """
    try:
        ev = Evento.objects.get(pk=id_evento)
    except Evento.DoesNotExist:
        return _no_encontrado('Evento no encontrado.')

    if not _puede_escanear(request.user, ev):
        return _denegado('Escanear requiere rol operativo o ser el docente organizador.')

    token = str(request.data.get('token_qr') or '').strip()
    if not token:
        return Response({'success': False, 'error': 'token_qr es obligatorio.'}, status=400)

    # El token es un UUID: validarlo antes de ir a la base evita que un
    # string arbitrario llegue al ORM y dispara un 400 limpio.
    import uuid as uuid_lib
    try:
        token_uuid = uuid_lib.UUID(token)
    except (ValueError, AttributeError, TypeError):
        return Response({'success': False, 'error': 'token_qr no es un UUID válido.'}, status=400)

    try:
        insc = InscripcionEvento.objects.select_related('usuario').get(
            evento=ev, token_qr=token_uuid)
    except InscripcionEvento.DoesNotExist:
        # Mensaje deliberadamente genérico: no confirma si el token existe
        # en OTRO evento (eso permitiría sondear tokens ajenos).
        return Response(
            {'success': False, 'error': 'QR no válido para este evento.'}, status=404)

    if insc.estado != 'INSCRITO':
        return Response({
            'success': False,
            'error': f'La inscripción está en estado {insc.get_estado_display()}.',
        }, status=409)

    ahora = timezone.now()
    ts = ahora
    enviado = request.data.get('timestamp')
    offline = bool(request.data.get('sincronizado_offline', False))
    if enviado:
        parsed = parse_datetime(str(enviado))
        if not parsed:
            return Response(
                {'success': False, 'error': 'timestamp: formato ISO-8601 esperado.'}, status=400)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        ts = min(parsed, ahora)

    with transaction.atomic():
        ultima = AsistenciaEvento.objects.select_for_update().filter(
            inscripcion=insc).order_by('-timestamp').first()
        direccion = 'OUT' if (ultima and ultima.direccion == 'IN') else 'IN'
        reg = AsistenciaEvento.objects.create(
            inscripcion=insc, direccion=direccion, timestamp=ts,
            escaneado_por=request.user,
            latitud=request.data.get('latitud') or None,
            longitud=request.data.get('longitud') or None,
            sincronizado_offline=offline,
        )

    return Response({'success': True, 'data': AsistenciaEventoSerializer(reg).data}, status=201)



# ════════════════════════════════════════════════════════════
#  Reporte de asistencia (ceremonias de grado)
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reporte_asistencia(request, id_evento):
    """GET /api/eventos/<id>/asistencia/

    Para cada inscrito: si asistió alguna vez, a qué hora entró la primera
    vez, a qué hora salió la última y si sigue adentro ahora mismo (el
    Reporte #3 del Decano). `dentro_ahora` sale de la última dirección
    registrada, que es justamente para lo que existe el patrón IN/OUT.
    """
    try:
        ev = Evento.objects.get(pk=id_evento)
    except Evento.DoesNotExist:
        return _no_encontrado('Evento no encontrado.')

    if not _puede_escanear(request.user, ev):
        return _denegado('El reporte de asistencia es para el organizador o el staff operativo.')

    inscripciones = (
        InscripcionEvento.objects
        .filter(evento=ev)
        .select_related('usuario')
        .prefetch_related(Prefetch(
            'asistencias',
            queryset=AsistenciaEvento.objects.order_by('timestamp'),
            to_attr='marcas_ordenadas',
        ))
        .order_by('usuario__apellido', 'usuario__nombre')
    )

    data, asistentes, dentro = [], 0, 0
    for insc in inscripciones:
        marcas = insc.marcas_ordenadas
        entradas = [m for m in marcas if m.direccion == 'IN']
        salidas = [m for m in marcas if m.direccion == 'OUT']
        asistio = bool(entradas)
        sigue_dentro = bool(marcas) and marcas[-1].direccion == 'IN'
        if asistio:
            asistentes += 1
        if sigue_dentro:
            dentro += 1
        data.append({
            'id_inscripcion': insc.id_inscripcion,
            'usuario': insc.usuario.nombre_completo,
            'correo': insc.usuario.correo,
            'externo_nombre': insc.externo_nombre or None,
            'estado_inscripcion': insc.estado,
            'asistio': asistio,
            'primera_entrada': entradas[0].timestamp.isoformat() if entradas else None,
            'ultima_salida': salidas[-1].timestamp.isoformat() if salidas else None,
            'total_marcas': len(marcas),
            'dentro_ahora': sigue_dentro,
        })

    total = len(data)
    return Response({
        'success': True,
        'total': total,
        'resumen': {
            'evento': ev.nombre,
            'fecha_inicio': ev.fecha_inicio.isoformat(),
            'inscritos': total,
            'asistentes': asistentes,
            'dentro_ahora': dentro,
            # Sin inscritos el porcentaje no es 0%, es "no aplica" --
            # devolver 0.0 haría que un evento vacío se vea como un
            # fracaso de asistencia en el reporte del Decano.
            'porcentaje_asistencia': round(asistentes * 100.0 / total, 2) if total else None,
        },
        'data': data,
    })
