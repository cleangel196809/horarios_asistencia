"""SIIHAPI · Admin de decano.

Solo se registra PerfilDecano aqui: es el vinculo Usuario<->Facultad que
hoy no tiene ninguna pantalla propia (hueco real identificado). Los demas
modelos de este app (Jornada, MatrizPlaneacion, ReglaIntervencion,
PlantillaCorreo, LogIntervencion) YA se gestionan de punta a punta desde
el panel propio del Decano (ver siihapi/decano_views.py) -- no se
auto-registran aqui a proposito, para no duplicar esa interfaz.
"""
from django.contrib import admin

from .models import PerfilDecano


@admin.register(PerfilDecano)
class PerfilDecanoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'facultades_lista', 'fecha_inicio', 'fecha_fin', 'created_at')
    list_filter = ('fecha_fin',)
    search_fields = ('usuario__correo', 'usuario__nombre', 'usuario__apellido')
    filter_horizontal = ('facultades',)
    autocomplete_fields = ('usuario',)
    readonly_fields = ('created_at', 'created_by')

    def facultades_lista(self, obj):
        return ', '.join(f.nombre for f in obj.facultades.all())
    facultades_lista.short_description = 'Facultades'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
