"""SIIHAPI - Vistas de integracion con SISCA."""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .cliente import get_cliente, ClienteSISCAError
from .models import IntegracionLog


@api_view(['GET'])
def ping(request):
    return Response({'app': 'integracion_sisca', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def estado_sisca(request):
    """GET /api/sisca/estado/  - Estado de la conexion con SISCA."""
    cliente = get_cliente()
    conectado = cliente.ping()
    ultima_pub = (IntegracionLog.objects
                  .filter(operacion='PUBLICAR_HORARIOS', estado='EXITO')
                  .order_by('-fecha').first())
    hace_24h = timezone.now() - timedelta(hours=24)
    logs_24h = IntegracionLog.objects.filter(fecha__gte=hace_24h)
    return Response({
        'conectado': conectado,
        'base_url': cliente.base_url,
        'ultima_publicacion': ultima_pub.fecha.isoformat() if ultima_pub else None,
        'logs_24h': {
            'total': logs_24h.count(),
            'exitos': logs_24h.filter(estado='EXITO').count(),
            'errores': logs_24h.filter(estado='ERROR').count(),
        },
        'total_logs': IntegracionLog.objects.count(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def publicar_horarios(request):
    """RF-40 - Publica horarios del periodo a SISCA."""
    periodo = request.data.get('periodo', '2026-2')
    if request.user.rol not in ('ADMINISTRADOR', 'COORDINADOR'):
        return Response({'success': False, 'error': 'No autorizado'},
                        status=status.HTTP_403_FORBIDDEN)
    horarios = []  # TODO: cargar horarios aprobados del periodo
    cliente = get_cliente()
    try:
        respuesta = cliente.publicar_horarios(periodo, horarios)
        return Response({
            'success': True,
            'mensaje': f'Horarios del periodo {periodo} publicados a SISCA',
            'total_publicados': len(horarios),
            'sisca_respuesta': respuesta,
        })
    except ClienteSISCAError as e:
        return Response({
            'success': False,
            'error': str(e),
            'sugerencia': 'Verifica que SISCA este corriendo en la URL configurada.'
        }, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def consultar_asistencia(request, id_sesion):
    """RF-42 - Consulta asistencia de una sesion en SISCA."""
    cliente = get_cliente()
    try:
        respuesta = cliente.consultar_asistencia_sesion(id_sesion)
        return Response({'success': True, 'data': respuesta})
    except ClienteSISCAError as e:
        return Response({'success': False, 'error': str(e)},
                        status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def logs(request):
    """Ultimos eventos de integracion para mostrar en la UI."""
    limit = int(request.GET.get('limit', 50))
    qs = IntegracionLog.objects.order_by('-fecha')[:limit]
    return Response({
        'success': True,
        'logs': [{
            'id': l.id_log,
            'operacion': l.get_operacion_display(),
            'operacion_codigo': l.operacion,
            'estado': l.estado,
            'endpoint': l.endpoint,
            'codigo_http': l.codigo_http,
            'intentos': l.intentos,
            'duracion_ms': l.duracion_ms,
            'error_msg': l.error_msg,
            'fecha': l.fecha.isoformat(),
        } for l in qs]
    })
