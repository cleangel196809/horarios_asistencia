"""SIIHAPI - URL routing principal."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView,
)

from . import frontend_views as fv
from . import decano_views as dv
from . import mentoria_views as mv


urlpatterns = [
    # ── Publicas ──
    path('',           fv.landing,     name='landing'),
    path('login/',     fv.login_view,  name='login'),
    path('logout/',    fv.logout_view, name='logout'),

    # ── Dashboard raiz ──
    path('dashboard/', fv.dashboard,   name='dashboard'),

    # ── Ciclos de formacion (periodos) ──
    path('periodos/crear/', fv.crear_periodo, name='crear_periodo'),
    path('periodos/seleccionar/', fv.seleccionar_periodo, name='seleccionar_periodo'),

    # ── Modulos ADMIN/COORDINADOR ──
    path('dashboard/sedes/',        fv.sedes_view,        name='sedes'),
    path('dashboard/programas/',    fv.programas_view,    name='programas'),
    path('dashboard/programas/<int:id_programa>/', fv.programa_ciclos_view, name='programa_ciclos'),
    path('dashboard/programas/<int:id_programa>/ciclo/<int:id_periodo>/', fv.programa_ciclo_materias_view, name='programa_ciclo_materias'),
    path('dashboard/programas/<int:id_programa>/ciclo/<int:id_periodo>/materia/<int:id_materia>/', fv.materia_periodo_estudiantes_view, name='materia_periodo_estudiantes'),
    path('dashboard/docentes/',     fv.docentes_view,     name='docentes'),
    path('dashboard/docentes/buscar/', fv.docentes_autocomplete, name='docentes_autocomplete'),
    path('dashboard/estudiantes/',  fv.estudiantes_view,  name='estudiantes'),
    path('dashboard/horarios/',     fv.horarios_view,     name='horarios'),
    path('dashboard/horarios/aprobar/',           fv.aprobar_horarios,    name='aprobar_horarios'),
    path('dashboard/horarios/<int:id_horario>/detalle/',  fv.horario_detalle,        name='horario_detalle'),
    path('dashboard/horarios/<int:id_horario>/pdf/',      fv.horario_exportar_pdf,   name='horario_exportar_pdf'),
    path('dashboard/horarios/pdf-completo/',              fv.horarios_exportar_pdf_completo, name='horarios_exportar_pdf_completo'),
    path('dashboard/horarios/excel-completo/',            fv.horarios_exportar_excel_completo, name='horarios_exportar_excel_completo'),
    path('dashboard/horarios/gestionar/',         fv.horarios_gestionar,  name='horarios_gestionar'),
    path('dashboard/horarios/solicitudes-reprogramacion/', fv.solicitudes_reprogramacion_gestionar, name='solicitudes_reprogramacion_gestionar'),
    path('dashboard/horarios/solicitudes-reprogramacion/<int:id_solicitud>/resolver/', fv.solicitud_reprogramacion_resolver, name='solicitud_reprogramacion_resolver'),
    path('dashboard/asistencias/justificaciones/', fv.justificaciones_gestionar, name='justificaciones_gestionar'),
    path('dashboard/asistencias/justificaciones/<int:id_justificacion>/resolver/', fv.justificacion_resolver, name='justificacion_resolver'),
    path('dashboard/bienestar/', fv.bienestar_dashboard, name='bienestar_dashboard'),
    path('dashboard/bienestar/alertas/<int:id_alerta>/estado/', fv.alerta_riesgo_actualizar_estado, name='alerta_riesgo_actualizar_estado'),
    # ── Eventos (Sprint 3, 2026-09-06) ──
    path('dashboard/eventos/',                          fv.calendario_eventos,       name='calendario_eventos'),
    path('dashboard/eventos/proponer/',                 fv.docente_proponer_evento,  name='docente_proponer_evento'),
    path('dashboard/eventos/gestionar/',                fv.eventos_gestionar,        name='eventos_gestionar'),
    path('dashboard/eventos/<int:id_evento>/resolver/',       fv.evento_resolver,          name='evento_resolver'),
    path('dashboard/eventos/<int:id_evento>/',                fv.evento_detalle,           name='evento_detalle'),
    path('dashboard/eventos/<int:id_evento>/inscribirme/',    fv.evento_inscribirse,       name='evento_inscribirse'),
    path('dashboard/eventos/<int:id_evento>/escanear/',       fv.evento_escanear_qr,       name='evento_escanear_qr'),
    path('dashboard/eventos/<int:id_evento>/certificados/',   fv.evento_certificados,      name='evento_certificados'),
    path('dashboard/mis-inscripciones-eventos/',              fv.mis_inscripciones_eventos, name='mis_inscripciones_eventos'),
    path('dashboard/inscripciones/<int:id_inscripcion>/qr.png', fv.inscripcion_qr_imagen,  name='inscripcion_qr_imagen'),
    path('dashboard/certificados/<int:id_certificado>/descargar/', fv.certificado_descargar, name='certificado_descargar'),
    path('dashboard/revision/',                   fv.revision_propuesta,  name='revision_propuesta'),
    path('dashboard/revision/aprobar-todos/',     fv.revision_aprobar_todos, name='revision_aprobar_todos'),
    path('dashboard/revision/eliminar-propuesta/', fv.revision_eliminar_propuesta, name='revision_eliminar_propuesta'),
    path('dashboard/publicacion/',                fv.centro_publicacion,  name='centro_publicacion'),
    path('dashboard/horarios/<int:id_horario>/actualizar/', fv.horario_actualizar, name='horario_actualizar'),
    path('dashboard/horarios/<int:id_horario>/eliminar/',   fv.horario_eliminar,   name='horario_eliminar'),

    # ── Motor IA ──
    path('dashboard/motor-ia/',           fv.motor_ia_view,         name='motor_ia'),
    path('dashboard/motor-ia/ejecutar/',  fv.motor_ia_ejecutar,     name='motor_ia_ejecutar'),
    path('dashboard/motor-ia/analizar/',  fv.motor_ia_analizar,     name='motor_ia_analizar'),
    path('dashboard/motor-ia/grupos/', fv.motor_ia_grupos, name='motor_ia_grupos'),
    path('dashboard/motor-ia/borrador-excel/', fv.motor_ia_descargar_borrador, name='motor_ia_descargar_borrador'),
    path('dashboard/motor-ia/proponer-edicion/', fv.motor_ia_proponer_edicion, name='motor_ia_proponer_edicion'),
    path('dashboard/motor-ia/aplicar-edicion/',  fv.motor_ia_aplicar_edicion,  name='motor_ia_aplicar_edicion'),
    path('dashboard/motor-ia/metricas/',  fv.motor_ia_metricas,     name='motor_ia_metricas'),
    path('dashboard/motor-ia/chat/',      fv.motor_ia_chat_view,    name='motor_ia_chat'),
    path('dashboard/motor-ia/chat/enviar/', fv.motor_ia_chat_enviar, name='motor_ia_chat_enviar'),

    # ── SISCA ──
    path('dashboard/integracion-sisca/',         fv.integracion_sisca, name='integracion_sisca'),
    path('dashboard/integracion-sisca/publicar/', fv.sisca_publicar,    name='sisca_publicar'),
    path('dashboard/integracion-sisca/publicar-ui/', fv.sisca_publicar_ui, name='sisca_publicar_ui'),
    path('dashboard/integracion-sisca/estado/',   fv.sisca_estado,      name='sisca_estado'),
    path('dashboard/integracion-sisca/logs/',     fv.sisca_logs,        name='sisca_logs'),

    # ── Carga masiva (RF-15, RF-20, RF-23, RF-25, RF-30) ──
    path('dashboard/carga-masiva/',                   fv.carga_masiva_view,  name='carga_masiva'),
    path('dashboard/generar-horarios/', fv.generar_horarios_desde_matriculas, name='generar_horarios_desde_matriculas'),
    path('dashboard/carga-masiva/plantilla/<str:tipo>/', fv.descargar_plantilla, name='descargar_plantilla'),

    # ── Base de datos (CRUD via Django Admin, backup/restore) y usuarios ──
    # ── Modulo del Decano (Sprint 4, 2026-09-06) ──
    path('dashboard/decano/',                              dv.decano_panel,                        name='decano_panel'),
    path('dashboard/decano/jornadas/',                       dv.jornadas_lista,                      name='jornadas_lista'),
    path('dashboard/decano/jornadas/<int:id_jornada>/toggle/', dv.jornada_toggle,                     name='jornada_toggle'),
    path('dashboard/decano/jornadas/<int:id_jornada>/editar/', dv.jornada_editar,                     name='jornada_editar'),
    path('dashboard/decano/matrices/',                      dv.matriz_planeacion_lista,             name='matriz_planeacion_lista'),
    path('dashboard/decano/matrices/crear/',                dv.matriz_planeacion_crear,             name='matriz_planeacion_crear'),
    path('dashboard/decano/matrices/<int:id_matriz>/',      dv.matriz_planeacion_detalle,           name='matriz_planeacion_detalle'),
    path('dashboard/decano/matrices/<int:id_matriz>/vincular-ia/',      dv.matriz_planeacion_vincular_ia,      name='matriz_planeacion_vincular_ia'),
    path('dashboard/decano/matrices/<int:id_matriz>/enviar-revision/',  dv.matriz_planeacion_enviar_revision,  name='matriz_planeacion_enviar_revision'),
    path('dashboard/decano/matrices/<int:id_matriz>/aprobar/',          dv.matriz_planeacion_aprobar,          name='matriz_planeacion_aprobar'),
    path('dashboard/decano/matrices/<int:id_matriz>/publicar/',         dv.matriz_planeacion_publicar,         name='matriz_planeacion_publicar'),
    path('dashboard/decano/matrices/<int:id_matriz>/continuar/',        dv.matriz_planeacion_continuar,        name='matriz_planeacion_continuar'),
    path('dashboard/decano/matrices/<int:id_matriz>/grupos/',               dv.grupos_planeacion_lista,            name='grupos_planeacion_lista'),
    path('dashboard/decano/matrices/<int:id_matriz>/grupos/crear/',         dv.grupo_planeacion_crear,             name='grupo_planeacion_crear'),
    path('dashboard/decano/grupos/<int:id_grupo>/toggle-activo/',           dv.grupo_planeacion_toggle_activo,     name='grupo_planeacion_toggle_activo'),
    path('dashboard/decano/grupos/<int:id_grupo>/asignar-docente/',         dv.grupo_planeacion_asignar_docente,   name='grupo_planeacion_asignar_docente'),

    path('dashboard/decano/reglas/',                        dv.reglas_lista,                        name='reglas_lista'),
    path('dashboard/decano/reglas/crear/',                  dv.regla_crear,                         name='regla_crear'),
    path('dashboard/decano/reglas/<int:id_regla>/editar/',  dv.regla_editar,                        name='regla_editar'),
    path('dashboard/decano/reglas/<int:id_regla>/toggle/',  dv.regla_activar_toggle,                name='regla_activar_toggle'),
    path('dashboard/decano/reglas/<int:id_regla>/disparar/', dv.regla_disparar_ahora,               name='regla_disparar_ahora'),
    path('dashboard/decano/plantillas/',                    dv.plantillas_lista,                    name='plantillas_lista'),
    path('dashboard/decano/plantillas/crear/',              dv.plantilla_crear,                     name='plantilla_crear'),
    path('dashboard/decano/plantillas/<int:id_plantilla>/editar/', dv.plantilla_editar,             name='plantilla_editar'),
    path('dashboard/decano/logs/',                          dv.logs_intervencion,                   name='logs_intervencion'),
    path('dashboard/decano/logs/<int:id_log>/reintentar/',  dv.log_intervencion_reintentar,         name='log_intervencion_reintentar'),

    path('dashboard/decano/reportes/ocupacion-salones/',           dv.reporte_ocupacion_salones,           name='reporte_ocupacion_salones'),
    path('dashboard/decano/reportes/heatmap-inasistencias/',       dv.reporte_heatmap_inasistencias,       name='reporte_heatmap_inasistencias'),
    path('dashboard/decano/reportes/roi-eventos/',                 dv.reporte_roi_eventos,                 name='reporte_roi_eventos'),
    path('dashboard/decano/reportes/riesgo-desercion/',             dv.reporte_riesgo_desercion,            name='reporte_riesgo_desercion'),
    path('dashboard/decano/reportes/cumplimiento-docente/',         dv.reporte_cumplimiento_docente,        name='reporte_cumplimiento_docente'),
    path('dashboard/decano/reportes/conflictos-horario/',           dv.reporte_conflictos_horario,          name='reporte_conflictos_horario'),
    path('dashboard/decano/reportes/utilizacion-infraestructura/',  dv.reporte_utilizacion_infraestructura, name='reporte_utilizacion_infraestructura'),

    # ── Mentoria (Sprint 4, 2026-09-06) ──
    path('dashboard/mentoria/',                             mv.mentoria_dashboard,                  name='mentoria_dashboard'),
    path('dashboard/mentoria/asignar/',                     mv.asignacion_mentoria_crear,           name='asignacion_mentoria_crear'),
    path('dashboard/mentoria/<int:id_asignacion>/',         mv.asignacion_mentoria_detalle,         name='asignacion_mentoria_detalle'),
    path('dashboard/mentoria/<int:id_asignacion>/sesiones/crear/', mv.sesion_mentoria_crear,        name='sesion_mentoria_crear'),
    path('dashboard/mentoria/sesiones/<int:id_sesion>/estado/',    mv.sesion_mentoria_actualizar_estado, name='sesion_mentoria_actualizar_estado'),
    path('dashboard/mentoria/sesiones/<int:id_sesion>/bitacora/',  mv.bitacora_mentoria_crear,      name='bitacora_mentoria_crear'),

    path('dashboard/base-datos/',                          fv.base_datos_view,        name='base_datos'),
    path('dashboard/base-datos/backup/',                   fv.bd_backup_ejecutar,     name='bd_backup_ejecutar'),
    path('dashboard/base-datos/backups/<str:filename>/descargar/', fv.bd_backup_descargar, name='bd_backup_descargar'),
    path('dashboard/base-datos/backups/<str:filename>/eliminar/',  fv.bd_backup_eliminar,  name='bd_backup_eliminar'),
    path('dashboard/base-datos/restaurar/',                fv.bd_restore_view,        name='bd_restore'),
    path('dashboard/usuarios/',                            fv.usuarios_admin_view,    name='usuarios_admin'),
    path('dashboard/usuarios/crear/',                      fv.usuario_crear_view,     name='usuario_crear'),
    path('dashboard/usuarios/<int:id_usuario>/editar/',    fv.usuario_editar_view,    name='usuario_editar'),
    path('dashboard/usuarios/<int:id_usuario>/inactivar/', fv.usuario_inactivar_view, name='usuario_inactivar'),
    path('dashboard/usuarios/<int:id_usuario>/reactivar/', fv.usuario_reactivar_view, name='usuario_reactivar'),

    # ── Reportes ADMIN ──
    path('dashboard/ejecutivo/',  fv.dashboard_ejecutivo, name='dashboard_ejecutivo'),
    path('dashboard/auditoria/',                 fv.auditoria_view,            name='auditoria'),
    path('dashboard/auditoria/exportar/<str:formato>/', fv.exportar_auditoria_view, name='exportar_auditoria'),
    path('dashboard/auditoria/pdf-categorias/',  fv.auditoria_pdf_categorias,  name='auditoria_pdf_categorias'),
    path('dashboard/reportes/',                  fv.reportes_categoria_view,   name='reportes_categoria'),

    # ── Modulos DOCENTE ──
    path('docente/mi-horario/',     fv.docente_mi_horario,      name='docente_mi_horario'),
    path('docente/mis-materias/',   fv.docente_mis_materias,    name='docente_mis_materias'),
    path('docente/disponibilidad/', fv.docente_disponibilidad,  name='docente_disponibilidad'),
    path('docente/estudiantes/',    fv.docente_mis_estudiantes, name='docente_mis_estudiantes'),
    path('docente/asistencia/',     fv.docente_asistencia,      name='docente_asistencia'),
    path('docente/marcar-asistencia/', fv.docente_marcar_asistencia, name='docente_marcar_asistencia'),
    path('docente/reportes/',       fv.docente_reportes,        name='docente_reportes'),
    path('mis-justificaciones/',    fv.mis_justificaciones,     name='mis_justificaciones'),
    path('docente/solicitudes-reprogramacion/', fv.docente_solicitudes_reprogramacion, name='docente_solicitudes_reprogramacion'),

    # ── Modulos ESTUDIANTE ──
    path('estudiante/mi-horario/',  fv.estudiante_mi_horario,  name='estudiante_mi_horario'),
    path('estudiante/mis-materias/',fv.estudiante_mis_materias,name='estudiante_mis_materias'),
    path('estudiante/asistencia/',  fv.estudiante_asistencia,  name='estudiante_asistencia'),
    path('estudiante/notas/',       fv.estudiante_notas,       name='estudiante_notas'),
    path('estudiante/reportes/',    fv.estudiante_reportes,    name='estudiante_reportes'),

    # ── Django admin ──
    path('admin/', admin.site.urls),

    # ── API REST ──
    path('api/auth/',            include('apps.autenticacion.urls')),
    path('api/academico/',       include('apps.academico.urls')),
    path('api/infraestructura/', include('apps.infraestructura.urls')),
    path('api/personal/',        include('apps.personal.urls')),
    path('api/matriculas/',      include('apps.matriculas.urls')),
    path('api/horarios/',        include('apps.horarios.urls')),
    path('api/reportes/',        include('apps.reportes.urls')),
    path('api/sisca/',           include('apps.integracion_sisca.urls')),

    # ── Docs API ──
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/',   SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
      path('api/redoc/',  SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
