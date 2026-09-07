"""
SIIHAPI · Modelos de Infraestructura (Sedes y Salones).

Datos reales del Politécnico Internacional:
· 3 sedes: Calle 73, Norte, Sur
· 135 salones distribuidos (Calle 73: 65, Sur: 39, Norte: 31)
"""
from django.db import models


class Sede(models.Model):
    """RF-06 · Gestión de las 3 sedes del Politécnico Internacional."""

    CODIGO_CHOICES = (
        ('CLL73', 'Calle 73'),
        ('NORTE', 'Norte'),
        ('SUR',   'Sur'),
    )

    id_sede = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=10, unique=True, choices=CODIGO_CHOICES)
    nombre = models.CharField(max_length=80)
    direccion = models.CharField(max_length=200)
    telefono = models.CharField(max_length=20, blank=True)
    capacidad_total = models.IntegerField(default=0)
    # 'estado' (CHAR 'A'/'I') es una columna adicional agregada a la tabla
    # unificada 'sedes' (Fase 2, 2026-09-03) para no tocar la lógica de
    # SIIHAPI; la tabla ya tenía su propio 'activa' BOOLEAN, usado por
    # planeación, que se deja intacto y sin mapear aquí.
    estado = models.CharField(max_length=1, choices=(('A', 'Activa'), ('I', 'Inactiva')), default='A')
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_column='created_at')

    class Meta:
        # Fase 2 (2026-09-03): compartida con planeación/SISCA.
        managed = False
        db_table = 'sedes'
        verbose_name = 'Sede'
        verbose_name_plural = 'Sedes'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def total_salones(self):
        return self.salones.count()


class Salon(models.Model):
    """RF-07 · Gestión de los 135 salones reales del Politécnico."""

    TIPO_CHOICES = (
        ('AULA',         'Aula tradicional'),
        ('LAB_SIST',     'Sala de Sistemas (Soft)'),
        ('LAB_SALUD',    'Laboratorio de Salud'),
        ('LAB_ENF',      'Laboratorio de Enfermería'),
        ('LAB_AMB',      'Laboratorio Ambiental'),
        ('LAB_MODA',     'Laboratorio de Modas'),
        ('COCINA',       'Cocina'),
        ('REPOSTERIA',   'Repostería'),
        ('MESA_BAR',     'Mesa y Bar (Hospitalidad)'),
        ('CERAMICA',     'Laboratorio de Cerámica'),
        ('YESOS',        'Laboratorio de Yesos'),
        ('METALURGIA',   'Laboratorio de Metalurgia'),
        ('COLADOS',      'Laboratorio de Colados'),
        ('ACRILICOS',    'Laboratorio de Acrílicos'),
        ('ORTODONCIA',   'Laboratorio de Ortodoncia'),
        ('MOTORES',      'Laboratorio de Motores'),
        ('GIMNASIO',     'Gimnasio'),
        ('BIBLIOTECA',   'Biblioteca'),
        ('AUDITORIO',    'Auditorio'),
        ('OFICINA',      'Oficina'),
        ('BODEGA',       'Bodega'),
        ('FLOTANTE',     'Flotante'),
        ('GOURMET',      'Cocina Gourmet'),
        ('CATA',         'Cata y Coctelería'),
    )

    id_salon = models.AutoField(primary_key=True, db_column='id')
    sede = models.ForeignKey(Sede, on_delete=models.CASCADE, related_name='salones')
    codigo = models.CharField(max_length=40)
    nombre = models.CharField(max_length=120)
    capacidad = models.IntegerField()
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='AULA')
    planta = models.CharField(max_length=20, blank=True, help_text='Piso 1, Piso 2, etc.')
    observaciones = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'salones'
        verbose_name = 'Salón'
        verbose_name_plural = 'Salones'
        # La restricción real en la tabla unificada es (sede_id, nombre),
        # no (sede, codigo) — alineado aquí en la Fase 2 (2026-09-03).
        unique_together = [('sede', 'nombre')]
        ordering = ['sede__nombre', 'planta', 'codigo']
        indexes = [
            models.Index(fields=['sede', 'activo']),
            models.Index(fields=['tipo']),
        ]

    def __str__(self):
        return f'{self.codigo} ({self.sede.nombre})'


class Equipamiento(models.Model):
    """RF-10 · Equipamiento asociado a salones."""

    TIPO_CHOICES = (
        ('VIDEOBEAM',   'Video Beam'),
        ('PORTATIL',    'Portátil'),
        ('COMPUTADOR',  'Computador de mesa'),
        ('CAMARA',      'Cámara'),
        ('TELEVISOR',   'Televisor'),
        ('HORNO',       'Horno microondas'),
        ('VENTILADOR',  'Ventilador'),
        ('LAVAMANOS',   'Lavamanos'),
        ('SILLA_SALUD', 'Silla Salud'),
        ('UNIDAD_DENTAL', 'Unidad dental'),
        ('INSTRUMENTAL', 'Instrumental especializado'),
        ('OTRO',        'Otro'),
    )

    id_equipamiento = models.AutoField(primary_key=True, db_column='id')
    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name='equipamiento')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    cantidad = models.IntegerField(default=1)
    descripcion = models.CharField(max_length=200, blank=True)
    operativo = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'salones_equipamiento'
        verbose_name = 'Equipamiento'
        verbose_name_plural = 'Equipamientos'

    def __str__(self):
        return f'{self.get_tipo_display()} x{self.cantidad} en {self.salon.codigo}'
