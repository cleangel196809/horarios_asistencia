"""Validadores de política de contraseñas (RNF-12)."""
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class PoliticaSIIHAPIValidator:
    """
    RNF-12 · Política de Contraseñas
    --------------------------------
    Las contraseñas deben tener:
    · Al menos 8 caracteres
    · Al menos una letra mayúscula
    · Al menos un número
    · Al menos un carácter especial
    """

    def validate(self, password, user=None):
        errores = []
        if len(password) < 8:
            errores.append(_('Debe tener al menos 8 caracteres.'))
        if not re.search(r'[A-Z]', password):
            errores.append(_('Debe contener al menos una letra mayúscula.'))
        if not re.search(r'[0-9]', password):
            errores.append(_('Debe contener al menos un número.'))
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]]', password):
            errores.append(_('Debe contener al menos un carácter especial.'))
        if errores:
            raise ValidationError(errores)

    def get_help_text(self):
        return _(
            'Tu contraseña debe tener al menos 8 caracteres, '
            'una mayúscula, un número y un carácter especial.'
        )
