"""
SIIHAPI · apps/evaluacion_docente — API REST (modularización, 2026-10-05).

Mismo estilo que `apps/infraestructura/views.py`: vistas de función con
`@api_view` y respuesta `{'success', 'total', 'data'}`.

Dos reglas que atraviesan todo el módulo:

1. **Nada se confirma solo.** Una calificación dictada por voz nace en
   BORRADOR y sólo pasa a CONFIRMADO cuando el docente lo pide
   explícitamente. No hay autoguardado silencioso en ningún camino.
2. **Ningún ajuste de syllabus sin motivo.** `ajustar_syllabus` exige
   `motivo` y escribe `HistorialAjusteSyllabus` en la misma transacción
   que el cambio: si falla la auditoría, no queda el cambio.
"""
import logging

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, parser_classes, permission_classes, throttle_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import (
    ActividadSyllabus, Calificacion, CriterioRubrica, HistorialAjusteSyllabus,
    NivelDesempeno, Rubrica, Syllabus, UnidadSyllabus,
)
from .throttling import VozTranscripcionThrottle
from .serializers import (
    ActividadSyllabusSerializer, CalificacionSerializer, CriterioRubricaSerializer,
    HistorialAjusteSyllabusSerializer, NivelDesempenoSerializer, RubricaSerializer,
    SyllabusSerializer, UnidadSyllabusSerializer,
)

log = logging.getLogger(__name__)

LIMITE_LISTADO = 300

# Igual que en apps.aula_virtual: las páginas HTML del módulo llaman a
# estos endpoints con la cookie de sesión, no con JWT. Se acepta
# SessionAuthentication ADEMÁS del JWT, sólo en esta app.
AUTENTICACION = [JWTAuthentication, SessionAuthentication]


# ════════════════════════════════════════════════════════════
#  Permisos
# ════════════════════════════════════════════════════════════
def _es_staff(user):
    from siihapi.permisos import es_solo_consulta
    return (user.is_authenticated
            and user.rol_efectivo in ('ADMINISTRADOR', 'COORDINADOR')
            and not es_solo_consulta(user))


def _mi_docente(user):
    """Perfil Docente del usuario, o None. La PK de Docente es el usuario."""
    from apps.personal.models import Docente
    return Docente.objects.filter(pk=user.id_usuario).first()


def _denegado(detalle='No tienes permiso para esta operación.'):
    return Response({'success': False, 'error': detalle}, status=403)


def _no_encontrado(detalle='Recurso no encontrado.'):
    return Response({'success': False, 'error': detalle}, status=404)


def _es_dueno(user, obj):
    """`obj` es cualquier cosa con un `docente_id` (Rubrica, Syllabus,
    Calificacion). El id de Docente ES el id de usuario."""
    return getattr(obj, 'docente_id', None) == user.id_usuario


def _puede_editar(user, obj):
    return _es_staff(user) or _es_dueno(user, obj)


# ════════════════════════════════════════════════════════════
#  Ping
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([AllowAny])
def ping(request):
    return Response({'app': 'evaluacion_docente', 'status': 'ok'})


