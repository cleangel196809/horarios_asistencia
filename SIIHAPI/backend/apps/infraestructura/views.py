"""SIIHAPI - API REST de Infraestructura (Sedes y Salones)."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Sede, Salon


@api_view(['GET'])
def ping(request):
    return Response({'app': 'infraestructura', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_sedes(request):
    qs = Sede.objects.filter(estado='A')
    data = [{
        'id_sede': s.id_sede, 'codigo': s.codigo, 'nombre': s.nombre,
        'direccion': s.direccion, 'telefono': s.telefono,
        'capacidad': s.capacidad_total, 'total_salones': s.total_salones,
    } for s in qs]
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_salones(request):
    sede = request.GET.get('sede')
    tipo = request.GET.get('tipo')
    qs = Salon.objects.filter(activo=True).select_related('sede')
    if sede: qs = qs.filter(sede__codigo=sede)
    if tipo: qs = qs.filter(tipo=tipo)
    qs = qs[:500]
    data = [{
        'id_salon': s.id_salon, 'codigo': s.codigo, 'nombre': s.nombre,
        'sede': s.sede.nombre, 'sede_codigo': s.sede.codigo,
        'capacidad': s.capacidad, 'tipo': s.get_tipo_display(),
        'tipo_codigo': s.tipo, 'planta': s.planta,
    } for s in qs]
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalle_salon(request, codigo):
    try:
        s = Salon.objects.select_related('sede').get(codigo=codigo, activo=True)
    except Salon.DoesNotExist:
        return Response({'success': False, 'error': 'Salon no encontrado'}, status=404)
    return Response({'success': True, 'data': {
        'id_salon': s.id_salon, 'codigo': s.codigo, 'nombre': s.nombre,
        'sede': s.sede.nombre, 'capacidad': s.capacidad,
        'tipo': s.get_tipo_display(), 'planta': s.planta,
        'equipamiento': list(s.equipamiento.values('tipo', 'cantidad', 'descripcion', 'operativo')),
    }})
