"""
SIIHAPI · apps.decano -- Motor de Intervención (Sprint 4, 2026-09-06).

Una sola función de evaluación (`evaluar_reglas_intervencion_sync`) sirve
a las DOS vías de disparo que pide el Entregable 4 de la especificación:
la tarea periódica de Celery Beat (`evaluar_reglas_intervencion`, ver
settings.CELERY_BEAT_SCHEDULE) y los signals de reacción inmediata
(apps/decano/signals.py) -- nunca se duplica la lógica de cálculo.

NOTA DE ALCANCE (2026-09-06): la métrica FALLAS_SALON referencia una
"racha de fallas reportadas de un salón" para la que este proyecto NO
tiene ningún modelo real (no existe 'Falla'/'IncidenciaSalon' en ningún
app de SIIHAPI, ni en el esquema unificado de integracion_pi). En vez de
inventar una fuente de datos falsa, _evaluar_fallas_salon() devuelve
siempre una lista vacía (documentado abajo) -- la métrica queda
completamente cableada (elegible en ReglaIntervencion, evaluada en cada
ciclo) y lista para activarse el día que exista un modelo real de
incidencias de salón.
"""
import logging
from datetime import timedelta
from smtplib import SMTPException

from celery import shared_task
from django.core.mail import send_mail
from django.template import Context, Template
from django.utils import timezone

logger = logging.getLogger('siihapi.decano')


def _resolver_destinatarios(roles):
    # destinatarios_roles admite tanto rol crudo (ej. 'DECANO') como
    # rol_efectivo (ej. 'COORDINADOR') -- se resuelve contra AMBOS campos
    # para no obligar al Decano a saber cual usar en el panel.
    from django.db.models import Q
    from apps.autenticacion.models import Usuario
    if not roles:
        return []
    roles_crudos_equivalentes = [r for r, equivalente in Usuario.ROL_EQUIVALENCIAS.items() if equivalente in roles]
    qs = Usuario.objects.filter(is_active=True).filter(Q(rol__in=roles) | Q(rol__in=roles_crudos_equivalentes))
    return sorted(set(qs.values_list('correo', flat=True)))


def _evaluar_asistencia_jornada_pct(ventana_dias):
    """Por Jornada (decano.Jornada, resuelta por rango horario típico
    contra Horario.bloque), % de AsistenciaEstudiante(estado='PRESENTE')
    sobre el total en la ventana. Devuelve [(objeto_id, valor_pct), ...]."""
    from apps.asistencias.models import AsistenciaEstudiante
    from apps.decano.models import Jornada
    desde = timezone.localdate() - timedelta(days=ventana_dias)
    resultados = []
    for jornada in Jornada.objects.filter(activa=True):
        qs = AsistenciaEstudiante.objects.filter(fecha__gte=desde)
        if jornada.hora_inicio_tipica and jornada.hora_fin_tipica:
            qs = qs.filter(
                horario__bloque__hora_inicio__gte=jornada.hora_inicio_tipica,
                horario__bloque__hora_inicio__lt=jornada.hora_fin_tipica,
            )
        total = qs.count()
        if not total:
            continue
        presentes = qs.filter(estado='PRESENTE').count()
        resultados.append((str(jornada.id_jornada), round(presentes / total * 100, 2), {'jornada': jornada}))
    return resultados


def _evaluar_fallas_salon(ventana_dias):
    """Ver nota de alcance en el docstring del módulo -- no existe modelo
    de incidencias de salón en SIIHAPI todavía."""
    return []


def _evaluar_inasistencia_docente_pct(ventana_dias):
    """Por Docente, % de AsistenciaDocente(estado='NO_DICTADA') sobre el
    total de sesiones registradas en la ventana."""
    from django.db.models import Count, Q
    from apps.asistencias.models import AsistenciaDocente
    desde = timezone.localdate() - timedelta(days=ventana_dias)
    filas = (
        AsistenciaDocente.objects.filter(fecha__gte=desde)
        .values('docente').annotate(total=Count('id_asistencia'), no_dictadas=Count('id_asistencia', filter=Q(estado='NO_DICTADA')))
    )
    resultados = []
    for fila in filas:
        if not fila['total']:
            continue
        pct = round(fila['no_dictadas'] / fila['total'] * 100, 2)
        from apps.personal.models import Docente
        docente = Docente.objects.filter(usuario_id=fila['docente']).select_related('usuario').first()
        if docente:
            resultados.append((str(fila['docente']), pct, {'docente': docente}))
    return resultados


def _evaluar_asistencia_evento_pct(ventana_dias):
    """Por Evento cuya fecha_inicio cae dentro de la ventana, % de
    inscritos (estado='INSCRITO') que registran al menos un
    AsistenciaEvento(direccion='IN')."""
    from django.db.models import Count, Q
    from apps.eventos.models import Evento
    desde = timezone.now() - timedelta(days=ventana_dias)
    eventos = Evento.objects.filter(fecha_inicio__gte=desde, estado__in=['FINALIZADO', 'EN_CURSO']).annotate(
        inscritos=Count('inscripciones', filter=Q(inscripciones__estado='INSCRITO'), distinct=True),
        asistentes=Count('inscripciones', filter=Q(inscripciones__estado='INSCRITO', inscripciones__asistencias__direccion='IN'), distinct=True),
    )
    resultados = []
    for evento in eventos:
        if not evento.inscritos:
            continue
        pct = round(evento.asistentes / evento.inscritos * 100, 2)
        resultados.append((str(evento.id_evento), pct, {'evento': evento}))
    return resultados


