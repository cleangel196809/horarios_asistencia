"""SIIHAPI · Admin de autenticación."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, TokenRecuperacion, IntentoLogin


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('correo', 'nombre', 'apellido', 'rol', 'estado', 'ultimo_login')
    list_filter = ('rol', 'estado', 'is_active')
    search_fields = ('correo', 'nombre', 'apellido', 'cedula')
    ordering = ('correo',)

    fieldsets = (
        ('Credenciales', {'fields': ('correo', 'password')}),
        ('Datos personales', {'fields': ('nombre', 'apellido', 'cedula', 'telefono')}),
        ('Rol y permisos', {'fields': ('rol', 'estado', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Habeas Data', {'fields': ('acepta_terminos', 'fecha_aceptacion_habeas_data')}),
        ('Seguridad', {'fields': ('intentos_fallidos', 'bloqueado_hasta')}),
        ('Auditoría', {'fields': ('fecha_creacion', 'ultimo_login', 'ultima_actividad')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('correo', 'nombre', 'apellido', 'rol', 'password1', 'password2'),
        }),
    )
    readonly_fields = ('fecha_creacion', 'ultimo_login', 'ultima_actividad')


@admin.register(TokenRecuperacion)
class TokenRecuperacionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'fecha_creacion', 'fecha_expiracion', 'usado')
    list_filter = ('usado',)
    search_fields = ('usuario__correo',)
    readonly_fields = ('token',)


@admin.register(IntentoLogin)
class IntentoLoginAdmin(admin.ModelAdmin):
    list_display = ('correo', 'exitoso', 'ip', 'fecha')
    list_filter = ('exitoso',)
    search_fields = ('correo', 'ip')
    date_hierarchy = 'fecha'