# ════════════════════════════════════════════════════════════
#  a) Calificaciones (notas por voz y manuales)
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def listar_calificaciones(request):
    """GET /api/evaluacion-docente/calificaciones/
    Filtros: materia, periodo, estudiante, estado, origen.

    Un docente ve sólo las suyas; el staff las ve todas. Un estudiante ve
    sólo las SUYAS Y CONFIRMADAS: un borrador no es una nota todavía y no
    tiene por qué verlo nadie más que quien lo está revisando.
    """
    qs = Calificacion.objects.select_related(
        'materia', 'estudiante__usuario', 'docente__usuario', 'periodo')

    if _es_staff(request.user):
        pass
    elif _mi_docente(request.user):
        qs = qs.filter(docente_id=request.user.id_usuario)
    else:
        qs = qs.filter(estudiante__usuario_id=request.user.id_usuario, estado='CONFIRMADO')

    for campo, param in (('materia_id', 'materia'), ('periodo_id', 'periodo'),
                         ('estudiante_id', 'estudiante')):
        valor = request.GET.get(param)
        if valor:
            if not str(valor).isdigit():
                return Response(
                    {'success': False, 'error': f'{param} debe ser un id numérico.'}, status=400)
            qs = qs.filter(**{campo: int(valor)})

    estado = request.GET.get('estado')
    if estado:
        if estado not in dict(Calificacion.ESTADO_CHOICES):
            return Response({'success': False, 'error': f'estado inválido: {estado}'}, status=400)
        qs = qs.filter(estado=estado)
    origen = request.GET.get('origen')
    if origen:
        if origen not in dict(Calificacion.ORIGEN_CHOICES):
            return Response({'success': False, 'error': f'origen inválido: {origen}'}, status=400)
        qs = qs.filter(origen=origen)

    qs = qs[:LIMITE_LISTADO]
    data = CalificacionSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_calificacion(request):
    """POST /api/evaluacion-docente/calificaciones/crear/

    Siempre nace en BORRADOR, venga de voz o escrita a mano. Confirmar es
    un paso aparte y explícito (`confirmar_calificacion`).
    """
    docente = _mi_docente(request.user)
    if not docente and not _es_staff(request.user):
        return _denegado('Sólo un Docente (o el staff) puede registrar calificaciones.')

    # El docente conoce el CÓDIGO del estudiante, no su id interno (que es
    # el id de usuario). Se acepta `estudiante_codigo` y se resuelve aquí,
    # para no obligar al frontend a hacer una búsqueda previa.
    datos = dict(request.data)
    codigo = (datos.pop('estudiante_codigo', None)
              or (datos.get('estudiante') if not str(datos.get('estudiante', '')).isdigit() else None))
    if isinstance(codigo, (list, tuple)):
        codigo = codigo[0] if codigo else None
    if codigo:
        from apps.matriculas.models import Estudiante
        est = Estudiante.objects.filter(codigo=str(codigo).strip()).first()
        if not est:
            return Response(
                {'success': False, 'error': f'No hay un estudiante con código {codigo}.'},
                status=404)
        datos['estudiante'] = est.pk

    ser = CalificacionSerializer(data=datos)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)

    if not docente:
        # Staff registrando en nombre de un docente: tiene que decir cuál.
        from apps.personal.models import Docente
        docente_id = request.data.get('docente')
        docente = Docente.objects.filter(pk=docente_id).first() if docente_id else None
        if not docente:
            return Response(
                {'success': False, 'error': 'docente es obligatorio cuando lo registra el staff.'},
                status=400)

    cal = ser.save(docente=docente, estado='BORRADOR')
    return Response({'success': True, 'data': CalificacionSerializer(cal).data}, status=201)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def confirmar_calificacion(request, id_calificacion):
    """POST /api/evaluacion-docente/calificaciones/<id>/confirmar/

    Acepta `nota` y `observaciones` en el cuerpo: el docente puede
    corregir la transcripción en el mismo acto de confirmar. El
    `texto_transcrito` original NO se toca — queda como evidencia de qué
    se dictó frente a qué se guardó.
    """
    cal = Calificacion.objects.filter(pk=id_calificacion).first()
    if not cal:
        return _no_encontrado('Calificación no encontrada.')
    if not _puede_editar(request.user, cal):
        return _denegado('Sólo el docente que la registró (o el staff) puede confirmarla.')
    if cal.estado == 'CONFIRMADO':
        return Response({'success': True, 'ya_confirmada': True,
                         'data': CalificacionSerializer(cal).data})

    campos = ['estado', 'confirmado_por', 'fecha_confirmacion', 'updated_at']
    if 'nota' in request.data or 'observaciones' in request.data:
        parcial = CalificacionSerializer(cal, data=request.data, partial=True)
        if not parcial.is_valid():
            return Response({'success': False, 'errors': parcial.errors}, status=400)
        if 'nota' in parcial.validated_data:
            cal.nota = parcial.validated_data['nota']
            campos.append('nota')
        if 'observaciones' in parcial.validated_data:
            cal.observaciones = parcial.validated_data['observaciones']
            campos.append('observaciones')

    cal.estado = 'CONFIRMADO'
    cal.confirmado_por = request.user
    cal.fecha_confirmacion = timezone.now()
    cal.save(update_fields=campos)
    log.info('[evaluacion_docente] calificación %s confirmada por %s',
             cal.pk, request.user.correo)
    return Response({'success': True, 'data': CalificacionSerializer(cal).data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def descartar_calificacion(request, id_calificacion):
    """POST /api/evaluacion-docente/calificaciones/<id>/descartar/

    Borra un BORRADOR (una transcripción que salió mal). Una calificación
    ya confirmada NO se borra por aquí: corregir una nota en firme es otra
    conversación y debe dejar rastro.
    """
    cal = Calificacion.objects.filter(pk=id_calificacion).first()
    if not cal:
        return _no_encontrado('Calificación no encontrada.')
    if not _puede_editar(request.user, cal):
        return _denegado()
    if cal.estado == 'CONFIRMADO':
        return Response({
            'success': False,
            'error': 'Una calificación confirmada no se descarta desde aquí.',
        }, status=409)
    cal.delete()
    return Response({'success': True, 'data': {'id_calificacion': id_calificacion}})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([VozTranscripcionThrottle])
def transcribir_audio(request):
    """POST /api/notas/transcribir-audio  (multipart: campo `audio`)

    RESPALDO de la Web Speech API, para navegadores que no la soportan.
    Devuelve SÓLO el texto: no crea ninguna calificación. El docente lee
    la transcripción, la corrige si hace falta y recién entonces llama a
    `crear_calificacion`. Ese es el punto del flujo con confirmación
    humana — aquí no se guarda nada.

    Si `faster-whisper` no está instalado responde 503 con el detalle, y
    el cliente sigue usando Web Speech API.
    """
    docente = _mi_docente(request.user)
    if not docente and not _es_staff(request.user):
        return _denegado('Sólo un Docente (o el staff) puede usar la transcripción.')

    from .transcripcion import TranscripcionNoDisponible, transcribir, validar_audio

    archivo = request.FILES.get('audio')
    error = validar_audio(archivo)
    if error:
        return Response({'success': False, 'error': error}, status=400)

    idioma = (request.data.get('idioma') or 'es').strip().lower()
    if idioma not in ('es', 'en', 'pt', 'fr', ''):
        return Response({'success': False, 'error': f'Idioma no admitido: {idioma}'}, status=400)

    try:
        resultado = transcribir(archivo, idioma=idioma)
    except TranscripcionNoDisponible as e:
        return Response({'success': False, 'error': str(e)}, status=503)
    except Exception as e:  # noqa: BLE001 — audio corrupto, ffmpeg ausente, etc.
        log.exception('[evaluacion_docente] fallo transcribiendo audio')
        return Response(
            {'success': False, 'error': f'No se pudo transcribir el audio: {e}'}, status=422)

    return Response({
        'success': True,
        'requiere_confirmacion': True,
        'data': resultado,
    })



# ════════════════════════════════════════════════════════════
#  b) Rúbricas y matriz de evaluación
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def listar_rubricas(request):
    qs = Rubrica.objects.select_related('materia', 'docente__usuario', 'periodo') \
                        .prefetch_related('criterios__niveles')
    if not _es_staff(request.user) and _mi_docente(request.user):
        qs = qs.filter(docente_id=request.user.id_usuario)
    materia = request.GET.get('materia')
    if materia:
        if not str(materia).isdigit():
            return Response({'success': False, 'error': 'materia debe ser un id numérico.'}, status=400)
        qs = qs.filter(materia_id=int(materia))
    qs = qs[:LIMITE_LISTADO]
    data = RubricaSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_rubrica(request):
    docente = _mi_docente(request.user)
    if not docente:
        if not _es_staff(request.user):
            return _denegado('Sólo un Docente (o el staff) puede crear rúbricas.')
        from apps.personal.models import Docente
        docente = Docente.objects.filter(pk=request.data.get('docente')).first()
        if not docente:
            return Response(
                {'success': False, 'error': 'docente es obligatorio cuando la crea el staff.'},
                status=400)
    ser = RubricaSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    rubrica = ser.save(docente=docente)
    return Response({'success': True, 'data': RubricaSerializer(rubrica).data}, status=201)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_criterio(request, id_rubrica):
    rubrica = Rubrica.objects.filter(pk=id_rubrica).first()
    if not rubrica:
        return _no_encontrado('Rúbrica no encontrada.')
    if not _puede_editar(request.user, rubrica):
        return _denegado()
    ser = CriterioRubricaSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    criterio = ser.save(rubrica=rubrica)
    return Response({'success': True, 'data': CriterioRubricaSerializer(criterio).data}, status=201)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_nivel(request, id_criterio):
    criterio = CriterioRubrica.objects.select_related('rubrica').filter(pk=id_criterio).first()
    if not criterio:
        return _no_encontrado('Criterio no encontrado.')
    if not _puede_editar(request.user, criterio.rubrica):
        return _denegado()
    ser = NivelDesempenoSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    nivel = ser.save(criterio=criterio)
    return Response({'success': True, 'data': NivelDesempenoSerializer(nivel).data}, status=201)


def _matriz(rubrica):
    """Matriz criterios × niveles: cabeceras, filas y avisos.

    Cada criterio puede tener sus propios niveles, así que las columnas
    son la UNIÓN ordenada de todos los nombres de nivel; una celda vacía
    significa que ese criterio no define ese nivel.
    """
    criterios = list(rubrica.criterios.prefetch_related('niveles').all())
    nombres, vistos = [], set()
    for c in criterios:
        for n in c.niveles.all():
            if n.nombre not in vistos:
                vistos.add(n.nombre)
                nombres.append(n.nombre)

    filas = []
    for c in criterios:
        por_nombre = {n.nombre: n for n in c.niveles.all()}
        filas.append({
            'criterio': c.nombre,
            'descripcion': c.descripcion,
            'peso': float(c.peso),
            'niveles': [
                {
                    'nombre': nombre,
                    'puntaje': float(por_nombre[nombre].puntaje) if nombre in por_nombre else None,
                    'descriptor': por_nombre[nombre].descriptor if nombre in por_nombre else '',
                }
                for nombre in nombres
            ],
        })

    peso_total = float(rubrica.peso_total)
    avisos = []
    if criterios and abs(peso_total - 100.0) > 0.01:
        # Se avisa, no se corrige: repartir el peso es decisión del docente.
        avisos.append(f'Los pesos suman {peso_total:g}% en vez de 100%.')
    if not criterios:
        avisos.append('La rúbrica todavía no tiene criterios.')
    return {'niveles': nombres, 'filas': filas, 'peso_total': peso_total, 'avisos': avisos}


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def matriz_evaluacion(request, id_rubrica):
    """GET /api/evaluacion-docente/rubricas/<id>/matriz/"""
    rubrica = Rubrica.objects.select_related('materia').filter(pk=id_rubrica).first()
    if not rubrica:
        return _no_encontrado('Rúbrica no encontrada.')
    if not _puede_editar(request.user, rubrica):
        return _denegado()
    return Response({'success': True, 'data': {
        'rubrica': RubricaSerializer(rubrica).data,
        'matriz': _matriz(rubrica),
    }})


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def matriz_evaluacion_excel(request, id_rubrica):
    """GET /api/evaluacion-docente/rubricas/<id>/matriz.xlsx

    Reutiliza el generador institucional `_construir_excel_generico_politecnico`
    (mismo membrete azul que los 7 reportes del Decano) en vez de armar
    otro estilo de Excel distinto.
    """
    rubrica = Rubrica.objects.select_related('materia').filter(pk=id_rubrica).first()
    if not rubrica:
        return _no_encontrado('Rúbrica no encontrada.')
    if not _puede_editar(request.user, rubrica):
        return _denegado()

    m = _matriz(rubrica)
    columnas = ['Criterio', 'Peso %'] + m['niveles']
    filas = []
    for fila in m['filas']:
        celdas = []
        for nivel in fila['niveles']:
            if nivel['puntaje'] is None:
                celdas.append('—')
            elif nivel['descriptor']:
                celdas.append(f"{nivel['puntaje']:g} — {nivel['descriptor']}")
            else:
                celdas.append(f"{nivel['puntaje']:g}")
        filas.append([fila['criterio'], f"{fila['peso']:g}"] + celdas)

    from siihapi.frontend_views import _construir_excel_generico_politecnico
    titulo = f'Matriz de evaluación · {rubrica.materia.codigo} · {rubrica.tema}'
    contenido = _construir_excel_generico_politecnico(titulo, columnas, filas)

    resp = HttpResponse(
        contenido,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="matriz_evaluacion_{rubrica.pk}.xlsx"'
    return resp


# ════════════════════════════════════════════════════════════
#  c) Syllabus y auditoría de ajustes
# ════════════════════════════════════════════════════════════
@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def listar_syllabus(request):
    qs = Syllabus.objects.select_related('materia', 'periodo', 'docente__usuario') \
                         .prefetch_related('unidades__actividades')
    if not _es_staff(request.user) and _mi_docente(request.user):
        qs = qs.filter(docente_id=request.user.id_usuario)
    for campo, param in (('materia_id', 'materia'), ('periodo_id', 'periodo')):
        valor = request.GET.get(param)
        if valor:
            if not str(valor).isdigit():
                return Response(
                    {'success': False, 'error': f'{param} debe ser un id numérico.'}, status=400)
            qs = qs.filter(**{campo: int(valor)})
    qs = qs[:LIMITE_LISTADO]
    data = SyllabusSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_syllabus(request):
    docente = _mi_docente(request.user)
    if not docente:
        if not _es_staff(request.user):
            return _denegado('Sólo un Docente (o el staff) puede crear un syllabus.')
        from apps.personal.models import Docente
        docente = Docente.objects.filter(pk=request.data.get('docente')).first()
        if not docente:
            return Response(
                {'success': False, 'error': 'docente es obligatorio cuando lo crea el staff.'},
                status=400)

    ser = SyllabusSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)

    # La versión la calcula el servidor: si la mandara el cliente, dos
    # docentes podrían crear dos "v1" del mismo syllabus a la vez.
    with transaction.atomic():
        ultima = Syllabus.objects.select_for_update().filter(
            materia=ser.validated_data['materia'],
            periodo=ser.validated_data['periodo'],
            docente=docente,
        ).order_by('-version').first()
        version = (ultima.version + 1) if ultima else 1
        syl = ser.save(docente=docente, version=version, estado='BORRADOR')

    return Response({'success': True, 'data': SyllabusSerializer(syl).data}, status=201)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_unidad(request, id_syllabus):
    syl = Syllabus.objects.filter(pk=id_syllabus).first()
    if not syl:
        return _no_encontrado('Syllabus no encontrado.')
    if not _puede_editar(request.user, syl):
        return _denegado()
    ser = UnidadSyllabusSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    unidad = ser.save(syllabus=syl)
    return Response({'success': True, 'data': UnidadSyllabusSerializer(unidad).data}, status=201)


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def crear_actividad(request, id_unidad):
    unidad = UnidadSyllabus.objects.select_related('syllabus').filter(pk=id_unidad).first()
    if not unidad:
        return _no_encontrado('Unidad no encontrada.')
    if not _puede_editar(request.user, unidad.syllabus):
        return _denegado()
    ser = ActividadSyllabusSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'success': False, 'errors': ser.errors}, status=400)
    actividad = ser.save(unidad=unidad)
    return Response({'success': True, 'data': ActividadSyllabusSerializer(actividad).data}, status=201)


