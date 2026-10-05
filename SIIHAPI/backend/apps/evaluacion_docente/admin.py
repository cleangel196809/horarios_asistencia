"""SIIHAPI · apps/evaluacion_docente — registro en el Django admin."""
from django.contrib import admin

from .models import (
    ActividadSyllabus, Calificacion, CriterioRubrica, HistorialAjusteSyllabus,
    NivelDesempeno, Rubrica, Syllabus, UnidadSyllabus,
)


@admin.register(Calificacion)
class CalificacionAdmin(admin.ModelAdmin):
    list_display = ('id_calificacion', 'estudiante', 'materia', 'nota', 'origen', 'estado', 'created_at')
    list_filter = ('estado', 'origen', 'materia')
    search_fields = ('descripcion', 'estudiante__codigo')
    # La transcripción original es evidencia: se consulta, no se edita.
    readonly_fields = ('texto_transcrito', 'confianza_transcripcion',
                       'confirmado_por', 'fecha_confirmacion', 'created_at', 'updated_at')


class NivelDesempenoInline(admin.TabularInline):
    model = NivelDesempeno
    extra = 0


@admin.register(CriterioRubrica)
class CriterioRubricaAdmin(admin.ModelAdmin):
    list_display = ('id_criterio', 'nombre', 'rubrica', 'peso', 'orden')
    inlines = [NivelDesempenoInline]


class CriterioInline(admin.TabularInline):
    model = CriterioRubrica
    extra = 0


@admin.register(Rubrica)
class RubricaAdmin(admin.ModelAdmin):
    list_display = ('id_rubrica', 'tema', 'materia', 'docente', 'activa')
    list_filter = ('activa',)
    search_fields = ('tema', 'materia__codigo')
    inlines = [CriterioInline]


class UnidadInline(admin.TabularInline):
    model = UnidadSyllabus
    extra = 0


@admin.register(Syllabus)
class SyllabusAdmin(admin.ModelAdmin):
    list_display = ('id_syllabus', 'materia', 'periodo', 'docente', 'version', 'estado')
    list_filter = ('estado', 'periodo')
    inlines = [UnidadInline]


@admin.register(ActividadSyllabus)
class ActividadSyllabusAdmin(admin.ModelAdmin):
    list_display = ('id_actividad', 'nombre', 'unidad', 'fecha_planeada', 'fecha_real', 'estado')
    list_filter = ('estado',)


@admin.register(HistorialAjusteSyllabus)
class HistorialAjusteSyllabusAdmin(admin.ModelAdmin):
    """Auditoría append-only: desde el admin sólo se lee."""
    list_display = ('id_ajuste', 'syllabus', 'objeto_tipo', 'campo', 'realizado_por', 'fecha')
    list_filter = ('objeto_tipo',)
    search_fields = ('motivo', 'campo')
    readonly_fields = [f.name for f in HistorialAjusteSyllabus._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