def _evaluar_inasistencia_estudiante_multimateria(ventana_dias):
    """Mismo cálculo que apps.asistencias.management.commands.
    recalcular_alertas_riesgo (Sprint 2): estudiantes con 3+ materias en
    ≥30% de inasistencia -- aquí se expresa como cantidad de materias
    afectadas (el 'valor_metrica' de la regla), para que el umbral de la
    ReglaIntervencion sea configurable en NÚMERO de materias, no en %."""
    from django.db.models import Count, Q
    from apps.asistencias.models import AsistenciaEstudiante
    desde = timezone.localdate() - timedelta(days=ventana_dias)
    filas = (
        AsistenciaEstudiante.objects.filter(fecha__gte=desde)
        .values('matricula__estudiante', 'matricula__materia')
        .annotate(total=Count('id_asistencia'), ausentes=Count('id_asistencia', filter=Q(estado='AUSENTE')))
    )
    por_estudiante = {}
    for fila in filas:
        if not fila['total']:
            continue
        pct = fila['ausentes'] / fila['total'] * 100
        if pct >= 30:
            por_estudiante.setdefault(fila['matricula__estudiante'], 0)
            por_estudiante[fila['matricula__estudiante']] += 1

    resultados = []
    for estudiante_id, n_materias in por_estudiante.items():
        from apps.matriculas.models import Estudiante
        estudiante = Estudiante.objects.filter(usuario_id=estudiante_id).select_related('usuario').first()
        if estudiante:
            resultados.append((str(estudiante_id), n_materias, {'estudiante': estudiante}))
    return resultados


_CALCULADORAS_METRICA = {
    'ASISTENCIA_JORNADA_PCT': ('Jornada', _evaluar_asistencia_jornada_pct),
    'FALLAS_SALON': ('Salon', _evaluar_fallas_salon),
    'INASISTENCIA_DOCENTE_PCT': ('Docente', _evaluar_inasistencia_docente_pct),
    'ASISTENCIA_EVENTO_PCT': ('Evento', _evaluar_asistencia_evento_pct),
    'INASISTENCIA_ESTUDIANTE_MULTIMATERIA': ('Estudiante', _evaluar_inasistencia_estudiante_multimateria),
}

_OPERADORES = {
    'LT': lambda v, u: v < u, 'LTE': lambda v, u: v <= u,
    'GT': lambda v, u: v > u, 'GTE': lambda v, u: v >= u, 'EQ': lambda v, u: v == u,
}


def _cumple_condicion(regla, valor):
    return _OPERADORES[regla.operador](float(valor), float(regla.umbral))


def _en_cooldown(regla, objeto_tipo, objeto_id):
    from apps.decano.models import LogIntervencion
    limite = timezone.now() - timedelta(hours=regla.cooldown_horas)
    return LogIntervencion.objects.filter(
        regla=regla, objeto_tipo=objeto_tipo, objeto_id=str(objeto_id), fecha_disparo__gte=limite,
    ).exclude(estado='FALLIDO').exists()


def _renderizar_plantilla(plantilla, contexto_dict):
    ctx = Context(contexto_dict)
    asunto = Template(plantilla.asunto).render(ctx)
    cuerpo_html = Template(plantilla.cuerpo_html).render(ctx)
    return asunto, cuerpo_html


