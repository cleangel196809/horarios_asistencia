"""
SIIHAPI · apps/evaluacion_docente (modularización, 2026-10-05).

Tres cosas que hoy el docente hace fuera del sistema:

  a) tomar notas de clase y convertirlas en calificaciones (por voz),
  b) evaluar con rúbricas y poder exportar la matriz criterios × niveles,
  c) ajustar el syllabus durante el ciclo dejando rastro de por qué.

Todas las tablas viven en el esquema `evaluacion_docente` de la Postgres
compartida (ver `siihapi/esquemas.py` y
`SIIHAPI/scripts/esquemas/02_crear_esquema_evaluacion_docente.sql`). Nada
se crea en `public`; las FK apuntan a las tablas `managed=False` que ya
están ahí (usuarios, materias, docentes_perfil, estudiantes_perfil,
periodos) sin modificarlas.

Regla transversal: NADA se guarda como definitivo sin que una persona lo
confirme. Una nota dictada por voz nace en BORRADOR y sólo cuenta cuando
el docente la confirma -- un error de transcripción no puede convertirse
en la nota de alguien.
"""
from django.conf import settings
from django.db import models

from siihapi.esquemas import tabla

ESQUEMA = 'evaluacion_docente'


# ════════════════════════════════════════════════════════════
#  a) Notas por voz
# ════════════════════════════════════════════════════════════
class Calificacion(models.Model):
    """Una nota de un estudiante en una materia.

    `origen` distingue si se dictó por voz o se escribió a mano, y
    `estado` separa el borrador de lo confirmado. Las dos cosas juntas son
    lo que permite auditar después "esta nota vino de una transcripción y
    la confirmó tal persona a tal hora".
    """

    ORIGEN_CHOICES = (('VOZ', 'Dictada por voz'), ('MANUAL', 'Escrita a mano'))
    ESTADO_CHOICES = (('BORRADOR', 'Borrador'), ('CONFIRMADO', 'Confirmado'))

    id_calificacion = models.AutoField(primary_key=True)
    materia = models.ForeignKey(
        'academico.Materia', on_delete=models.PROTECT, related_name='calificaciones_docente')
    periodo = models.ForeignKey(
        'matriculas.Periodo', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='calificaciones_docente')
    estudiante = models.ForeignKey(
        'matriculas.Estudiante', on_delete=models.PROTECT, related_name='calificaciones_docente')
    docente = models.ForeignKey(
        'personal.Docente', on_delete=models.PROTECT, related_name='calificaciones_registradas')
    rubrica = models.ForeignKey(
        'evaluacion_docente.Rubrica', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='calificaciones',
        help_text='Opcional: rúbrica con la que se evaluó')

    descripcion = models.CharField(max_length=200, help_text='Actividad evaluada')
    # Escala 0.0–5.0 del Politécnico. Se valida en el serializer, no sólo
    # aquí, porque las notas también entran por la API.
    nota = models.DecimalField(max_digits=4, decimal_places=2)
    observaciones = models.TextField(blank=True)

    origen = models.CharField(max_length=8, choices=ORIGEN_CHOICES, default='MANUAL')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='BORRADOR')
    # Se conserva el texto crudo que produjo la transcripción: es la
    # evidencia de qué se dictó, frente a lo que el docente terminó
    # guardando. Sin esto no hay forma de revisar un reclamo.
    texto_transcrito = models.TextField(
        blank=True, help_text='Transcripción original, tal cual llegó (sólo origen=VOZ)')
    confianza_transcripcion = models.FloatField(
        null=True, blank=True, help_text='0..1 reportado por el motor de voz, si lo reporta')

    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='calificaciones_confirmadas')
    fecha_confirmacion = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = tabla(ESQUEMA, 'calificaciones')
        verbose_name = 'Calificación'
        verbose_name_plural = 'Calificaciones'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['materia', 'periodo', 'estado']),
            models.Index(fields=['estudiante', 'materia']),
            models.Index(fields=['estado', 'origen']),
        ]

    def __str__(self):
        return f'{self.estudiante_id} · {self.materia_id} · {self.nota} [{self.estado}]'


