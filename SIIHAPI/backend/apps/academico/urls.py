"""SIIHAPI - URLs de academico."""
from django.urls import path
from . import views

app_name = 'academico'

urlpatterns = [
    path('ping/',       views.ping,              name='ping'),
    path('facultades/', views.listar_facultades, name='listar_facultades'),
    path('programas/',  views.listar_programas,  name='listar_programas'),
    path('materias/',   views.listar_materias,   name='listar_materias'),
]