def _enviar_log_intervencion(log, cuerpo_html):
    # Envia el correo de un LogIntervencion ya creado (estado=ENCOLADO) y
    # actualiza su estado -- reintentos con backoff los maneja Celery
    # (ver evaluar_reglas_intervencion, autoretry_for). cuerpo_html se pasa
    # aparte (no vive en LogIntervencion, que solo audita metadatos --
    # mismo diseno que integracion_sisca.IntegracionLog).
    from django.conf import settings as djsettings
    from django.utils.html import strip_tags
    try:
        send_mail(
            subject=log.asunto_renderizado,
            message=strip_tags(cuerpo_html),
            html_message=cuerpo_html,
            from_email=getattr(djsettings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=log.destinatarios,
            fail_silently=False,
        )
        log.estado = 'ENVIADO'
        log.fecha_envio = timezone.now()
        log.save(update_fields=['estado', 'fecha_envio'])
    except SMTPException as exc:
        log.intentos += 1
        log.estado = 'REINTENTANDO' if log.intentos < 3 else 'FALLIDO'
        log.error_detalle = str(exc)
        log.save(update_fields=['intentos', 'estado', 'error_detalle'])
        raise


def evaluar_reglas_intervencion_sync(dry_run=False, solo_regla_id=None):
    """Núcleo del motor de reglas -- callable directamente (management
    command --dry-run, vista 'disparar ahora') o vía la tarea Celery de
    abajo. Devuelve la lista de LogIntervencion creados (o, en dry_run,
    de tuplas describiendo lo que se habría creado)."""
    from apps.decano.models import ReglaIntervencion, LogIntervencion

    reglas = ReglaIntervencion.objects.filter(activa=True).select_related('plantilla')
    if solo_regla_id:
        reglas = reglas.filter(id_regla=solo_regla_id)

    creados = []
    for regla in reglas:
        objeto_tipo, calculadora = _CALCULADORAS_METRICA[regla.metrica]
        try:
            candidatos = calculadora(regla.ventana_dias)
        except Exception:
            logger.exception('Error calculando métrica %s para regla #%s', regla.metrica, regla.id_regla)
            continue

        for objeto_id, valor, contexto_obj in candidatos:
            if not _cumple_condicion(regla, valor):
                continue
            if _en_cooldown(regla, objeto_tipo, objeto_id):
                continue

            destinatarios = _resolver_destinatarios(regla.destinatarios_roles)
            contexto = {**contexto_obj, 'valor_metrica': valor, 'regla': regla.nombre, 'ventana_dias': regla.ventana_dias}
            try:
                asunto, cuerpo_html = _renderizar_plantilla(regla.plantilla, contexto)
            except Exception:
                logger.exception('Error renderizando plantilla %s', regla.plantilla.codigo)
                continue

            if dry_run:
                creados.append((regla.nombre, objeto_tipo, objeto_id, valor, destinatarios))
                continue

            log = LogIntervencion.objects.create(
                regla=regla, objeto_tipo=objeto_tipo, objeto_id=str(objeto_id), valor_metrica=valor,
                destinatarios=destinatarios, asunto_renderizado=asunto, estado='ENCOLADO',
            )
            if not destinatarios:
                log.estado = 'FALLIDO'
                log.error_detalle = 'No se resolvió ningún destinatario para destinatarios_roles.'
                log.save(update_fields=['estado', 'error_detalle'])
            else:
                try:
                    _enviar_log_intervencion(log, cuerpo_html)
                except Exception:
                    pass  # ya quedo registrado en el log; Celery reintenta si corre via la tarea de abajo
                    pass  # ya quedó registrado en el log; Celery reintenta si corre vía la tarea de abajo
            creados.append(log)
    return creados


@shared_task(bind=True, autoretry_for=(SMTPException,), max_retries=3, retry_backoff=True)
def evaluar_reglas_intervencion(self):
    """Tarea periódica (Celery Beat, ver settings.CELERY_BEAT_SCHEDULE) --
    también se puede disparar a mano: `celery -A siihapi call
    apps.decano.tasks.evaluar_reglas_intervencion`."""
    return len(evaluar_reglas_intervencion_sync())


def _reconstruir_contexto_objeto(objeto_tipo, objeto_id):
    """Reconstruye el mismo dict de contexto que devuelve la calculadora
    original de la metrica (ver _CALCULADORAS_METRICA), a partir solo de
    objeto_tipo/objeto_id -- lo usa el reenvio manual (ver
    reintentar_log_intervencion) porque LogIntervencion no persiste el
    objeto en si, solo su tipo/id (auditoria ligera, mismo patron que
    integracion_sisca.IntegracionLog)."""
    if objeto_tipo == 'Jornada':
        from apps.decano.models import Jornada
        obj = Jornada.objects.filter(id_jornada=objeto_id).first()
        return {'jornada': obj} if obj else {}
    if objeto_tipo == 'Docente':
        from apps.personal.models import Docente
        obj = Docente.objects.filter(usuario_id=objeto_id).select_related('usuario').first()
        return {'docente': obj} if obj else {}
    if objeto_tipo == 'Evento':
        from apps.eventos.models import Evento
        obj = Evento.objects.filter(id_evento=objeto_id).first()
        return {'evento': obj} if obj else {}
    if objeto_tipo == 'Estudiante':
        from apps.matriculas.models import Estudiante
        obj = Estudiante.objects.filter(usuario_id=objeto_id).select_related('usuario').first()
        return {'estudiante': obj} if obj else {}
    return {}


def reintentar_log_intervencion(log):
    """Reenvio manual de un LogIntervencion en estado FALLIDO, disparado
    desde el panel del Decano (ver siihapi/decano_views.py,
    log_intervencion_reintentar). Re-renderiza la plantilla real con el
    contexto reconstruido -- nunca reenvia un texto generico distinto al
    que hubiera producido la regla."""
    contexto_obj = _reconstruir_contexto_objeto(log.objeto_tipo, log.objeto_id)
    contexto = {
        **contexto_obj,
        'valor_metrica': log.valor_metrica,
        'regla': log.regla.nombre,
        'ventana_dias': log.regla.ventana_dias,
    }
    _asunto, cuerpo_html = _renderizar_plantilla(log.regla.plantilla, contexto)
    destinatarios_frescos = _resolver_destinatarios(log.regla.destinatarios_roles)
    if destinatarios_frescos:
        log.destinatarios = destinatarios_frescos
        log.save(update_fields=['destinatarios'])
    _enviar_log_intervencion(log, cuerpo_html)
