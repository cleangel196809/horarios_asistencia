"""
SIIHAPI · Modelos de Autenticación y Seguridad.

Mapean al esquema SIIHAPI de Oracle XE 21c. Todas las tablas
llevan el prefijo SIIHAPI_ para no chocar con SISCA, que vive
en la misma instancia Oracle.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UsuarioManager(BaseUserManager):
    """Manager personalizado para usar correo en vez de username."""

    use_in_migrations = True

    def _create_user(self, correo, password, rol, **extra_fields):
        if not correo:
            raise ValueError('El correo institucional es obligatorio.')
        correo = self.normalize_email(correo).lower()
        user = self.model(correo=correo, rol=rol, **extra_fields)
        user.set_password(password)  # hash Argon2id 128 caracteres
        user.save(using=self._db)
        return user

    def create_user(self, correo, password=None, rol='ESTUDIANTE', **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(correo, password, rol, **extra_fields)

    def create_superuser(self, correo, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self._create_user(correo, password, 'ADMINISTRADOR', **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    Usuario base de SIIHAPI con autenticación multi-rol (RF-01).

    El campo `password` heredado de AbstractBaseUser almacena el hash
    Argon2id con salida de 128 caracteres (ver hashers.Argon2id128CharHasher).
    """

    ROL_CHOICES = (
        ('ADMINISTRADOR', 'Administrador'),
        ('COORDINADOR',   'Coordinador Académico'),
        ('DOCENTE',       'Docente'),
        ('ESTUDIANTE',    'Estudiante'),
        # Fase 2 (2026-09-03): roles propios del esquema unificado
        # (integracion_pi/planeación) sin vista dedicada en SIIHAPI todavía.
        # Ver ROL_EQUIVALENCIAS mas abajo para como se mapean a efectos de
        # permisos y dashboard.
        ('ADMIN',                'Administrador (unificado)'),
        ('DECANO',               'Decano'),
        ('SECRETARIA_ACADEMICA', 'Secretaria Academica'),
        # Fase 3 (2026-09-04): roles de SOLO CONSULTA. Ven el mismo
        # dashboard/menu que Coordinador (horarios, docentes, estudiantes,
        # programas y sedes en modo lectura) pero NUNCA pueden ejecutar el
        # Motor IA, aprobar/editar/publicar horarios, hacer carga masiva ni
        # tocar la integracion SISCA. Ver permisos.ROLES_SOLO_CONSULTA.
        ('BIENESTAR_ACADEMICO', 'Bienestar Academico'),
        ('MENTORIAS',           'Mentorias'),
    )

    # Fase 2 (2026-09-03): equivalencias de vocabulario entre el esquema
    # unificado y el vocabulario propio de SIIHAPI. SIIHAPI solo tiene 4
    # "niveles" de acceso (ADMINISTRADOR/COORDINADOR/DOCENTE/ESTUDIANTE); los
    # roles de planeación sin equivalente 1:1 se mapean al nivel mas cercano:
    #   - ADMIN                 -> ADMINISTRADOR (equivalente exacto)
    #   - DECANO                -> COORDINADOR   (academico/horarios/reportes;
    #                                             NO incluye panel ejecutivo/
    #                                             auditoria, reservado a
    #                                             ADMINISTRADOR)
    #   - SECRETARIA_ACADEMICA  -> COORDINADOR   (mismo criterio anterior)
    # Ajustar este diccionario si se necesita otro nivel de acceso.
    ROL_EQUIVALENCIAS = {
        'ADMIN': 'ADMINISTRADOR',
        'DECANO': 'COORDINADOR',
        'SECRETARIA_ACADEMICA': 'COORDINADOR',
        # Fase 3 (2026-09-04): mismo nivel de dashboard que Coordinador,
        # pero de solo consulta -- ver permisos.ROLES_SOLO_CONSULTA (se usa
        # el rol CRUDO, no rol_efectivo, para distinguirlos y bloquearles
        # las acciones que si puede hacer un Coordinador real).
        'BIENESTAR_ACADEMICO': 'COORDINADOR',
        'MENTORIAS': 'COORDINADOR',
    }

    id_usuario = models.AutoField(primary_key=True, db_column='id')
    # Override del campo password (heredado de AbstractBaseUser) para
    # permitir hashes Argon2id de 128 chars en hex + prefijo + salt = 173 chars.
    # El default de Django (128 chars) no alcanza. db_column='password_hash':
    # así se llama la columna en la tabla unificada 'usuarios' (Fase 2).
    password = models.CharField(max_length=255, verbose_name='Contrasena', db_column='password_hash')
    correo = models.EmailField(
        unique=True,
        max_length=120,
        verbose_name='Correo institucional',
        help_text='Correo @pi.edu.co'
    )
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    cedula = models.CharField(max_length=20, unique=True, null=True, blank=True)
    rol = models.CharField(max_length=25, choices=ROL_CHOICES, default='ESTUDIANTE')
    telefono = models.CharField(max_length=20, blank=True)
    estado = models.CharField(
        max_length=1,
        choices=(('A', 'Activo'), ('I', 'Inactivo'), ('B', 'Bloqueado')),
        default='A'
    )

    # Habeas Data (RNF-39, RNF-41)
    acepta_terminos = models.BooleanField(default=False)
    fecha_aceptacion_habeas_data = models.DateTimeField(null=True, blank=True, db_column='fecha_aceptacion_terminos')

    # Control de intentos fallidos (RNF-13)
    intentos_fallidos = models.IntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    # Auditoría temporal
    fecha_creacion = models.DateTimeField(default=timezone.now, db_column='created_at')
    ultimo_login = models.DateTimeField(null=True, blank=True)
    ultima_actividad = models.DateTimeField(null=True, blank=True)

    # Django auth fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UsuarioManager()

    @property
    def rol_efectivo(self):
        """Rol normalizado al vocabulario interno de SIIHAPI, para chequeos
        de permisos y dispatch de dashboard (ver ROL_EQUIVALENCIAS). El campo
        `rol` conserva siempre el valor real guardado en la BD."""
        return self.ROL_EQUIVALENCIAS.get(self.rol, self.rol)

    USERNAME_FIELD = 'correo'
    REQUIRED_FIELDS = ['nombre', 'apellido']

    class Meta:
        # Fase 2 (2026-09-03): tabla compartida con planeación/SISCA vía el
        # esquema unificado de integracion_pi — managed=False, Django NO
        # crea/altera esta tabla, solo lee/escribe sobre la que ya existe.
        managed = False
        db_table = 'usuarios'
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'
        indexes = [
            models.Index(fields=['rol']),
            # NO indexar 'correo': ya tiene unique=True (Oracle ORA-01408).
        ]

    def __str__(self):
        return f'{self.nombre} {self.apellido} ({self.rol})'

    @property
    def nombre_completo(self):
        return f'{self.nombre} {self.apellido}'

    @property
    def avatar_initials(self):
        return f'{self.nombre[:1]}{self.apellido[:1]}'.upper()

    def esta_bloqueado(self):
        """Verifica si la cuenta está bloqueada temporalmente por intentos fallidos."""
        if self.bloqueado_hasta and self.bloqueado_hasta > timezone.now():
            return True
        return False

    def registrar_intento_fallido(self):
        """RNF-13: Bloquear tras 5 intentos en 15 minutos."""
        from datetime import timedelta
        self.intentos_fallidos += 1
        if self.intentos_fallidos >= 5:
            self.bloqueado_hasta = timezone.now() + timedelta(minutes=15)
            self.estado = 'B'
        self.save(update_fields=['intentos_fallidos', 'bloqueado_hasta', 'estado'])

    def resetear_intentos(self):
        if self.intentos_fallidos > 0 or self.bloqueado_hasta:
            self.intentos_fallidos = 0
            self.bloqueado_hasta = None
            if self.estado == 'B':
                self.estado = 'A'
            self.save(update_fields=['intentos_fallidos', 'bloqueado_hasta', 'estado'])


class TokenRecuperacion(models.Model):
    """Token de un solo uso para recuperación de contraseña (RF-02)."""
    id_token = models.AutoField(primary_key=True, db_column='id')
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='tokens_recuperacion')
    token = models.CharField(max_length=128, unique=True)
    fecha_creacion = models.DateTimeField(default=timezone.now, db_column='created_at')
    fecha_expiracion = models.DateTimeField()
    usado = models.BooleanField(default=False)
    fecha_uso = models.DateTimeField(null=True, blank=True)
    ip_solicitante = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'tokens_recuperacion'
        verbose_name = 'Token de Recuperación'
        verbose_name_plural = 'Tokens de Recuperación'

    def es_valido(self):
        return not self.usado and self.fecha_expiracion > timezone.now()


class IntentoLogin(models.Model):
    """Registro de intentos de login para auditoría (RNF-40)."""
    id_intento = models.AutoField(primary_key=True, db_column='id')
    correo = models.CharField(max_length=120)
    exitoso = models.BooleanField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'intentos_login'
        verbose_name = 'Intento de Login'
        verbose_name_plural = 'Intentos de Login'
        indexes = [
            models.Index(fields=['correo', 'fecha']),
        ]
