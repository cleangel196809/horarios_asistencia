"""SIIHAPI - API REST de Matriculas."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Estudiante, Periodo, Matricula


@api_view(['GET'])
def ping(request):
    return Response({'app': 'matriculas', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_periodos(request):
    qs = Periodo.objects.all().order_by('-fecha_inicio')
    return Response({'success': True, 'data': [{
        'id_periodo': p.id_periodo, 'codigo': p.codigo, 'nombre': p.nombre,
        'fecha_inicio': str(p.fecha_inicio), 'fecha_fin': str(p.fecha_fin),
        'activo': p.activo,
    } for p in qs]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_estudiantes(request):
    programa = request.GET.get('programa')
    qs = Estudiante.objects.filter(activo=True).select_related('usuario', 'programa')
    if programa: qs = qs.filter(programa__codigo=programa)
    qs = qs[:300]
    return Response({'success': True, 'total': len(qs), 'data': [{
        'id_estudiante': e.id_estudiante, 'codigo': e.codigo,
        'nombre_completo': e.usuario.nombre_completo,
        'correo': e.usuario.correo,
        'programa': e.programa.nombre, 'programa_codigo': e.programa.codigo,
        'semestre': e.semestre_actual,
    } for e in qs]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mis_matriculas(request):
    if request.user.rol != 'ESTUDIANTE':
        return Response({'success': False, 'error': 'Solo estudiantes'}, status=403)
    est = Estudiante.objects.filter(usuario=request.user).first()
    if not est:
        return Response({'success': False, 'error': 'Cuenta no vinculada'}, status=404)
    qs = Matricula.objects.filter(estudiante=est).select_related('materia', 'periodo').order_by('-periodo__fecha_inicio')
    return Response({'success': True, 'total': qs.count(), 'data': [{
        'id_matricula': m.id_matricula, 'periodo': m.periodo.codigo,
        'materia': m.materia.codigo, 'materia_nombre': m.materia.nombre,
        'creditos': m.materia.creditos, 'estado': m.estado,
        'nota_final': float(m.nota_final) if m.nota_final else None,
    } for m in qs]})
