"""
SIIHAPI · apps/evaluacion_docente — vista HTML de notas por voz.

La página sólo renderiza; todo lo demás pasa por la API REST de
`views.py`. La transcripción ocurre EN EL NAVEGADOR (Web Speech API) y el
audio sólo sale del equipo cuando el navegador no la soporta y se usa el
respaldo del servidor.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.contrib import messages

from .views import _es_staff, _mi_docente


@login_required
def notas_por_voz(request):
    docente = _mi_docente(request.user)
    if not docente and not _es_staff(request.user):
        messages.error(request, 'Esta sección es para docentes.')
        return redirect('dashboard')

    from apps.academico.models import Materia
    materias = Materia.objects.none()
    if docente:
        # Materias con un syllabus o una rúbrica suya; si no tiene
        # ninguna todavía, se ofrece el catálogo activo para no dejar el
        # selector vacío en el primer uso.
        from .models import Rubrica, Syllabus
        ids = set(Syllabus.objects.filter(docente=docente).values_list('materia_id', flat=True))
        ids |= set(Rubrica.objects.filter(docente=docente).values_list('materia_id', flat=True))
        materias = Materia.objects.filter(id_materia__in=ids) if ids else Materia.objects.filter(activa=True)[:200]
    else:
        materias = Materia.objects.filter(activa=True)[:200]

    from .models import Calificacion
    borradores = (Calificacion.objects
                  .filter(estado='BORRADOR', **({'docente': docente} if docente else {}))
                  .select_related('estudiante__usuario', 'materia')[:50])

    return render(request, 'dashboard/evaluacion_notas_voz.html', {
        'materias': materias,
        'borradores': borradores,
    })
