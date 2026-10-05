"""
SIIHAPI · apps/aula_virtual (modularización, 2026-10-05).

Clases en línea al estilo Odoo eLearning/Discuss, pero sin licencias:
el video es una sala pública de Jitsi Meet embebida en un iframe, y la
identidad de la sala es un UUID propio del canal — nunca el nombre de la
materia, que sería adivinable desde fuera y dejaría entrar a cualquiera.

TODAS las tablas de esta app viven en el esquema `aula_virtual` de la
misma Postgres compartida (ver `siihapi/esquemas.py` y
`SIIHAPI/scripts/esquemas/01_crear_esquema_aula_virtual.sql`). No se
crea ni una sola tabla nueva en `public`: ahí sólo están las tablas
`managed=False` ya existentes (usuarios, materias, docentes_perfil,
periodos) a las que esta app apunta por ForeignKey, sin modificarlas.
"""
import uuid as uuid_lib

from django.conf import settings
from django.db import models

from siihapi.esquemas import tabla

ESQUEMA = 'aula_virtual'


class CanalVirtual(models.Model):
    """Espacio permanente de una materia: el "aula" en sí.

    `sala_uuid` es el identificador de la sala de Jitsi. Es aleatorio y
    único a propósito: `https://meet.jit.si/<uuid>` sólo lo conoce quien
    tenga acceso al canal. Usar la materia o un consecutivo haría la sala
    adivinable, y las salas públicas de Jitsi no piden credenciales.
    """

    id_canal = models.AutoField(primary_key=True)
    materia = models.ForeignKey(
        'academico.Materia', on_delete=models.PROTECT, related_name='canales_virtuales')
    docente = models.ForeignKey(
        'personal.Docente', on_delete=models.PROTECT, related_name='canales_virtuales',
        help_text='Docente responsable del canal (perfil 1:1 sobre usuarios)')
    periodo = models.ForeignKey(
        'matriculas.Periodo', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='canales_virtuales',
        help_text='Ciclo de formación al que pertenece el canal')
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    sala_uuid = models.UUIDField(
        default=uuid_lib.uuid4, unique=True, editable=False,
        help_text='Identificador de la sala pública de Jitsi (no adivinable)')
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = tabla(ESQUEMA, 'canales')
        verbose_name = 'Canal virtual'
        verbose_name_plural = 'Canales virtuales'
        ordering = ['materia__codigo', 'nombre']
        indexes = [models.Index(fields=['materia', 'activo'])]

    def __str__(self):
        return f'{self.nombre} ({self.materia.codigo})'

    @property
    def url_jitsi(self) -> str:
        base = getattr(settings, 'AULA_VIRTUAL_JITSI_BASE_URL', 'https://meet.jit.si').rstrip('/')
        return f'{base}/{self.sala_uuid}'


class SesionVirtual(models.Model):
    """Una clase concreta dentro del canal. Es la unidad que se cierra y
    cuya asistencia se consolida y se envía a SISCA (ver `sisca_sync`)."""

    ESTADO_CHOICES = (
        ('PROGRAMADA', 'Programada'),
        ('EN_CURSO', 'En curso'),
        ('FINALIZADA', 'Finalizada'),
        ('CANCELADA', 'Cancelada'),
    )

    id_sesion = models.AutoField(primary_key=True)
    canal = models.ForeignKey(CanalVirtual, on_delete=models.CASCADE, related_name='sesiones')
    titulo = models.CharField(max_length=200)
    fecha_inicio = models.DateTimeField()
    duracion_minutos = models.PositiveIntegerField(default=60)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='PROGRAMADA')
    grabacion_url = models.URLField(
        blank=True, max_length=500,
        help_text='Opcional: enlace externo a la grabación (Jitsi público no graba en servidor)')
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    cerrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='sesiones_virtuales_cerradas')
    # Estado del envío a SISCA. Se guarda en la sesión (y no sólo en
    # integracion_log) para poder reintentar exactamente las sesiones que
    # quedaron sin sincronizar cuando el circuit breaker estaba abierto.
    sincronizada_sisca = models.BooleanField(default=False)
    fecha_sincronizacion = models.DateTimeField(null=True, blank=True)
    error_sincronizacion = models.TextField(blank=True)

    class Meta:
        db_table = tabla(ESQUEMA, 'sesiones')
        verbose_name = 'Sesión virtual'
        verbose_name_plural = 'Sesiones virtuales'
        ordering = ['-fecha_inicio']
        indexes = [
            models.Index(fields=['canal', 'fecha_inicio']),
            models.Index(fields=['estado', 'sincronizada_sisca']),
        ]

    def __str__(self):
        return f'{self.titulo} · {self.fecha_inicio:%Y-%m-%d %H:%M}'

    @property
    def url_jitsi(self) -> str:
        """Todas las sesiones de un canal comparten la sala: es el mismo
        "salón", en distintos horarios."""
        return self.canal.url_jitsi


class ParticipanteSesion(models.Model):
    """Entrada/salida de un usuario en una sesión — la base de la
    asistencia virtual.

    Es un registro por usuario y sesión (no un log de eventos como
    `apps.eventos.AsistenciaEvento`): a una clase se entra y se sale una
    vez, y lo que interesa para SISCA son los minutos acumulados. Si
    alguien se reconecta se actualiza `hora_salida`, no se crea otra fila.
    """

    id_participante = models.AutoField(primary_key=True)
    sesion = models.ForeignKey(SesionVirtual, on_delete=models.CASCADE, related_name='participantes')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='participaciones_virtuales')
    hora_entrada = models.DateTimeField()
    hora_salida = models.DateTimeField(null=True, blank=True)
    minutos_acumulados = models.PositiveIntegerField(
        default=0, help_text='Se recalcula al cerrar la sesión')

    class Meta:
        db_table = tabla(ESQUEMA, 'participantes_sesion')
        verbose_name = 'Participante de sesión'
        verbose_name_plural = 'Participantes de sesión'
        unique_together = [('sesion', 'usuario')]
        indexes = [models.Index(fields=['sesion', 'usuario'])]
        ordering = ['hora_entrada']

    def __str__(self):
        return f'{self.usuario_id} en sesión {self.sesion_id}'


class RecursoCanal(models.Model):
    """Material de apoyo del canal: PDF, enlace o video.

    Se guarda la URL, no el binario: el repo ya sirve archivos subidos por
    MEDIA_ROOT y duplicar un almacén de archivos aquí no aporta nada.
    """

    TIPO_CHOICES = (
        ('PDF', 'Documento PDF'),
        ('ENLACE', 'Enlace externo'),
        ('VIDEO', 'Video'),
        ('OTRO', 'Otro material'),
    )

    id_recurso = models.AutoField(primary_key=True)
    canal = models.ForeignKey(CanalVirtual, on_delete=models.CASCADE, related_name='recursos')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='ENLACE')
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    url = models.URLField(max_length=500)
    publicado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='recursos_publicados')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = tabla(ESQUEMA, 'recursos_canal')
        verbose_name = 'Recurso del canal'
        verbose_name_plural = 'Recursos del canal'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['canal', 'tipo'])]

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.titulo}'
