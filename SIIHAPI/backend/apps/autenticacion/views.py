"""SIIHAPI · Vistas de autenticación (RF-01 a RF-05)."""
import secrets
from datetime import timedelta
from django.contrib.auth import authenticate, get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import OutstandingToken, BlacklistedToken

from .models import TokenRecuperacion, IntentoLogin
from .serializers import (
    LoginSerializer,
    UsuarioSerializer,
    CambioContrasenaSerializer,
    RecuperarContrasenaSerializer,
    RestablecerContrasenaSerializer,
    emitir_tokens,
)
from .hashers import verificar_longitud_hash

User = get_user_model()


def _get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    RF-01 · POST /api/auth/login/
    Body: {"correo": "...", "contrasena": "...", "rol": "ADMINISTRADOR|COORDINADOR|DOCENTE|ESTUDIANTE"}
    """
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    correo = serializer.validated_data['correo'].lower()
    contrasena = serializer.validated_data['contrasena']
    rol = serializer.validated_data['rol']

    ip = _get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]

    try:
        user = User.objects.get(correo=correo)
    except User.DoesNotExist:
        IntentoLogin.objects.create(correo=correo, exitoso=False, ip=ip, user_agent=user_agent)
        return Response(
            {'success': False, 'error': 'Credenciales inválidas'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # RNF-13: verificar bloqueo
    if user.esta_bloqueado():
        return Response(
            {'success': False, 'error': f'Cuenta bloqueada hasta {user.bloqueado_hasta.isoformat()}'},
            status=status.HTTP_403_FORBIDDEN
        )

    if not user.check_password(contrasena):
        user.registrar_intento_fallido()
        IntentoLogin.objects.create(correo=correo, exitoso=False, ip=ip, user_agent=user_agent)
        return Response(
            {'success': False, 'error': 'Credenciales inválidas'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    if user.rol != rol:
        return Response(
            {'success': False, 'error': 'Rol incorrecto para este usuario'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    if user.estado != 'A':
        return Response(
            {'success': False, 'error': 'Usuario inactivo'},
            status=status.HTTP_403_FORBIDDEN
        )

    # Login exitoso
    user.resetear_intentos()
    user.ultimo_login = timezone.now()
    user.ultima_actividad = timezone.now()
    user.save(update_fields=['ultimo_login', 'ultima_actividad'])

    IntentoLogin.objects.create(correo=correo, exitoso=True, ip=ip, user_agent=user_agent)
    tokens = emitir_tokens(user)

    return Response({
        'success': True,
        'tokens': tokens,
        'user': UsuarioSerializer(user).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """RF-04 · POST /api/auth/logout/  — Invalida el refresh token."""
    refresh = request.data.get('refresh')
    if refresh:
        try:
            from rest_framework_simplejwt.tokens import RefreshToken
            RefreshToken(refresh).blacklist()
        except Exception:
            pass
    return Response({'success': True, 'message': 'Sesión cerrada'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cambiar_contrasena(request):
    """RF-03 · POST /api/auth/cambiar-contrasena/"""
    serializer = CambioContrasenaSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user
    if not user.check_password(serializer.validated_data['contrasena_actual']):
        return Response(
            {'success': False, 'error': 'Contraseña actual incorrecta'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(serializer.validated_data['contrasena_nueva'])
    user.save()

    # Verificar que el hash quedó de 128 caracteres (RNF-07)
    if not verificar_longitud_hash(user.password):
        return Response(
            {'success': False, 'error': 'Error interno: hash no cumple longitud 128'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # Invalidar tokens existentes
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)

    return Response({'success': True, 'message': 'Contraseña actualizada correctamente'})


@api_view(['POST'])
@permission_classes([AllowAny])
def recuperar_contrasena(request):
    """RF-02 · POST /api/auth/recuperar/"""
    serializer = RecuperarContrasenaSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    correo = serializer.validated_data['correo']

    try:
        user = User.objects.get(correo=correo.lower())
    except User.DoesNotExist:
        # No revelamos si el correo existe (seguridad)
        return Response({'success': True, 'message': 'Si el correo existe, recibirás un enlace.'})

    # Generar token de un solo uso (RF-02)
    token_str = secrets.token_urlsafe(64)
    TokenRecuperacion.objects.create(
        usuario=user,
        token=token_str,
        fecha_expiracion=timezone.now() + timedelta(minutes=30),
        ip_solicitante=_get_client_ip(request),
    )

    # Enviar correo
    enlace = f"https://siihapi.pi.edu.co/restablecer/?token={token_str}"
    try:
        send_mail(
            subject='SIIHAPI · Recuperación de contraseña',
            message=f'Hola {user.nombre},\n\nUsa este enlace para restablecer tu contraseña:\n{enlace}\n\nValido por 30 minutos.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.correo],
            fail_silently=True,
        )
    except Exception:
        pass

    return Response({'success': True, 'message': 'Si el correo existe, recibirás un enlace.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def restablecer_contrasena(request):
    """RF-02 · POST /api/auth/restablecer/"""
    serializer = RestablecerContrasenaSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    token_str = serializer.validated_data['token']

    try:
        token = TokenRecuperacion.objects.get(token=token_str)
    except TokenRecuperacion.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Token inválido'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not token.es_valido():
        return Response(
            {'success': False, 'error': 'Token expirado o ya usado'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = token.usuario
    user.set_password(serializer.validated_data['contrasena_nueva'])
    user.resetear_intentos()
    user.save()

    token.usado = True
    token.fecha_uso = timezone.now()
    token.save()

    return Response({'success': True, 'message': 'Contraseña restablecida exitosamente'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def yo(request):
    """GET /api/auth/yo/ — Datos del usuario autenticado."""
    return Response({'success': True, 'user': UsuarioSerializer(request.user).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verificar_hash(request):
    """
    Endpoint de diagnóstico: verifica que el hash del usuario actual
    cumpla con los 128 caracteres requeridos por RNF-07.
    Solo en DEBUG.
    """
    if not settings.DEBUG:
        return Response({'error': 'Solo disponible en modo DEBUG'}, status=403)
    user = request.user
    valido = verificar_longitud_hash(user.password)
    partes = user.password.split('$')
    return Response({
        'algoritmo': partes[0] if len(partes) > 0 else None,
        'longitud_hash_hex': len(partes[2]) if len(partes) > 2 else 0,
        'cumple_rnf_07': valido,
        'esperado': 128,
    })
