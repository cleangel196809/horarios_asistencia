"""
SIIHAPI - API REST del Módulo de Gestión Documental Inteligente (User-in-the-Loop).

Flujo expuesto vía API (sin romper Oracle ni la integración SISCA):
  POST   /api/horarios/docs/sesiones/                 -> analizar N archivos
  GET    /api/horarios/docs/sesiones/<sid>/           -> ver borrador + conflictos
  POST   /api/horarios/docs/sesiones/<sid>/instruccion/ -> aplicar cambio en NL (iterable)
  POST   /api/horarios/docs/sesiones/<sid>/aprobar/   -> exportar .xlsx definitivo
  POST   /api/horarios/docs/sesiones/<sid>/publicar-sisca/ -> publicar el resultado en SISCA

El estado se guarda en la CACHE de Django (cero cambios de esquema Oracle).
"""
import uuid
import logging

from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from siihapi.motor_ia import gestion_documentos as gd

log = logging.getLogger(__name__)

_TTL = 60 * 60 * 3          # 3 horas de vida por sesión
_PREFIX = 'sesiondoc:'


def _guardar(sesion: 'gd.SesionDocumento'):
    cache.set(_PREFIX + sesion.id, sesion.to_json(), _TTL)


def _cargar(sid: str):
    raw = cache.get(_PREFIX + sid)
    return gd.SesionDocumento.from_json(raw) if raw else None


# ───────────────────────────────────────────────────────────────
# 1) Carga y análisis de múltiples documentos
# ───────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def crear_sesion(request):
    archivos = request.FILES.getlist('archivos') or request.FILES.getlist('archivos[]')
    if not archivos:
        f = request.FILES.get('archivo')
        archivos = [f] if f else []
    if len(archivos) < 1:
        return Response({'success': False, 'error': 'Adjunta al menos un archivo (campo "archivos").'}, status=400)

    periodo = (request.data.get('periodo') or '2026-2').strip()
    pares = []
    for f in archivos:
        if f.size > 8 * 1024 * 1024:
            return Response({'success': False, 'error': f'{f.name} supera 8 MB.'}, status=400)
        pares.append((f.name, f.read()))

    sid = uuid.uuid4().hex[:12]
    try:
        sesion = gd.analizar_documentos(pares, periodo=periodo, sesion_id=sid)
    except Exception as e:
        log.exception('GestionDoc analizar')
        return Response({'success': False, 'error': f'No se pudo analizar: {str(e)[:200]}'}, status=400)

    _guardar(sesion)
    return Response({
        'success': True,
        'sesion_id': sesion.id,
        'estado': sesion.estado,
        'resumen': gd.resumen_para_usuario(sesion),
    }, status=201)


# ───────────────────────────────────────────────────────────────
# 2) Ver estado / borrador actual
# ───────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ver_sesion(request, sid):
    sesion = _cargar(sid)
    if not sesion:
        return Response({'success': False, 'error': 'Sesión no encontrada o expirada.'}, status=404)
    return Response({
        'success': True,
        'sesion_id': sesion.id,
        'estado': sesion.estado,
        'resumen': gd.resumen_para_usuario(sesion),
        'borrador': sesion.df().to_dict('records'),
        'conflictos': sesion.advertencias,
        'historial': sesion.historial,
    })


# ───────────────────────────────────────────────────────────────
# 3) Aplicar cambios en lenguaje natural (ciclo de revisión)
# ───────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser, FormParser, MultiPartParser])
def aplicar_instruccion(request, sid):
    sesion = _cargar(sid)
    if not sesion:
        return Response({'success': False, 'error': 'Sesión no encontrada o expirada.'}, status=404)

    instruccion = (request.data.get('instruccion') or '').strip()
    if not instruccion:
        return Response({'success': False, 'error': 'Falta "instruccion".'}, status=400)

    proveedor = request.data.get('proveedor') or None
    resultado = gd.aplicar_cambios_usuario(sesion, instruccion, forzar_proveedor=proveedor)
    _guardar(sesion)   # persistir el nuevo borrador

    if not resultado.get('ok'):
        return Response({'success': False, 'duda': resultado.get('duda')}, status=200)
    return Response({
        'success': True,
        'sesion_id': sesion.id,
        'operaciones_aplicadas': resultado['operaciones_aplicadas'],
        'borrador': resultado['borrador'],
        'conflictos': resultado['conflictos'],
        'hay_conflictos': resultado['hay_conflictos'],
        'pregunta': '¿Desea realizar más cambios o aprobar el documento?',
    })


# ───────────────────────────────────────────────────────────────
# 4) Aprobación final -> exportar .xlsx limpio
# ───────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def aprobar_sesion(request, sid):
    sesion = _cargar(sid)
    if not sesion:
        return Response({'success': False, 'error': 'Sesión no encontrada o expirada.'}, status=404)

    contenido, errores = gd.exportar_documento_limpio(sesion)
    if errores:
        return Response({'success': False, 'error': 'No se puede aprobar: hay inconsistencias.',
                         'detalle': errores}, status=409)
    _guardar(sesion)  # estado -> APROBADO
    resp = HttpResponse(
        contenido,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="horario_limpio_{sid}.xlsx"'
    return resp


# ───────────────────────────────────────────────────────────────
# 5) Publicar el resultado aprobado en SISCA (reusa el cliente con circuit breaker)
# ───────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def publicar_en_sisca(request, sid):
    sesion = _cargar(sid)
    if not sesion:
        return Response({'success': False, 'error': 'Sesión no encontrada o expirada.'}, status=404)

    # Validación final antes de enviar
    _, errores = gd.exportar_documento_limpio(sesion)
    if errores:
        return Response({'success': False, 'error': 'Corrige las inconsistencias antes de publicar.',
                         'detalle': errores}, status=409)

    # Construir payload SISCA desde el borrador limpio
    filas = sesion.df().to_dict('records')
    payload = [{
        'codigo_materia': f.get('codigo_materia', ''),
        'nombre_materia': f.get('nombre_materia', ''),
        'docente':        f.get('docente', ''),
        'docente_email':  f.get('docente_email', ''),
        'salon':          f.get('salon', ''),
        'dia':            f.get('dia', ''),
        'hora_inicio':    f.get('hora_inicio', ''),
        'hora_fin':       f.get('hora_fin', ''),
    } for f in filas]

    try:
        from apps.integracion_sisca.cliente import get_cliente, ClienteSISCAError
        cliente = get_cliente()
        if not cliente.ping():
            return Response({'success': False,
                             'error': f'SISCA no responde en {cliente.base_url}. Inícialo y reintenta.'},
                            status=502)
        resp = cliente.publicar_horarios(sesion.periodo, payload)
        sesion.historial.append({'paso': 'publicacion_sisca', 'total': len(payload)})
        _guardar(sesion)
        return Response({'success': True,
                         'mensaje': f'{len(payload)} horario(s) publicados en SISCA.',
                         'sisca_respuesta': resp})
    except ClienteSISCAError as e:
        return Response({'success': False, 'error': str(e),
                         'sugerencia': 'Verifica que SISCA esté corriendo en el puerto 8080.'},
                        status=502)
    except Exception as e:
        log.exception('GestionDoc publicar SISCA')
        return Response({'success': False, 'error': f'Error publicando en SISCA: {str(e)[:200]}'}, status=500)
