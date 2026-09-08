"""
SIIHAPI · apps/decano (Sprint 4, 2026-09-06) — Tablero de Mando, Motor de
Planeación y Motor de Intervención del rol DECANO.

Grounding: el rol 'DECANO' YA EXISTE en autenticacion.Usuario.ROL_CHOICES,
pero ROL_EQUIVALENCIAS lo mapea a 'COORDINADOR' -- ve el mismo dashboard
que un Coordinador, sin panel propio. Este app le da un panel real (ver
permisos.decano_required, ya existente desde Sprint 2).
academico.Facultad.decano es HOY solo texto libre (decano_nombre, sin FK
a Usuario) -- PerfilDecano cierra ese vacío.

Colisión evitada a propósito: horarios.ReglaNegocio YA EXISTE (tabla
reglas_negocio) pero es la regla declarativa que consume el solver CSP
(OR-Tools) para generar horarios -- nada que ver con este motor de
intervención por correo. Por eso el modelo de reglas se llama
ReglaIntervencion, nunca ReglaNegocio. Del mismo modo, la "simulación
what-if" reutiliza horarios.AsignacionIA (ya trackea corridas del Motor
IA real) via el campo MatrizPlaneacion.asignacion_ia, en vez de crear un
motor de simulación paralelo -- ver frontend_views.matriz_planeacion_*.
"""
from django.conf import settings
from django.db import models


class Jornada(models.Model):
    """Catálogo nuevo -- hoy 'jornada' solo existe como texto libre en el
    Excel de carga de horarios. Se normaliza porque el Decano la necesita
    como dimensión de corte en varios reportes."""
    id_jornada = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=40, unique=True)
    hora_inicio_tipica = models.TimeField(null=True, blank=True)
    hora_fin_tipica = models.TimeField(null=True, blank=True)
    orden = models.PositiveSmallIntegerField(default=0, help_text='Para ordenar Mañana<Tarde<Noche<Especial en reportes')
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'decano_jornadas'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class PerfilDecano(models.Model):
    """Liga un Usuario (rol crudo 'DECANO') a la(s) Facultad(es) que
    dirige. Complementa academico.Facultad.decano (texto libre) con una
    relación real y consultable por el ORM."""
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil_decano')
    facultades = models.ManyToManyField(
        'academico.Facultad', related_name='decanos_asignados',
        help_text='Un Decano puede dirigir 1 o más facultades (ej. facultades hermanas en distinta sede)')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True, help_text='Vacío = periodo vigente')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', editable=False)

    class Meta:
        db_table = 'decano_perfiles'

    def __str__(self):
        return f'Decano: {self.usuario_id}'


class MatrizPlaneacion(models.Model):
    ESTADO_CHOICES = (
        ('BORRADOR', 'Borrador'),
        ('EN_REVISION', 'En revisión'),
        ('APROBADO', 'Aprobado'),
        ('PUBLICADO', 'Publicado'),
    )
    id_matriz = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150, help_text='Ej. "Matriz Ingeniería 2026-3T"')
    facultad = models.ForeignKey('academico.Facultad', on_delete=models.PROTECT, related_name='matrices_planeacion')
    periodo = models.ForeignKey('matriculas.Periodo', on_delete=models.PROTECT, related_name='matrices_planeacion')
    sede = models.ForeignKey('infraestructura.Sede', on_delete=models.PROTECT, related_name='matrices_planeacion')
    jornada = models.ForeignKey(Jornada, on_delete=models.PROTECT, related_name='matrices_planeacion')
    ciclo = models.CharField(max_length=10, help_text='Mismo dominio que academico.Materia.ciclo (texto, no siempre numérico)')
    parametros_simulacion = models.JSONField(
        default=dict, blank=True,
        help_text='Snapshot de los parámetros usados en la corrida "what-if" (docentes/salones candidatos, reglas activas)')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='BORRADOR')
    continua_de = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='continuaciones',
        help_text=(
            'Matriz del periodo anterior de la que esta es continuidad (mismo eje matriculas.Periodo, '
            'no el campo ciclo -- ver matriz_planeacion_continuar en decano_views.py). Columna aditiva, '
            'ninguna matriz existente se ve afectada por su ausencia.'
        ),
    )
    asignacion_ia = models.ForeignKey(
        'horarios.AsignacionIA', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='matrices_planeacion',
        help_text='Corrida real del Motor IA (OR-Tools) que materializó esta matriz -- reutiliza el motor existente, nunca se reimplementa')
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    publicado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    fecha_publicacion = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='matrices_creadas')

    class Meta:
        db_table = 'decano_matrices_planeacion'
        indexes = [models.Index(fields=['facultad', 'periodo', 'estado'])]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.nombre} [{self.estado}]'


