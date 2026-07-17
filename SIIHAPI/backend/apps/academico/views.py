"""SIIHAPI - API REST de Academico."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Facultad, Programa, Materia


@api_view(['GET'])
def ping(request):
    return Response({'app': 'academico', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_facultades(request):
    qs = Facultad.objects.filter(activa=True)
    return Response({'success': True, 'total': qs.count(), 'data': [
        {'id': f.id_facultad, 'codigo': f.codigo, 'nombre': f.nombre} for f in qs
    ]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_programas(request):
    tipo = request.GET.get('tipo')
    facultad = request.GET.get('facultad')
    qs = Programa.objects.filter(activo=True).select_related('facultad')
    if tipo: qs = qs.filter(tipo=tipo)
    if facultad: qs = qs.filter(facultad__codigo=facultad)
    return Response({'success': True, 'total': qs.count(), 'data': [{
        'id_programa': p.id_programa, 'codigo': p.codigo, 'nombre': p.nombre,
        'tipo': p.tipo, 'tipo_label': p.get_tipo_display(),
        'facultad': p.facultad.nombre, 'duracion_semestres': p.duracion_semestres,
    } for p in qs]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_materias(request):
    programa = request.GET.get('programa')
    qs = Materia.objects.filter(activa=True).select_related('programa')
    if programa: qs = qs.filter(programa__codigo=programa)
    qs = qs[:300]
    return Response({'success': True, 'total': len(qs), 'data': [{
        'id_materia': m.id_materia, 'codigo': m.codigo, 'nombre': m.nombre,
        'programa': m.programa.codigo, 'ciclo': m.ciclo,
        'creditos': m.creditos, 'horas_semanales': m.horas_semanales,
    } for m in qs]})
