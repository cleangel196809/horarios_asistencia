"""SIIHAPI · apps/aula_virtual — registro en el Django admin."""
from django.contrib import admin

from .models import CanalVirtual, ParticipanteSesion, RecursoCanal, SesionVirtual


@admin.register(CanalVirtual)
class CanalVirtualAdmin(admin.ModelAdmin):
    list_display = ('id_canal', 'nombre', 'materia', 'docente', 'periodo', 'activo')
    list_filter = ('activo', 'periodo')
    search_fields = ('nombre', 'materia__codigo', 'materia__nombre')
    # sala_uuid es la credencial de acceso a la sala: se muestra, no se edita.
    readonly_fields = ('sala_uuid', 'created_at', 'updated_at')


@admin.register(SesionVirtual)
class SesionVirtualAdmin(admin.ModelAdmin):
    list_display = ('id_sesion', 'titulo', 'canal', 'fecha_inicio', 'estado', 'sincronizada_sisca')
    list_filter = ('estado', 'sincronizada_sisca')
    search_fields = ('titulo', 'canal__nombre')
    readonly_fields = ('fecha_cierre', 'fecha_sincronizacion', 'error_sincronizacion')


@admin.register(ParticipanteSesion)
class ParticipanteSesionAdmin(admin.ModelAdmin):
    list_display = ('id_participante', 'sesion', 'usuario', 'hora_entrada', 'hora_salida', 'minutos_acumulados')
    search_fields = ('usuario__correo',)


@admin.register(RecursoCanal)
class RecursoCanalAdmin(admin.ModelAdmin):
    list_display = ('id_recurso', 'titulo', 'canal', 'tipo', 'created_at')
    list_filter = ('tipo',)
    search_fields = ('titulo', 'canal__nombre')