# ════════════════════════════════════════════════════════════
#  b) Rúbricas y matriz de evaluación
# ════════════════════════════════════════════════════════════
class Rubrica(models.Model):
    """Rúbrica de evaluación de un tema/materia, propia de un docente."""

    id_rubrica = models.AutoField(primary_key=True)
    materia = models.ForeignKey(
        'academico.Materia', on_delete=models.PROTECT, related_name='rubricas')
    docente = models.ForeignKey(
        'personal.Docente', on_delete=models.PROTECT, related_name='rubricas')
    periodo = models.ForeignKey(
        'matriculas.Periodo', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='rubricas')
    tema = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = tabla(ESQUEMA, 'rubricas')
        verbose_name = 'Rúbrica'
        verbose_name_plural = 'Rúbricas'
        ordering = ['materia__codigo', 'tema']
        indexes = [models.Index(fields=['materia', 'activa'])]

    def __str__(self):
        return f'{self.tema} ({self.materia_id})'

    @property
    def peso_total(self):
        """Suma de los pesos de sus criterios. Debería ser 100; la vista
        avisa cuando no lo es en vez de corregirlo sola — repartir el peso
        es una decisión del docente, no del sistema."""
        return sum((c.peso for c in self.criterios.all()), start=0)


class CriterioRubrica(models.Model):
    """Criterio evaluable dentro de una rúbrica, con su peso relativo."""

    id_criterio = models.AutoField(primary_key=True)
    rubrica = models.ForeignKey(Rubrica, on_delete=models.CASCADE, related_name='criterios')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    peso = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Porcentaje sobre 100 dentro de la rúbrica')
    orden = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = tabla(ESQUEMA, 'criterios_rubrica')
        verbose_name = 'Criterio de rúbrica'
        verbose_name_plural = 'Criterios de rúbrica'
        ordering = ['orden', 'id_criterio']
        unique_together = [('rubrica', 'nombre')]

    def __str__(self):
        return f'{self.nombre} ({self.peso}%)'


class NivelDesempeno(models.Model):
    """Nivel de desempeño de un criterio (ej. Superior / Alto / Básico /
    Bajo) con el puntaje que otorga. Criterios × niveles ES la matriz de
    evaluación que se exporta."""

    id_nivel = models.AutoField(primary_key=True)
    criterio = models.ForeignKey(
        CriterioRubrica, on_delete=models.CASCADE, related_name='niveles')
    nombre = models.CharField(max_length=100)
    descriptor = models.TextField(
        blank=True, help_text='Qué tiene que hacer el estudiante para quedar en este nivel')
    puntaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    orden = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = tabla(ESQUEMA, 'niveles_desempeno')
        verbose_name = 'Nivel de desempeño'
        verbose_name_plural = 'Niveles de desempeño'
        ordering = ['orden', '-puntaje']
        unique_together = [('criterio', 'nombre')]

    def __str__(self):
        return f'{self.nombre} ({self.puntaje})'


# ════════════════════════════════════════════════════════════
#  c) Syllabus y sus ajustes
# ════════════════════════════════════════════════════════════
class Syllabus(models.Model):
    """Plan de la materia para un periodo, versionado.

    Versionar importa: cuando el docente reorganiza el plan a mitad de
    ciclo, lo que se entregó al principio sigue existiendo. El
    `HistorialAjusteSyllabus` guarda el porqué de cada cambio.
    """

    ESTADO_CHOICES = (
        ('BORRADOR', 'Borrador'),
        ('VIGENTE', 'Vigente'),
        ('ARCHIVADO', 'Archivado'),
    )

    id_syllabus = models.AutoField(primary_key=True)
    materia = models.ForeignKey(
        'academico.Materia', on_delete=models.PROTECT, related_name='syllabus')
    periodo = models.ForeignKey(
        'matriculas.Periodo', on_delete=models.PROTECT, related_name='syllabus')
    docente = models.ForeignKey(
        'personal.Docente', on_delete=models.PROTECT, related_name='syllabus')
    version = models.PositiveIntegerField(default=1)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='BORRADOR')
    objetivo_general = models.TextField(blank=True)
    metodologia = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = tabla(ESQUEMA, 'syllabus')
        verbose_name = 'Syllabus'
        verbose_name_plural = 'Syllabus'
        unique_together = [('materia', 'periodo', 'docente', 'version')]
        ordering = ['-version']
        indexes = [models.Index(fields=['materia', 'periodo', 'estado'])]

    def __str__(self):
        return f'Syllabus {self.materia_id} {self.periodo_id} v{self.version}'


