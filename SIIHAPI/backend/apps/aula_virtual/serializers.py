"""SIIHAPI · apps/aula_virtual — Serializers DRF (modularización, 2026-10-05)."""
from rest_framework import serializers

from .models import CanalVirtual, ParticipanteSesion, RecursoCanal, SesionVirtual


class CanalVirtualSerializer(serializers.ModelSerializer):
    materia_codigo = serializers.CharField(source='materia.codigo', read_only=True)
    materia_nombre = serializers.CharField(source='materia.nombre', read_only=True)
    docente_nombre = serializers.CharField(source='docente.usuario.nombre_completo', read_only=True)
    periodo_codigo = serializers.CharField(source='periodo.codigo', read_only=True, default=None)
    url_jitsi = serializers.CharField(read_only=True)
    total_sesiones = serializers.IntegerField(source='sesiones.count', read_only=True)

    class Meta:
        model = CanalVirtual
        fields = [
            'id_canal', 'materia', 'materia_codigo', 'materia_nombre',
            'docente', 'docente_nombre', 'periodo', 'periodo_codigo',
            'nombre', 'descripcion', 'url_jitsi', 'activo', 'total_sesiones',
            'created_at', 'updated_at',
        ]
        # `sala_uuid` NO se expone como campo editable ni se acepta del
        # cliente: es la credencial de acceso a la sala de Jitsi. Sólo se
        # publica ya resuelta dentro de `url_jitsi`, y sólo a quien la vista
        # deja ver el canal.
        read_only_fields = ['id_canal', 'docente', 'created_at', 'updated_at']


class SesionVirtualSerializer(serializers.ModelSerializer):
    canal_nombre = serializers.CharField(source='canal.nombre', read_only=True)
    materia_codigo = serializers.CharField(source='canal.materia.codigo', read_only=True)
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)
    url_jitsi = serializers.CharField(read_only=True)
    total_participantes = serializers.IntegerField(source='participantes.count', read_only=True)

    class Meta:
        model = SesionVirtual
        fields = [
            'id_sesion', 'canal', 'canal_nombre', 'materia_codigo', 'titulo',
            'fecha_inicio', 'duracion_minutos', 'estado', 'estado_label',
            'grabacion_url', 'url_jitsi', 'fecha_cierre', 'cerrada_por',
            'sincronizada_sisca', 'fecha_sincronizacion', 'error_sincronizacion',
            'total_participantes',
        ]
        read_only_fields = [
            'id_sesion', 'canal', 'estado', 'fecha_cierre', 'cerrada_por',
            'sincronizada_sisca', 'fecha_sincronizacion', 'error_sincronizacion',
        ]

    def validate_duracion_minutos(self, valor):
        # Tope de 12 h: una "clase" más larga que eso siempre ha sido un
        # error de captura, y el valor se usa para calcular asistencia.
        if valor < 5 or valor > 720:
            raise serializers.ValidationError('La duración debe estar entre 5 y 720 minutos.')
        return valor


class ParticipanteSesionSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(source='usuario.nombre_completo', read_only=True)
    usuario_correo = serializers.CharField(source='usuario.correo', read_only=True)

    class Meta:
        model = ParticipanteSesion
        fields = [
            'id_participante', 'sesion', 'usuario', 'usuario_nombre',
            'usuario_correo', 'hora_entrada', 'hora_salida', 'minutos_acumulados',
        ]
        read_only_fields = fields


class RecursoCanalSerializer(serializers.ModelSerializer):
    tipo_label = serializers.CharField(source='get_tipo_display', read_only=True)
    publicado_por_nombre = serializers.CharField(
        source='publicado_por.nombre_completo', read_only=True, default=None)

    class Meta:
        model = RecursoCanal
        fields = [
            'id_recurso', 'canal', 'tipo', 'tipo_label', 'titulo',
            'descripcion', 'url', 'publicado_por', 'publicado_por_nombre',
            'created_at',
        ]
        read_only_fields = ['id_recurso', 'canal', 'publicado_por', 'created_at']
