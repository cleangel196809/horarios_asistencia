"""
SIIHAPI · apps/eventos (Sprint 3, 2026-09-06).

Diseño adaptado del proyecto de referencia "attendance-system" (control de
asistencia a eventos de grado): QR con token determinístico, registro de
asistencia con dirección IN/OUT (la última fila por inscripción decide si
el próximo escaneo es entrada o salida), modo online/offline. A diferencia
de aquel sistema (Participant de texto libre + Mongo), aquí el inscrito
SIEMPRE es un Usuario real de SIIHAPI -- nunca un registro de texto libre.
"""
import uuid as uuid_lib
from django.conf import settings
from django.db import models


class Evento(models.Model):
    TIPO_CHOICES = (
        ('ACADEMICO', 'Académico'), ('BIENESTAR', 'Bienestar'),
        ('INSTITUCIONAL', 'Institucional'), ('GRADO', 'Ceremonia de grado'),
    )
    MODALIDAD_CHOICES = (('PRESENCIAL', 'Presencial'), ('VIRTUAL', 'Virtual'), ('HIBRIDO', 'Híbrido'))
    ESTADO_CHOICES = (
        ('BORRADOR', 'Borrador'), ('PUBLICADO', 'Publicado'),
        ('EN_CURSO', 'En curso'), ('FINALIZADO', 'Finalizado'), ('CANCELADO', 'Cancelado'),
    )

    id_evento = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    modalidad = models.CharField(max_length=12, choices=MODALIDAD_CHOICES, default='PRESENCIAL')
    # Los "eventos de bienestar" (ferias de salud, jornadas psicológicas,
    # deportivas) son Evento(tipo='BIENESTAR') -- NO se duplica un modelo
    # de evento aparte en apps.bienestar.
    facultad = models.ForeignKey('academico.Facultad', null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos')
    programa = models.ForeignKey('academico.Programa', null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos')
    materia = models.ForeignKey(
        'academico.Materia', null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos',
        help_text='Cuando el evento nace de una propuesta de Docente para su materia')
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    cupo_maximo = models.PositiveIntegerField(null=True, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='BORRADOR')
    propuesto_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='eventos_propuestos')
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos_aprobados')
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'eventos'
        indexes = [models.Index(fields=['fecha_inicio', 'estado'])]
        ordering = ['-fecha_inicio']

    def __str__(self):
        return f'{self.nombre} ({self.fecha_inicio:%Y-%m-%d})'


class ReservaRecurso(models.Model):
    """Reserva de salón/equipamiento para un Evento. Reutiliza
    infraestructura.Salon/Equipamiento -- NO crea un catálogo de espacios
    paralelo. El choque de salón se valida en la vista con la MISMA lógica
    de detección de cruces que ya usa el Motor IA de horarios (ver
    frontend_views._hay_conflicto_reserva)."""
    ESTADO_CHOICES = (('SOLICITADA', 'Solicitada'), ('CONFIRMADA', 'Confirmada'), ('RECHAZADA', 'Rechazada'), ('CANCELADA', 'Cancelada'))
    id_reserva = models.AutoField(primary_key=True)
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='reservas')
    salon = models.ForeignKey('infraestructura.Salon', on_delete=models.PROTECT, related_name='reservas_eventos')
    equipamiento = models.ManyToManyField('infraestructura.Equipamiento', blank=True, related_name='reservas_eventos')
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='SOLICITADA')
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reservas_solicitadas')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eventos_reservas_recurso'
        indexes = [models.Index(fields=['salon', 'fecha_inicio', 'fecha_fin'])]

    def __str__(self):
        return f'{self.salon} para {self.evento} [{self.estado}]'


class InscripcionEvento(models.Model):
    ESTADO_CHOICES = (('INSCRITO', 'Inscrito'), ('CANCELADO', 'Cancelado'), ('LISTA_ESPERA', 'Lista de espera'))
    id_inscripcion = models.AutoField(primary_key=True)
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='inscripciones')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='inscripciones_eventos',
        help_text='Estudiante, Docente o cualquier rol con cuenta SIIHAPI -- nunca un registro de texto libre')
    externo_nombre = models.CharField(max_length=150, blank=True, help_text='Solo si el evento admite invitados externos (ceremonias de grado)')
    externo_correo = models.EmailField(blank=True)
    # Mismo patrón probado en attendance-system: token determinístico, para
    # que reenviar la invitación nunca genere un segundo QR válido.
    token_qr = models.UUIDField(default=uuid_lib.uuid4, unique=True, editable=False)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='INSCRITO')
    fecha_inscripcion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eventos_inscripciones'
        unique_together = [('evento', 'usuario')]
        indexes = [models.Index(fields=['evento', 'estado'])]

    def __str__(self):
        return f'{self.usuario_id} -> {self.evento}'


class AsistenciaEvento(models.Model):
    """Registro de escaneo QR. DIRECCION in/out replica el patrón probado
    de attendance-system: la ÚLTIMA fila por inscripción decide si el
    próximo escaneo es entrada o salida -- permite reportar tanto "asistió
    alguna vez" como "sigue adentro ahora mismo" (Reporte #3 del Decano)."""
    DIRECCION_CHOICES = (('IN', 'Entrada'), ('OUT', 'Salida'))
    id_asistencia = models.AutoField(primary_key=True)
    inscripcion = models.ForeignKey(InscripcionEvento, on_delete=models.CASCADE, related_name='asistencias')
    direccion = models.CharField(max_length=3, choices=DIRECCION_CHOICES, default='IN')
    timestamp = models.DateTimeField()
    escaneado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='escaneos_realizados',
        help_text='Usuario con el rol operativo que escaneó (Secretaría Académica, Docente organizador, etc.)')
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    sincronizado_offline = models.BooleanField(
        default=False, help_text='True si el escaneo se capturó sin conexión y se sincronizó después (cola offline del scanner PWA)')

    class Meta:
        db_table = 'eventos_asistencias'
        indexes = [models.Index(fields=['inscripcion', 'timestamp'])]
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.inscripcion_id} · {self.direccion} · {self.timestamp}'


class Certificado(models.Model):
    """Certificado/constancia digital. Reutiliza el generador PDF genérico
    (frontend_views._construir_pdf_generico_politecnico) con membrete
    institucional -- el PDF se genera al vuelo en la descarga, no se
    almacena un archivo binario en este modelo (solo metadatos + el QR de
    verificación impreso en el propio PDF)."""
    TIPO_CHOICES = (('ASISTENCIA', 'Asistencia'), ('PARTICIPACION', 'Participación'), ('GRADO', 'Grado'))
    id_certificado = models.AutoField(primary_key=True)
    inscripcion = models.OneToOneField(InscripcionEvento, on_delete=models.CASCADE, related_name='certificado')
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES, default='ASISTENCIA')
    codigo_verificacion = models.UUIDField(default=uuid_lib.uuid4, unique=True, editable=False, help_text='QR de verificación impreso en el certificado')
    pdf_generado = models.BooleanField(default=False)
    fecha_emision = models.DateTimeField(null=True, blank=True)
    emitido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='certificados_emitidos')

    class Meta:
        db_table = 'eventos_certificados'

    def __str__(self):
        return f'Certificado {self.tipo} · {self.inscripcion_id}'
