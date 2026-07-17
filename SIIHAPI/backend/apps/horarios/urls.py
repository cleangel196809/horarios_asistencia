"""SIIHAPI - URLs de horarios."""
from django.urls import path
from . import views
from . import api_gestion_docs as gd_api

app_name = 'horarios'

urlpatterns = [
    path('ping/',         views.ping,            name='ping'),
    path('bloques/',      views.listar_bloques,  name='listar_bloques'),
    path('horarios/',     views.listar_horarios, name='listar_horarios'),
    path('mi/',           views.mi_horario,      name='mi_horario'),
    path('ia/historial/', views.historial_ia,    name='historial_ia'),
    # ── Gestión documental inteligente (User-in-the-Loop) ──
    path('docs/sesiones/',                       gd_api.crear_sesion,        name='gd_crear'),
    path('docs/sesiones/<str:sid>/',             gd_api.ver_sesion,          name='gd_ver'),
    path('docs/sesiones/<str:sid>/instruccion/', gd_api.aplicar_instruccion, name='gd_instruccion'),
    path('docs/sesiones/<str:sid>/aprobar/',     gd_api.aprobar_sesion,      name='gd_aprobar'),
    path('docs/sesiones/<str:sid>/publicar-sisca/', gd_api.publicar_en_sisca, name='gd_publicar_sisca'),
]
