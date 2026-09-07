"""SIIHAPI - API REST de Personal."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Docente, DisponibilidadDocente, Especialidad


@api_view(['GET'])
def ping(request):
    return Response({'app': 'personal', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_docentes(request):
    qs = Docente.objects.filter(activo=True).select_related('usuario')[:200]
    return Response({'success': True, 'total': len(qs), 'data': [{
        'id_docente': d.usuario_id,
        'nombre_completo': d.usuario.nombre_completo,
        'correo': d.usuario.correo,
        'tipo_contrato': d.tipo_contrato,
        'tipo_contrato_label': d.get_tipo_contrato_display(),
        'carga_horaria_max': d.carga_horaria_max,
    } for d in qs]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mi_disponibilidad(request):
    if request.user.rol != 'DOCENTE':
        return Response({'success': False, 'error': 'Solo docentes'}, status=403)
    doc = Docente.objects.filter(usuario=request.user).first()
    if not doc:
        return Response({'success': False, 'error': 'Cuenta no vinculada'}, status=404)
    qs = DisponibilidadDocente.objects.filter(docente=doc).order_by('dia', 'bloque')
    return Response({'success': True, 'total': qs.count(), 'data': [{
        'id': r.id_disponibilidad, 'dia': r.dia, 'dia_label': r.get_dia_display(),
        'bloque': r.bloque, 'motivo': r.motivo,
    } for r in qs]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_especialidades(request):
    qs = Especialidad.objects.all()
    return Response({'success': True, 'data': [
        {'codigo': e.codigo, 'nombre': e.nombre} for e in qs
    ]})