class GrupoPlaneacion(models.Model):
    """Grupo (seccion) de una Materia dentro de una MatrizPlaneacion --
    Sprint 4b (2026-09-08). Cierra el hueco de planeacion a nivel de grupo
    individual: activo/inactivo (decide si sigue al siguiente periodo),
    docente asignado (con preseleccion automatica desde el grupo del
    periodo anterior via grupo_origen, igual que MatrizPlaneacion.continua_de),
    y es_transversal (si es True, el docente se busca entre TODOS los
    docentes de la institucion, no solo los de la facultad de la matriz --
    ver matriz_planeacion_continuar en decano_views.py, que copia los
    grupos activos al crear la continuacion)."""
    id_grupo = models.AutoField(primary_key=True)
    matriz = models.ForeignKey(MatrizPlaneacion, on_delete=models.CASCADE, related_name='grupos')
    materia = models.ForeignKey('academico.Materia', on_delete=models.PROTECT, related_name='grupos_planeacion')
    numero_grupo = models.CharField(max_length=10, help_text='Ej. "01"')
    activo = models.BooleanField(default=True, help_text='Si sigue activo -- se copia al continuar al siguiente periodo')
    es_transversal = models.BooleanField(default=False, help_text='Si es materia transversal, el docente se busca entre TODOS los docentes, no solo los de la facultad')
    docente = models.ForeignKey('personal.Docente', null=True, blank=True, on_delete=models.SET_NULL, related_name='grupos_planeacion')
    grupo_origen = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='continuaciones',
        help_text='Grupo del periodo anterior del que este es continuidad -- se usa para preseleccionar el docente')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='grupos_planeacion_creados')

    class Meta:
        db_table = 'decano_grupos_planeacion'
        unique_together = [('matriz', 'materia', 'numero_grupo')]
        ordering = ['materia__nombre', 'numero_grupo']

    def __str__(self):
        return f'{self.materia.nombre} — Grupo {self.numero_grupo} ({self.matriz.nombre})'


class ReglaIntervencion(models.Model):
    """Motor de reglas declarativas Decano -> acción (correo). El Decano la
    crea/edita/activa desde un panel, sin tocar código."""
    METRICA_CHOICES = (
        ('ASISTENCIA_JORNADA_PCT', '% asistencia de una Jornada'),
        ('FALLAS_SALON', 'Fallas reportadas de un salón (racha)'),
        ('INASISTENCIA_DOCENTE_PCT', '% inasistencia propia de un docente'),
        ('ASISTENCIA_EVENTO_PCT', '% asistencia de inscritos a un evento'),
        ('INASISTENCIA_ESTUDIANTE_MULTIMATERIA', '% inasistencia de un estudiante en 3+ materias'),
    )
    OPERADOR_CHOICES = (('LT', '<'), ('LTE', '<='), ('GT', '>'), ('GTE', '>='), ('EQ', '='))

    id_regla = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    metrica = models.CharField(max_length=40, choices=METRICA_CHOICES)
    operador = models.CharField(max_length=3, choices=OPERADOR_CHOICES)
    umbral = models.DecimalField(max_digits=6, decimal_places=2, help_text='Ej. 80.00 para "< 80%", o 3 para "3+ materias"')
    ventana_dias = models.PositiveIntegerField(default=7, help_text='Ventana de evaluación de la métrica, en días')
    destinatarios_roles = models.JSONField(
        default=list, help_text="Ej. ['COORDINADOR','BIENESTAR_ACADEMICO'] -- rol crudo o rol_efectivo destino")
    plantilla = models.ForeignKey('PlantillaCorreo', on_delete=models.PROTECT, related_name='reglas')
    activa = models.BooleanField(default=True)
    prioridad = models.IntegerField(default=5)
    cooldown_horas = models.PositiveIntegerField(default=24, help_text='No re-disparar la misma regla+mismo objeto antes de N horas')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reglas_creadas')

    class Meta:
        db_table = 'decano_reglas_intervencion'
        indexes = [models.Index(fields=['metrica', 'activa'])]

    def __str__(self):
        return f'{self.nombre} ({self.get_metrica_display()} {self.get_operador_display()} {self.umbral})'


class PlantillaCorreo(models.Model):
    id_plantilla = models.AutoField(primary_key=True)
    codigo = models.SlugField(max_length=60, unique=True)
    asunto = models.CharField(max_length=200, help_text='Admite variables {{...}}')
    cuerpo_html = models.TextField(help_text='Admite {{estudiante.nombre}}, {{materia}}, {{porcentaje_fallas}}, etc.')
    variables_disponibles = models.JSONField(default=list, help_text='Nombres de variable válidos, usado para validar en el panel')
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'decano_plantillas_correo'

    def __str__(self):
        return self.codigo


class LogIntervencion(models.Model):
    """Bitácora de correos disparados por ReglaIntervencion -- mismo
    espíritu que integracion_sisca.IntegracionLog (ya audita eventos de
    sincronización con SISCA)."""
    ESTADO_CHOICES = (
        ('ENCOLADO', 'Encolado'), ('ENVIADO', 'Enviado'),
        ('FALLIDO', 'Fallido'), ('REINTENTANDO', 'Reintentando'),
    )
    id_log = models.AutoField(primary_key=True)
    regla = models.ForeignKey(ReglaIntervencion, on_delete=models.PROTECT, related_name='disparos')
    objeto_tipo = models.CharField(max_length=40, help_text="Ej. 'Docente', 'Estudiante', 'Salon', 'Evento', 'Jornada'")
    objeto_id = models.CharField(max_length=40)
    valor_metrica = models.DecimalField(max_digits=6, decimal_places=2)
    destinatarios = models.JSONField(default=list, help_text='Correos efectivamente resueltos al momento del disparo')
    asunto_renderizado = models.CharField(max_length=200)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='ENCOLADO')
    intentos = models.PositiveSmallIntegerField(default=0)
    error_detalle = models.TextField(blank=True)
    fecha_disparo = models.DateTimeField(auto_now_add=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'decano_log_intervenciones'
        indexes = [models.Index(fields=['regla', 'objeto_tipo', 'objeto_id']), models.Index(fields=['estado'])]
        ordering = ['-fecha_disparo']

    def __str__(self):
        return f'{self.regla.nombre} -> {self.objeto_tipo}#{self.objeto_id} [{self.estado}]'
