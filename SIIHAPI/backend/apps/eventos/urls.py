"""SIIHAPI · apps/eventos — URLs de la API REST (modularización, 2026-10-05).

Se monta bajo /api/eventos/ en `siihapi/urls.py`. El frontend HTML del
Sprint 3 sigue viviendo en /dashboard/eventos/ y no se toca.
"""
from django.urls import path

from . import views

app_name = 'eventos'

urlpatterns = [
    path('ping/',                               views.ping,                name='ping'),

    # Eventos
    path('',                                    views.listar_eventos,      name='listar_eventos'),
    path('crear/',                              views.crear_evento,        name='crear_evento'),
    path('<int:id_evento>/',                    views.detalle_evento,      name='detalle_evento'),
    path('<int:id_evento>/aprobar/',            views.aprobar_evento,      name='aprobar_evento'),

    # Reservas de salón/equipamiento
    path('<int:id_evento>/reservas/',           views.crear_reserva,       name='crear_reserva'),

    # Inscripciones y QR
    path('<int:id_evento>/inscribirme/',        views.inscribirse,         name='inscribirse'),
    path('inscripciones/<int:id_inscripcion>/qr/', views.qr_inscripcion,   name='qr_inscripcion'),

    # Escaneo y reporte
    path('<int:id_evento>/escanear/',           views.registrar_escaneo,   name='registrar_escaneo'),
    path('<int:id_evento>/asistencia/',         views.reporte_asistencia,  name='reporte_asistencia'),
]