# Campos que `ajustar_syllabus` deja cambiar, por tipo de objeto. Lista
# blanca a propósito: sin ella, un `campo` arbitrario del cliente podría
# escribir cualquier atributo del modelo (incluido `docente` o `estado`).
CAMPOS_AJUSTABLES = {
    'SYLLABUS': {'objetivo_general', 'metodologia'},
    'UNIDAD': {'titulo', 'contenidos', 'semanas_estimadas', 'numero'},
    'ACTIVIDAD': {'nombre', 'descripcion', 'fecha_planeada', 'fecha_real', 'estado'},
}


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def ajustar_syllabus(request, id_syllabus):
    """POST /api/evaluacion-docente/syllabus/<id>/ajustar/

    body: {"objeto_tipo": "ACTIVIDAD", "objeto_id": 12,
           "campo": "fecha_real", "valor": "2026-10-20",
           "motivo": "Se corrió por el paro de transporte"}

    El cambio y su registro de auditoría se escriben en la MISMA
    transacción: no puede quedar un ajuste sin su motivo. `motivo` es
    obligatorio — ésa es la razón de ser de este endpoint frente a un
    PATCH normal.
    """
    syl = Syllabus.objects.filter(pk=id_syllabus).first()
    if not syl:
        return _no_encontrado('Syllabus no encontrado.')
    if not _puede_editar(request.user, syl):
        return _denegado('Ajustar el syllabus requiere ser el docente responsable o staff.')

    motivo = (request.data.get('motivo') or '').strip()
    if not motivo:
        return Response(
            {'success': False, 'error': 'motivo es obligatorio para cualquier ajuste.'}, status=400)
    if len(motivo) > 2000:
        return Response({'success': False, 'error': 'motivo supera los 2000 caracteres.'}, status=400)

    objeto_tipo = (request.data.get('objeto_tipo') or '').strip().upper()
    if objeto_tipo not in CAMPOS_AJUSTABLES:
        return Response({
            'success': False,
            'error': f'objeto_tipo debe ser uno de: {", ".join(CAMPOS_AJUSTABLES)}.',
        }, status=400)

    campo = (request.data.get('campo') or '').strip()
    if campo not in CAMPOS_AJUSTABLES[objeto_tipo]:
        return Response({
            'success': False,
            'error': f'campo "{campo}" no es ajustable en {objeto_tipo}. '
                     f'Permitidos: {", ".join(sorted(CAMPOS_AJUSTABLES[objeto_tipo]))}.',
        }, status=400)

    objeto_id = request.data.get('objeto_id')
    if objeto_tipo == 'SYLLABUS':
        objeto = syl
        objeto_id = syl.pk
    elif objeto_tipo == 'UNIDAD':
        objeto = UnidadSyllabus.objects.filter(pk=objeto_id, syllabus=syl).first()
    else:
        objeto = ActividadSyllabus.objects.filter(pk=objeto_id, unidad__syllabus=syl).first()
    if not objeto:
        # Se exige que el objeto pertenezca A ESTE syllabus: si no, se
        # podría ajustar la actividad de otro docente pasando su id.
        return _no_encontrado(f'{objeto_tipo} {objeto_id} no pertenece a este syllabus.')

    # El valor se valida a través del serializer del propio modelo, no a
    # mano: así una fecha mal formada o un estado inexistente da 400 con
    # el mismo mensaje que daría al crear el objeto.
    serializer_cls = {
        'SYLLABUS': SyllabusSerializer,
        'UNIDAD': UnidadSyllabusSerializer,
        'ACTIVIDAD': ActividadSyllabusSerializer,
    }[objeto_tipo]
    parcial = serializer_cls(objeto, data={campo: request.data.get('valor')}, partial=True)
    if not parcial.is_valid():
        return Response({'success': False, 'errors': parcial.errors}, status=400)

    anterior = getattr(objeto, campo)
    with transaction.atomic():
        actualizado = parcial.save()
        nuevo = getattr(actualizado, campo)
        ajuste = HistorialAjusteSyllabus.objects.create(
            syllabus=syl,
            realizado_por=request.user,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            campo=campo,
            valor_anterior='' if anterior is None else str(anterior),
            valor_nuevo='' if nuevo is None else str(nuevo),
            motivo=motivo,
        )

    log.info('[evaluacion_docente] ajuste syllabus %s %s.%s por %s',
             syl.pk, objeto_tipo, campo, request.user.correo)
    return Response({'success': True, 'data': {
        'ajuste': HistorialAjusteSyllabusSerializer(ajuste).data,
        'objeto': serializer_cls(actualizado).data,
    }}, status=201)


