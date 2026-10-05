"""SIIHAPI · apps/evaluacion_docente — URLs de la API REST (2026-10-05).

Se monta bajo /api/evaluacion-docente/ en `siihapi/urls.py`. El endpoint
de transcripción se monta ADEMÁS en /api/notas/transcribir-audio, que es
la ruta que consume el frontend de notas por voz.
"""
from django.urls import path

from . import views

app_name = 'evaluacion_docente'

urlpatterns = [
    path('ping/', views.ping, name='ping'),

    # a) Calificaciones (voz y manuales)
    path('calificaciones/',        views.listar_calificaciones, name='listar_calificaciones'),
    path('calificaciones/crear/',  views.crear_calificacion,    name='crear_calificacion'),
    path('calificaciones/<int:id_calificacion>/confirmar/',
         views.confirmar_calificacion, name='confirmar_calificacion'),
    path('calificaciones/<int:id_calificacion>/descartar/',
         views.descartar_calificacion, name='descartar_calificacion'),

    # b) Rúbricas y matriz de evaluación
    path('rubricas/',                              views.listar_rubricas,   name='listar_rubricas'),
    path('rubricas/crear/',                        views.crear_rubrica,     name='crear_rubrica'),
    path('rubricas/<int:id_rubrica>/criterios/crear/', views.crear_criterio, name='crear_criterio'),
    path('criterios/<int:id_criterio>/niveles/crear/', views.crear_nivel,    name='crear_nivel'),
    path('rubricas/<int:id_rubrica>/matriz/',      views.matriz_evaluacion, name='matriz_evaluacion'),
    path('rubricas/<int:id_rubrica>/matriz.xlsx',  views.matriz_evaluacion_excel,
         name='matriz_evaluacion_excel'),

    # c) Syllabus
    path('syllabus/',                              views.listar_syllabus,   name='listar_syllabus'),
    path('syllabus/crear/',                        views.crear_syllabus,    name='crear_syllabus'),
    path('syllabus/<int:id_syllabus>/unidades/crear/', views.crear_unidad,  name='crear_unidad'),
    path('unidades/<int:id_unidad>/actividades/crear/', views.crear_actividad,
         name='crear_actividad'),
    path('syllabus/<int:id_syllabus>/ajustar/',    views.ajustar_syllabus,  name='ajustar_syllabus'),
    path('syllabus/<int:id_syllabus>/historial/',  views.historial_syllabus, name='historial_syllabus'),
    path('syllabus/<int:id_syllabus>/publicar/',   views.publicar_syllabus, name='publicar_syllabus'),
]
