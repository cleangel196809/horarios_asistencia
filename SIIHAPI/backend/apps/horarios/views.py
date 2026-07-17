"""SIIHAPI - API REST de Horarios."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import Bloque, Horario, AsignacionIA, ReglaNegocio
from apps.personal.models import Docente
from apps.matriculas.models import Estudiante


@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    return Response({'app': 'horarios', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_bloques(request):
    qs = Bloque.objects.all().order_by('numero')
    return Response({
        'success': True,
        'data': [{
            'numero': b.numero,
            'hora_inicio': b.hora_inicio.strftime('%H:%M'),
            'hora_fin':    b.hora_fin.strftime('%H:%M'),
        } for b in qs]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_horarios(request):
    estado = request.GET.get('estado')
    qs = Horario.objects.select_related(
        'matricula', 'materia', 'docente__usuario', 'salon__sede', 'bloque'
    )
    if estado:
        qs = qs.filter(estado=estado)
    qs = qs[:300]
    data = [{
        'id_horario':  h.id_horario,
        'dia':         h.dia,
        'bloque':      h.bloque.numero,
        'materia':     h.materia.codigo,
        'docente':     h.docente.usuario.nombre_completo,
        'salon':       h.salon.codigo,
        'sede':        h.salon.sede.nombre,
        'estado':      h.estado,
        'id_sisca':    h.id_sisca,
    } for h in qs]
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mi_horario(request):
    """GET /api/horarios/mi/  Devuelve mi horario segun el rol."""
    user = request.user
    if user.rol == 'DOCENTE':
        doc = Docente.objects.filter(usuario=user).first()
        if not doc:
            return Response({'success': False, 'error': 'Cuenta no vinculada'}, status=404)
        qs = Horario.objects.filter(docente=doc)
    elif user.rol == 'ESTUDIANTE':
        est = Estudiante.objects.filter(usuario=user).first()
        if not est:
            return Response({'success': False, 'error': 'Cuenta no vinculada'}, status=404)
        qs = Horario.objects.filter(matricula__estudiante=est)
    else:
        return Response({'success': False, 'error': 'Solo Docente o Estudiante'}, status=403)

    qs = qs.select_related('materia', 'docente__usuario', 'salon', 'bloque').order_by('dia', 'bloque__numero')
    data = [{
        'dia':         h.dia,
        'dia_label':   h.get_dia_display(),
        'bloque':      h.bloque.numero,
        'hora_inicio': h.bloque.hora_inicio.strftime('%H:%M'),
        'hora_fin':    h.bloque.hora_fin.strftime('%H:%M'),
        'materia':     h.materia.codigo,
        'materia_nombre': h.materia.nombre,
        'docente':     h.docente.usuario.nombre_completo,
        'salon':       h.salon.codigo,
        'estado':      h.estado,
    } for h in qs]
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def historial_ia(request):
    qs = AsignacionIA.objects.order_by('-fecha_inicio')[:50]
    return Response({
        'success': True,
        'data': [{
            'job_id':   a.job_id,
            'periodo':  a.periodo.codigo,
            'estado':   a.estado,
            'inicio':   a.fecha_inicio.isoformat() if a.fecha_inicio else None,
            'duracion_ms': a.duracion_ms,
            'asignadas': a.asignaciones_exitosas,
            'conflictos': a.conflictos_residuales,
        } for a in qs]
    })
