"""Helpers para la integracion SISCA."""
from apps.integracion_sisca.cliente import get_cliente


def _cliente_disponible():
    cliente = get_cliente()
    return cliente.ping()