@api_view(['GET'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def historial_syllabus(request, id_syllabus):
    """GET /api/evaluacion-docente/syllabus/<id>/historial/"""
    syl = Syllabus.objects.filter(pk=id_syllabus).first()
    if not syl:
        return _no_encontrado('Syllabus no encontrado.')
    if not _puede_editar(request.user, syl):
        return _denegado()
    qs = syl.historial_ajustes.select_related('realizado_por')[:LIMITE_LISTADO]
    data = HistorialAjusteSyllabusSerializer(qs, many=True).data
    return Response({'success': True, 'total': len(data), 'data': data})


@api_view(['POST'])
@authentication_classes(AUTENTICACION)
@permission_classes([IsAuthenticated])
def publicar_syllabus(request, id_syllabus):
    """POST /api/evaluacion-docente/syllabus/<id>/publicar/

    Pone esta versión VIGENTE y archiva la anterior. Queda registrado en
    el historial como cualquier otro ajuste.
    """
    syl = Syllabus.objects.filter(pk=id_syllabus).first()
    if not syl:
        return _no_encontrado('Syllabus no encontrado.')
    if not _puede_editar(request.user, syl):
        return _denegado()
    if syl.estado == 'VIGENTE':
        return Response({'success': True, 'ya_vigente': True,
                         'data': SyllabusSerializer(syl).data})

    motivo = (request.data.get('motivo') or 'Publicación de la versión').strip()
    with transaction.atomic():
        Syllabus.objects.filter(
            materia=syl.materia, periodo=syl.periodo, docente=syl.docente, estado='VIGENTE',
        ).exclude(pk=syl.pk).update(estado='ARCHIVADO')
        anterior = syl.estado
        syl.estado = 'VIGENTE'
        syl.save(update_fields=['estado', 'updated_at'])
        HistorialAjusteSyllabus.objects.create(
            syllabus=syl, realizado_por=request.user, objeto_tipo='SYLLABUS',
            objeto_id=syl.pk, campo='estado', valor_anterior=anterior,
            valor_nuevo='VIGENTE', motivo=motivo,
        )
    return Response({'success': True, 'data': SyllabusSerializer(syl).data})
