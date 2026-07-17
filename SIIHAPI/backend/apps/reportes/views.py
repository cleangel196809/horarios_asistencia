"""SIIHAPI - API REST de Reportes."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.infraestructura.models import Sede, Salon
from apps.academico.models import Programa
from apps.matriculas.models import Estudiante, Matricula
from apps.personal.models import Docente
from apps.horarios.models import Horario, AsignacionIA
from apps.integracion_sisca.models import IntegracionLog


@api_view(['GET'])
def ping(request):
    return Response({'app': 'reportes', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def kpis_globales(request):
    """KPIs institucionales (RF-46)."""
    return Response({'success': True, 'data': {
        'sedes': Sede.objects.filter(estado='A').count(),
        'salones': Salon.objects.filter(activo=True).count(),
        'programas': Programa.objects.filter(activo=True).count(),
        'docentes': Docente.objects.filter(activo=True).count(),
        'estudiantes': Estudiante.objects.filter(activo=True).count(),
        'matriculas_activas': Matricula.objects.filter(estado='ACTIVA').count(),
        'horarios': Horario.objects.count(),
        'horarios_publicados': Horario.objects.filter(estado='PUBLICADO').count(),
        'ejecuciones_ia': AsignacionIA.objects.count(),
        'eventos_sisca': IntegracionLog.objects.count(),
    }})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribucion_por_sede(request):
    sedes = Sede.objects.filter(estado='A')
    return Response({'success': True, 'data': [{
        'sede': s.nombre, 'codigo': s.codigo,
        'salones': s.salones.filter(activo=True).count(),
        'horarios': Horario.objects.filter(salon__sede=s).count(),
    } for s in sedes]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribucion_por_tipo_programa(request):
    data = []
    for t, label in Programa.TIPO_CHOICES:
        data.append({
            'tipo': t, 'label': label,
            'programas': Programa.objects.filter(tipo=t, activo=True).count(),
            'estudiantes': Estudiante.objects.filter(programa__tipo=t, activo=True).count(),
        })
    return Response({'success': True, 'data': data})
