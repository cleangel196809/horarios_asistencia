"""SIIHAPI · apps/aula_virtual — URLs de la API REST (modularización, 2026-10-05).

Se monta bajo /api/aula-virtual/ en `siihapi/urls.py`. La página HTML con
el iframe de Jitsi se monta aparte, en /dashboard/aula-virtual/.
"""
from django.urls import path

from . import views

app_name = 'aula_virtual'

urlpatterns = [
    path('ping/',                                views.ping,                      name='ping'),

    # Canales
    path('canales/',                             views.listar_canales,            name='listar_canales'),
    path('canales/crear/',                       views.crear_canal,               name='crear_canal'),
    path('canales/<int:id_canal>/',              views.detalle_canal,             name='detalle_canal'),

    # Recursos del canal
    path('canales/<int:id_canal>/recursos/',     views.listar_recursos,           name='listar_recursos'),
    path('canales/<int:id_canal>/recursos/crear/', views.crear_recurso,           name='crear_recurso'),

    # Sesiones
    path('canales/<int:id_canal>/sesiones/',       views.listar_sesiones,         name='listar_sesiones'),
    path('canales/<int:id_canal>/sesiones/crear/', views.crear_sesion,            name='crear_sesion'),
    path('sesiones/<int:id_sesion>/unirme/',       views.unirse_sesion,           name='unirse_sesion'),
    path('sesiones/<int:id_sesion>/salir/',        views.salir_sesion,            name='salir_sesion'),
    path('sesiones/<int:id_sesion>/cerrar/',       views.cerrar_sesion_virtual,   name='cerrar_sesion'),
    path('sesiones/<int:id_sesion>/reintentar-sisca/', views.reintentar_sincronizacion,
         name='reintentar_sincronizacion'),
    path('sesiones/<int:id_sesion>/asistencia/',   views.asistencia_sesion,       name='asistencia_sesion'),
]
