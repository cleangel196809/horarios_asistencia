"""SIIHAPI · Serializers de autenticación."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """RF-01: Autenticación con correo + contraseña + rol."""
    correo = serializers.EmailField()
    contrasena = serializers.CharField(write_only=True)
    rol = serializers.ChoiceField(choices=User.ROL_CHOICES)


class UsuarioSerializer(serializers.ModelSerializer):
    """Serializer público (sin password) para devolver datos del usuario."""
    nombre_completo = serializers.CharField(read_only=True)
    avatar_initials = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id_usuario', 'correo', 'nombre', 'apellido', 'rol',
            'cedula', 'telefono', 'estado',
            'nombre_completo', 'avatar_initials',
            'fecha_creacion', 'ultimo_login',
        ]
        read_only_fields = ['id_usuario', 'fecha_creacion', 'ultimo_login']


class CambioContrasenaSerializer(serializers.Serializer):
    """RF-03: Cambio de contraseña con política RNF-12."""
    contrasena_actual = serializers.CharField(write_only=True)
    contrasena_nueva = serializers.CharField(write_only=True)
    contrasena_confirma = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['contrasena_nueva'] != attrs['contrasena_confirma']:
            raise serializers.ValidationError({
                'contrasena_confirma': 'Las contraseñas no coinciden.'
            })
        validate_password(attrs['contrasena_nueva'])
        return attrs


class RecuperarContrasenaSerializer(serializers.Serializer):
    """RF-02: Solicitud de recuperación de contraseña."""
    correo = serializers.EmailField()


class RestablecerContrasenaSerializer(serializers.Serializer):
    """RF-02: Restablecimiento usando token."""
    token = serializers.CharField()
    contrasena_nueva = serializers.CharField(write_only=True)
    contrasena_confirma = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['contrasena_nueva'] != attrs['contrasena_confirma']:
            raise serializers.ValidationError({
                'contrasena_confirma': 'Las contraseñas no coinciden.'
            })
        validate_password(attrs['contrasena_nueva'])
        return attrs


def emitir_tokens(user):
    """Genera tokens JWT (access + refresh) para un usuario."""
    refresh = RefreshToken.for_user(user)
    refresh['rol'] = user.rol
    refresh['nombre'] = user.nombre_completo
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }
