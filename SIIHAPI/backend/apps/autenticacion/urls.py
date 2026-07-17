"""SIIHAPI · URLs de autenticación."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = 'autenticacion'

urlpatterns = [
    path('login/',                views.login,                name='login'),
    path('logout/',               views.logout,               name='logout'),
    path('refresh/',              TokenRefreshView.as_view(), name='token_refresh'),
    path('cambiar-contrasena/',   views.cambiar_contrasena,   name='cambiar_contrasena'),
    path('recuperar/',            views.recuperar_contrasena, name='recuperar'),
    path('restablecer/',          views.restablecer_contrasena, name='restablecer'),
    path('yo/',                   views.yo,                   name='yo'),
    path('verificar-hash/',       views.verificar_hash,       name='verificar_hash'),
]
