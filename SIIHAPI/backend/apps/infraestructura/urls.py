"""SIIHAPI - URLs de infraestructura."""
from django.urls import path
from . import views

app_name = 'infraestructura'

urlpatterns = [
    path('ping/',                 views.ping,           name='ping'),
    path('sedes/',                views.listar_sedes,   name='listar_sedes'),
    path('salones/',              views.listar_salones, name='listar_salones'),
    path('salones/<str:codigo>/', views.detalle_salon,  name='detalle_salon'),
]