class UnidadSyllabus(models.Model):
    """Unidad temática dentro del syllabus."""

    id_unidad = models.AutoField(primary_key=True)
    syllabus = models.ForeignKey(Syllabus, on_delete=models.CASCADE, related_name='unidades')
    numero = models.PositiveIntegerField(default=1)
    titulo = models.CharField(max_length=200)
    contenidos = models.TextField(blank=True)
    semanas_estimadas = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = tabla(ESQUEMA, 'unidades_syllabus')
        verbose_name = 'Unidad del syllabus'
        verbose_name_plural = 'Unidades del syllabus'
        ordering = ['numero']
        unique_together = [('syllabus', 'numero')]

    def __str__(self):
        return f'U{self.numero}. {self.titulo}'


class ActividadSyllabus(models.Model):
    """Actividad planeada de una unidad: lo planeado contra lo real.

    `fecha_planeada` vs `fecha_real` es justamente el dato que hoy no
    queda registrado en ningún lado y que permite ver cuánto se desfasó
    el curso.
    """

    ESTADO_CHOICES = (
        ('PLANEADA', 'Planeada'),
        ('EN_CURSO', 'En curso'),
        ('COMPLETADA', 'Completada'),
        ('REPROGRAMADA', 'Reprogramada'),
        ('CANCELADA', 'Cancelada'),
    )

    id_actividad = models.AutoField(primary_key=True)
    unidad = models.ForeignKey(
        UnidadSyllabus, on_delete=models.CASCADE, related_name='actividades')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    fecha_planeada = models.DateField()
    fecha_real = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=13, choices=ESTADO_CHOICES, default='PLANEADA')
    rubrica = models.ForeignKey(
        Rubrica, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='actividades', help_text='Rúbrica con la que se evalúa esta actividad')

    class Meta:
        db_table = tabla(ESQUEMA, 'actividades_syllabus')
        verbose_name = 'Actividad del syllabus'
        verbose_name_plural = 'Actividades del syllabus'
        ordering = ['fecha_planeada']
        indexes = [models.Index(fields=['unidad', 'estado'])]

    def __str__(self):
        return f'{self.nombre} ({self.fecha_planeada})'

    @property
    def dias_desfase(self):
        """Días de diferencia entre lo planeado y lo real. None mientras
        la actividad no se haya ejecutado — 0 significaría "a tiempo", que
        no es lo mismo que "todavía no pasó"."""
        if not self.fecha_real:
            return None
        return (self.fecha_real - self.fecha_planeada).days


class HistorialAjusteSyllabus(models.Model):
    """Auditoría OBLIGATORIA de cada ajuste al syllabus.

    Es append-only por diseño: nunca se edita ni se borra una fila. El
    `motivo` no es opcional — un ajuste sin justificación es exactamente
    lo que este modelo existe para evitar.
    """

    id_ajuste = models.AutoField(primary_key=True)
    syllabus = models.ForeignKey(
        Syllabus, on_delete=models.CASCADE, related_name='historial_ajustes')
    realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ajustes_syllabus')
    fecha = models.DateTimeField(auto_now_add=True)
    objeto_tipo = models.CharField(
        max_length=20, help_text='SYLLABUS | UNIDAD | ACTIVIDAD')
    objeto_id = models.IntegerField(null=True, blank=True)
    campo = models.CharField(max_length=60, blank=True)
    valor_anterior = models.TextField(blank=True)
    valor_nuevo = models.TextField(blank=True)
    motivo = models.TextField(help_text='Obligatorio: por qué se hizo el ajuste')

    class Meta:
        db_table = tabla(ESQUEMA, 'historial_ajustes_syllabus')
        verbose_name = 'Ajuste del syllabus'
        verbose_name_plural = 'Historial de ajustes del syllabus'
        ordering = ['-fecha']
        indexes = [models.Index(fields=['syllabus', '-fecha'])]

    def __str__(self):
        return f'{self.objeto_tipo}#{self.objeto_id} {self.campo} @ {self.fecha:%Y-%m-%d}'
