"""SIIHAPI - URL routing principal."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView,
)

from . import frontend_views as fv


urlpatterns = [
    # ── Publicas ──
    path('',           fv.landing,     name='landing'),
    path('login/',     fv.login_view,  name='login'),
    path('logout/',    fv.logout_view, name='logout'),

    # ── Dashboard raiz ──
    path('dashboard/', fv.dashboard,   name='dashboard'),

    # ── Modulos ADMIN/COORDINADOR ──
    path('dashboard/sedes/',        fv.sedes_view,        name='sedes'),
    path('dashboard/programas/',    fv.programas_view,    name='programas'),
    path('dashboard/docentes/',     fv.docentes_view,     name='docentes'),
    path('dashboard/estudiantes/',  fv.estudiantes_view,  name='estudiantes'),
    path('dashboard/horarios/',     fv.horarios_view,     name='horarios'),
    path('dashboard/horarios/aprobar/',           fv.aprobar_horarios,    name='aprobar_horarios'),
    path('dashboard/horarios/<int:id_horario>/detalle/',  fv.horario_detalle,        name='horario_detalle'),
    path('dashboard/horarios/<int:id_horario>/pdf/',      fv.horario_exportar_pdf,   name='horario_exportar_pdf'),
    path('dashboard/horarios/pdf-completo/',              fv.horarios_exportar_pdf_completo, name='horarios_exportar_pdf_completo'),
    path('dashboard/horarios/excel-completo/',            fv.horarios_exportar_excel_completo, name='horarios_exportar_excel_completo'),
    path('dashboard/horarios/gestionar/',         fv.horarios_gestionar,  name='horarios_gestionar'),
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

    # ── Modulos ESTUDIANTE ──
    path('estudiante/mi-horario/',  fv.estudiante_mi_horario,  name='estudiante_mi_horario'),
    path('estudiante/mis-materias/',fv.estudiante_mis_materias,name='estudiante_mis_materias'),
    path('estudiante/asistencia/',  fv.estudiante_asistencia,  name='estudiante_asistencia'),
    path('estudiante/notas/',       fv.estudiante_notas,       name='estudiante_notas'),

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
