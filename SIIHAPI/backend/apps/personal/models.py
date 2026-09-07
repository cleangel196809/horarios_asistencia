"""SIIHAPI · Modelos de Personal Docente (RF-16 a RF-20)."""
from django.db import models
from django.conf import settings


class Especialidad(models.Model):
    """RF-19 · Especialidades académicas."""

    id_especialidad = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=120)

    class Meta:
        managed = False
        db_table = 'especialidades'
        verbose_name = 'Especialidad'
        verbose_name_plural = 'Especialidades'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Docente(models.Model):
    """RF-16 · Registro de docentes con tipo de contrato y especialidades."""

    TIPO_CONTRATO_CHOICES = (
        ('TC',       'Tiempo Completo'),
        ('MT',       'Medio Tiempo'),
        ('CATEDRA',  'Catedrático'),
    )

    # Fase 2 (2026-09-03): la tabla unificada 'docentes_perfil' usa
    # usuario_id como PK (perfil 1:1 sobre 'usuarios'), no un id_docente
    # autonumérico separado — se convierte 'usuario' en la PK real (mismo
    # patrón que Estudiante en apps.matriculas).
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='docente',
        primary_key=True,
        db_column='usuario_id',
    )
    # db_table='docentes_especialidades': tabla de unión ya existente en
    # el esquema unificado (Fase 2, 2026-09-03).
    especialidades = models.ManyToManyField(
        Especialidad, related_name='docentes', db_table='docentes_especialidades'
    )
    # Fase 3 (2026-09-04): facultad a la que pertenece el docente -- dato
    # organizacional propio del docente (no derivado de las materias que
    # dicta). Ver alter_docentes_facultad_fase3.sql para la columna nueva
    # en la tabla compartida 'docentes_perfil'. Queda vacia (NULL) para los
    # docentes ya existentes hasta que un administrador la asigne desde
    # /admin/ (Django Admin ya expone CRUD completo de Docente).
    facultad = models.ForeignKey(
        'academico.Facultad', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='docentes', db_column='facultad_id',
    )
    # Fase 3 (2026-09-04): sede fisica a la que pertenece el docente, para
    # tenerla en cuenta en la asignacion de horarios. Igual que facultad:
    # dato propio del docente (no todos los docentes del Excel real tenian
    # una de las 3 sedes fisicas -- ver cargar_docentes_facultad_sede).
    sede = models.ForeignKey(
        'infraestructura.Sede', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='docentes', db_column='sede_id',
    )
    tipo_contrato = models.CharField(max_length=10, choices=TIPO_CONTRATO_CHOICES, default='CATEDRA')
    carga_horaria_max = models.IntegerField(
        default=20,
        help_text='RF-18: Horas semanales máximas según contrato'
    )
    activo = models.BooleanField(default=True)
    fecha_vinculacion = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'docentes_perfil'
        verbose_name = 'Docente'
        verbose_name_plural = 'Docentes'

    def __str__(self):
        return self.usuario.nombre_completo


class DisponibilidadDocente(models.Model):
    """RF-17 · Bloques NO disponibles declarados por cada docente."""

    DIA_CHOICES = (
        ('LU', 'Lunes'), ('MA', 'Martes'), ('MI', 'Miércoles'),
        ('JU', 'Jueves'), ('VI', 'Viernes'), ('SA', 'Sábado'),
    )

    id_disponibilidad = models.AutoField(primary_key=True, db_column='id')
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, related_name='restricciones')
    dia = models.CharField(max_length=2, choices=DIA_CHOICES)
    # La tabla unificada 'docentes_disponibilidad' guarda 'bloque_id' como
    # FK real a bloques_horario(id), no el número de bloque suelto — se
    # convierte a ForeignKey (Fase 2, 2026-09-03). Referencia por string
    # ('horarios.Bloque') para evitar import circular con apps.horarios.
    bloque = models.ForeignKey(
        'horarios.Bloque', on_delete=models.CASCADE, db_column='bloque_id',
        help_text='Bloque horario (1-14)'
    )
    motivo = models.CharField(max_length=200, blank=True)

    class Meta:
        managed = False
        db_table = 'docentes_disponibilidad'
        verbose_name = 'Restricción de disponibilidad'
        verbose_name_plural = 'Restricciones de disponibilidad'
        unique_together = [('docente', 'dia', 'bloque')]

    def __str__(self):
        return f'{self.docente} - {self.get_dia_display()} bloque {self.bloque}'
