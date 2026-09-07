"""SIIHAPI · apps/mentoria (Sprint 4, 2026-09-06). El rol MENTORIAS ya
existe (Fase 3, hoy en permisos.ROLES_SOLO_CONSULTA). Igual que
apps.bienestar, este app agrega escritura propia sin tocar ese bloqueo
existente (ver permisos.mentoria_required, ya definido desde Sprint 2)."""
from django.conf import settings
from django.db import models


class AsignacionMentoria(models.Model):
    ESTADO_CHOICES = (('ACTIVA', 'Activa'), ('FINALIZADA', 'Finalizada'), ('CANCELADA', 'Cancelada'))
    id_asignacion = models.AutoField(primary_key=True)
    estudiante = models.ForeignKey('matriculas.Estudiante', on_delete=models.CASCADE, related_name='mentorias')
    mentor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='mentorias_asignadas')
    caso_bienestar_origen = models.ForeignKey('bienestar.CasoBienestar', null=True, blank=True, on_delete=models.SET_NULL, related_name='mentorias')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='ACTIVA')
    asignado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='mentorias_creadas')

    class Meta:
        db_table = 'mentoria_asignaciones'
        unique_together = [('estudiante', 'mentor', 'fecha_inicio')]
        indexes = [models.Index(fields=['estado'])]

    def __str__(self):
        return f'{self.estudiante_id} <- {self.mentor_id} [{self.estado}]'


class SesionMentoria(models.Model):
    """Agendada e integrada con horarios SOLO para verificar que no cruce
    con una clase del estudiante/mentor -- NUNCA se guarda como Horario
    propio (no ensucia el Motor IA con sesiones 1:1)."""
    ESTADO_CHOICES = (('PROGRAMADA', 'Programada'), ('REALIZADA', 'Realizada'), ('INASISTENCIA', 'Inasistencia'), ('CANCELADA', 'Cancelada'))
    id_sesion = models.AutoField(primary_key=True)
    asignacion = models.ForeignKey(AsignacionMentoria, on_delete=models.CASCADE, related_name='sesiones')
    fecha_hora_inicio = models.DateTimeField()
    fecha_hora_fin = models.DateTimeField()
    modalidad = models.CharField(max_length=12, choices=(('PRESENCIAL', 'Presencial'), ('VIRTUAL', 'Virtual')), default='PRESENCIAL')
    salon = models.ForeignKey('infraestructura.Salon', null=True, blank=True, on_delete=models.SET_NULL, related_name='sesiones_mentoria')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PROGRAMADA')

    class Meta:
        db_table = 'mentoria_sesiones'
        indexes = [models.Index(fields=['fecha_hora_inicio'])]

    def __str__(self):
        return f'Sesion #{self.id_sesion} · {self.asignacion_id} · {self.fecha_hora_inicio:%Y-%m-%d %H:%M}'


class BitacoraMentoria(models.Model):
    id_bitacora = models.AutoField(primary_key=True)
    sesion = models.OneToOneField(SesionMentoria, on_delete=models.CASCADE, related_name='bitacora')
    resumen = models.TextField()
    progreso_academico = models.CharField(max_length=10, choices=(('MEJORA', 'Mejora'), ('IGUAL', 'Igual'), ('EMPEORA', 'Empeora')), null=True, blank=True)
    progreso_personal_notas = models.TextField(blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mentoria_bitacoras'

    def __str__(self):
        return f'Bitacora sesion #{self.sesion_id}'
