"""SIIHAPI · apps/evaluacion_docente — Serializers DRF (modularización, 2026-10-05)."""
from decimal import Decimal

from rest_framework import serializers

from .models import (
    ActividadSyllabus, Calificacion, CriterioRubrica, HistorialAjusteSyllabus,
    NivelDesempeno, Rubrica, Syllabus, UnidadSyllabus,
)

# Escala institucional del Politécnico Internacional.
NOTA_MINIMA = Decimal('0.0')
NOTA_MAXIMA = Decimal('5.0')


class CalificacionSerializer(serializers.ModelSerializer):
    estudiante_nombre = serializers.CharField(
        source='estudiante.usuario.nombre_completo', read_only=True)
    estudiante_codigo = serializers.CharField(source='estudiante.codigo', read_only=True)
    materia_codigo = serializers.CharField(source='materia.codigo', read_only=True)
    origen_label = serializers.CharField(source='get_origen_display', read_only=True)
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)

    class Meta:
        model = Calificacion
        fields = [
            'id_calificacion', 'materia', 'materia_codigo', 'periodo',
            'estudiante', 'estudiante_nombre', 'estudiante_codigo', 'docente',
            'rubrica', 'descripcion', 'nota', 'observaciones', 'origen',
            'origen_label', 'estado', 'estado_label', 'texto_transcrito',
            'confianza_transcripcion', 'confirmado_por', 'fecha_confirmacion',
            'created_at', 'updated_at',
        ]
        # `estado`, `confirmado_por` y `fecha_confirmacion` NO se aceptan del
        # cliente: confirmar es un acto explícito que pasa por su propio
        # endpoint. Si se pudieran mandar aquí, una nota dictada por voz
        # podría nacer ya confirmada y se perdería la revisión humana, que
        # es justamente el punto.
        read_only_fields = [
            'id_calificacion', 'docente', 'estado', 'confirmado_por',
            'fecha_confirmacion', 'created_at', 'updated_at',
        ]

    def validate_nota(self, valor):
        if valor < NOTA_MINIMA or valor > NOTA_MAXIMA:
            raise serializers.ValidationError(
                f'La nota debe estar entre {NOTA_MINIMA} y {NOTA_MAXIMA}.')
        return valor

    def validate_texto_transcrito(self, valor):
        # Texto libre venido de un motor de voz: se acota la longitud para
        # que no entre un payload arbitrariamente grande por esta vía.
        if valor and len(valor) > 5000:
            raise serializers.ValidationError('La transcripción supera los 5000 caracteres.')
        return valor


class NivelDesempenoSerializer(serializers.ModelSerializer):
    class Meta:
        model = NivelDesempeno
        fields = ['id_nivel', 'criterio', 'nombre', 'descriptor', 'puntaje', 'orden']
        read_only_fields = ['id_nivel', 'criterio']


class CriterioRubricaSerializer(serializers.ModelSerializer):
    niveles = NivelDesempenoSerializer(many=True, read_only=True)

    class Meta:
        model = CriterioRubrica
        fields = ['id_criterio', 'rubrica', 'nombre', 'descripcion', 'peso', 'orden', 'niveles']
        read_only_fields = ['id_criterio', 'rubrica']

    def validate_peso(self, valor):
        if valor < 0 or valor > 100:
            raise serializers.ValidationError('El peso es un porcentaje entre 0 y 100.')
        return valor


class RubricaSerializer(serializers.ModelSerializer):
    materia_codigo = serializers.CharField(source='materia.codigo', read_only=True)
    docente_nombre = serializers.CharField(source='docente.usuario.nombre_completo', read_only=True)
    criterios = CriterioRubricaSerializer(many=True, read_only=True)
    peso_total = serializers.SerializerMethodField()

    class Meta:
        model = Rubrica
        fields = [
            'id_rubrica', 'materia', 'materia_codigo', 'docente', 'docente_nombre',
            'periodo', 'tema', 'descripcion', 'activa', 'criterios',
            'peso_total', 'created_at',
        ]
        read_only_fields = ['id_rubrica', 'docente', 'created_at']

    def get_peso_total(self, obj):
        return obj.peso_total


class ActividadSyllabusSerializer(serializers.ModelSerializer):
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)
    dias_desfase = serializers.IntegerField(read_only=True)

    class Meta:
        model = ActividadSyllabus
        fields = [
            'id_actividad', 'unidad', 'nombre', 'descripcion', 'fecha_planeada',
            'fecha_real', 'estado', 'estado_label', 'rubrica', 'dias_desfase',
        ]
        read_only_fields = ['id_actividad', 'unidad']


class UnidadSyllabusSerializer(serializers.ModelSerializer):
    actividades = ActividadSyllabusSerializer(many=True, read_only=True)

    class Meta:
        model = UnidadSyllabus
        fields = [
            'id_unidad', 'syllabus', 'numero', 'titulo', 'contenidos',
            'semanas_estimadas', 'actividades',
        ]
        read_only_fields = ['id_unidad', 'syllabus']


class HistorialAjusteSyllabusSerializer(serializers.ModelSerializer):
    realizado_por_nombre = serializers.CharField(
        source='realizado_por.nombre_completo', read_only=True)

    class Meta:
        model = HistorialAjusteSyllabus
        fields = [
            'id_ajuste', 'syllabus', 'realizado_por', 'realizado_por_nombre',
            'fecha', 'objeto_tipo', 'objeto_id', 'campo', 'valor_anterior',
            'valor_nuevo', 'motivo',
        ]
        # El historial es append-only: desde la API sólo se lee. Se crea en
        # la vista, junto con el ajuste que lo motiva.
        read_only_fields = fields


class SyllabusSerializer(serializers.ModelSerializer):
    materia_codigo = serializers.CharField(source='materia.codigo', read_only=True)
    periodo_codigo = serializers.CharField(source='periodo.codigo', read_only=True)
    docente_nombre = serializers.CharField(source='docente.usuario.nombre_completo', read_only=True)
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)
    unidades = UnidadSyllabusSerializer(many=True, read_only=True)

    class Meta:
        model = Syllabus
        fields = [
            'id_syllabus', 'materia', 'materia_codigo', 'periodo', 'periodo_codigo',
            'docente', 'docente_nombre', 'version', 'estado', 'estado_label',
            'objetivo_general', 'metodologia', 'unidades', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id_syllabus', 'docente', 'version', 'estado', 'created_at', 'updated_at',
        ]
