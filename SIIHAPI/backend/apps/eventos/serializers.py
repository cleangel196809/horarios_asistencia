"""
SIIHAPI · apps/eventos — Serializers DRF (modularización, 2026-10-05).

Complementan el frontend HTML que ya existe para eventos
(`siihapi/frontend_views.py`, Sprint 3): aquí va la capa REST que consume
el escáner QR en modo PWA/offline y los reportes de asistencia para
ceremonias de grado.

Los modelos NO se tocan — ya estaban entregados y sus tablas viven en
`public`, junto con el resto de SIIHAPI.
"""
from rest_framework import serializers

from .models import (
    AsistenciaEvento, Certificado, Evento, InscripcionEvento, ReservaRecurso,
)


class EventoSerializer(serializers.ModelSerializer):
    """Lectura y escritura de eventos.

    `propuesto_por`, `aprobado_por` y `fecha_aprobacion` son de solo
    lectura: los fija la vista a partir de `request.user`, nunca el
    cliente (si no, cualquiera podría auto-aprobarse un evento mandando
    `aprobado_por` en el payload).
    """

    tipo_label = serializers.CharField(source='get_tipo_display', read_only=True)
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)
    modalidad_label = serializers.CharField(source='get_modalidad_display', read_only=True)
    propuesto_por_nombre = serializers.CharField(
        source='propuesto_por.nombre_completo', read_only=True)
    total_inscritos = serializers.SerializerMethodField()
    cupos_disponibles = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            'id_evento', 'nombre', 'descripcion', 'tipo', 'tipo_label',
            'modalidad', 'modalidad_label', 'facultad', 'programa', 'materia',
            'fecha_inicio', 'fecha_fin', 'cupo_maximo', 'estado', 'estado_label',
            'propuesto_por', 'propuesto_por_nombre', 'aprobado_por',
            'fecha_aprobacion', 'total_inscritos', 'cupos_disponibles',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id_evento', 'estado', 'propuesto_por', 'aprobado_por',
            'fecha_aprobacion', 'created_at', 'updated_at',
        ]

    def get_total_inscritos(self, obj) -> int:
        return obj.inscripciones.filter(estado='INSCRITO').count()

    def get_cupos_disponibles(self, obj):
        if obj.cupo_maximo is None:
            return None
        return max(obj.cupo_maximo - self.get_total_inscritos(obj), 0)

    def validate(self, attrs):
        inicio = attrs.get('fecha_inicio', getattr(self.instance, 'fecha_inicio', None))
        fin = attrs.get('fecha_fin', getattr(self.instance, 'fecha_fin', None))
        if inicio and fin and fin <= inicio:
            raise serializers.ValidationError(
                {'fecha_fin': 'La fecha de fin debe ser posterior a la de inicio.'})
        cupo = attrs.get('cupo_maximo')
        if cupo is not None and cupo == 0:
            raise serializers.ValidationError(
                {'cupo_maximo': 'Deja el cupo vacío para "sin límite"; 0 bloquea el evento entero.'})
        return attrs


class ReservaRecursoSerializer(serializers.ModelSerializer):
    """Reserva de salón/equipamiento. El choque de salón NO se valida aquí
    sino en la vista, que reutiliza `_hay_conflicto_reserva` de
    frontend_views — la misma función que ya usa el flujo HTML, para que
    las dos rutas no puedan divergir."""

    salon_codigo = serializers.CharField(source='salon.codigo', read_only=True)
    sede = serializers.CharField(source='salon.sede.nombre', read_only=True)
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)

    class Meta:
        model = ReservaRecurso
        fields = [
            'id_reserva', 'evento', 'salon', 'salon_codigo', 'sede',
            'equipamiento', 'fecha_inicio', 'fecha_fin', 'estado',
            'estado_label', 'solicitado_por', 'created_at',
        ]
        read_only_fields = ['id_reserva', 'estado', 'solicitado_por', 'created_at']

    def validate(self, attrs):
        inicio, fin = attrs.get('fecha_inicio'), attrs.get('fecha_fin')
        if inicio and fin and fin <= inicio:
            raise serializers.ValidationError(
                {'fecha_fin': 'La fecha de fin debe ser posterior a la de inicio.'})
        return attrs


class InscripcionEventoSerializer(serializers.ModelSerializer):
    """`token_qr` se expone pero NUNCA se acepta como entrada: es el
    secreto que valida el escaneo. El modelo ya lo declara
    `editable=False`, aquí se refuerza explícitamente."""

    usuario_nombre = serializers.CharField(source='usuario.nombre_completo', read_only=True)
    usuario_correo = serializers.CharField(source='usuario.correo', read_only=True)
    evento_nombre = serializers.CharField(source='evento.nombre', read_only=True)
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)
    asistio = serializers.SerializerMethodField()

    class Meta:
        model = InscripcionEvento
        fields = [
            'id_inscripcion', 'evento', 'evento_nombre', 'usuario',
            'usuario_nombre', 'usuario_correo', 'externo_nombre',
            'externo_correo', 'token_qr', 'estado', 'estado_label',
            'asistio', 'fecha_inscripcion',
        ]
        read_only_fields = [
            'id_inscripcion', 'evento', 'usuario', 'token_qr', 'estado',
            'fecha_inscripcion',
        ]

    def get_asistio(self, obj) -> bool:
        return obj.asistencias.filter(direccion='IN').exists()


class AsistenciaEventoSerializer(serializers.ModelSerializer):
    """Un registro de escaneo. `direccion` es de solo lectura: la calcula
    la vista a partir del último registro de la inscripción (patrón IN/OUT
    documentado en models.py), nunca la manda el cliente."""

    usuario_nombre = serializers.CharField(
        source='inscripcion.usuario.nombre_completo', read_only=True)
    direccion_label = serializers.CharField(source='get_direccion_display', read_only=True)

    class Meta:
        model = AsistenciaEvento
        fields = [
            'id_asistencia', 'inscripcion', 'usuario_nombre', 'direccion',
            'direccion_label', 'timestamp', 'escaneado_por', 'latitud',
            'longitud', 'sincronizado_offline',
        ]
        read_only_fields = [
            'id_asistencia', 'inscripcion', 'direccion', 'escaneado_por',
        ]


class CertificadoSerializer(serializers.ModelSerializer):
    """Solo lectura desde la API: la emisión de certificados sigue
    pasando por el flujo HTML (`evento_certificados`), que es el que
    construye el PDF institucional."""

    tipo_label = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nombre = serializers.CharField(
        source='inscripcion.usuario.nombre_completo', read_only=True)

    class Meta:
        model = Certificado
        fields = [
            'id_certificado', 'inscripcion', 'usuario_nombre', 'tipo',
            'tipo_label', 'codigo_verificacion', 'pdf_generado',
            'fecha_emision', 'emitido_por',
        ]
        read_only_fields = fields
