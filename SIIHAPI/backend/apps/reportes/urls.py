"""SIIHAPI - URLs de reportes."""
from django.urls import path
from . import views

app_name = 'reportes'

urlpatterns = [
    path('ping/',                  views.ping,                          name='ping'),
    path('kpis/',                  views.kpis_globales,                 name='kpis_globales'),
    path('distribucion-sede/',     views.distribucion_por_sede,         name='dist_sede'),
    path('distribucion-programa/', views.distribucion_por_tipo_programa, name='dist_programa'),
]
