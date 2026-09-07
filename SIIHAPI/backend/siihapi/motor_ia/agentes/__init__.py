"""
SIIHAPI · Registro de Agentes de IA del Motor IA (Fase 3, 2026-09-04).

Cada IA que este modulo puede usar -- Google Gemini, OpenAI, Anthropic
Claude, Microsoft Copilot (via Azure OpenAI) y el analizador heuristico
local -- tiene aqui su propio "agente" (ver base.AgenteIA), en vez de
condicionales sueltos repetidos por cada vista. Los agentes son wrappers
delgados sobre motor_ia/llm.py: no cambian su comportamiento, solo dan una
fachada uniforme para listarlos, elegirlos y saber cuales estan realmente
disponibles (con API key configurada).

Uso tipico:
    from siihapi.motor_ia.agentes import obtener_agente, agentes_disponibles

    agente = obtener_agente('COPILOT')   # o None -> el mejor disponible
    resultado = agente.analizar_horario(datos)

    for a in agentes_disponibles():
        print(a.codigo, a.nombre_visible)
"""
from .base import AgenteIA
from .agente_gemini import AgenteGemini
from .agente_openai import AgenteOpenAI
from .agente_anthropic import AgenteAnthropic
from .agente_copilot import AgenteCopilot
from .agente_heuristico import AgenteHeuristico

# Orden = prioridad de auto-seleccion (igual que motor_ia.llm.proveedor_disponible,
# heuristico siempre al final como respaldo garantizado).
REGISTRO = [
    AgenteGemini(),
    AgenteOpenAI(),
    AgenteAnthropic(),
    AgenteCopilot(),
    AgenteHeuristico(),
]

_POR_CODIGO = {a.codigo: a for a in REGISTRO}


def todos_los_agentes():
    """Lista completa de agentes conocidos por el modulo (esten o no
    configurados en este momento)."""
    return list(REGISTRO)


def agentes_disponibles():
    """Solo los agentes que tienen sus credenciales/dependencias listas
    ahora mismo."""
    return [a for a in REGISTRO if a.disponible()]


def obtener_agente(codigo=None):
    """Devuelve el agente pedido por su codigo ('GEMINI'|'OPENAI'|
    'ANTHROPIC'|'COPILOT'|'HEURISTIC'). Sin codigo (o uno desconocido),
    devuelve el primer agente disponible segun la prioridad del registro
    (y por ultimo, siempre, el heuristico)."""
    if codigo and codigo in _POR_CODIGO:
        return _POR_CODIGO[codigo]
    disponibles = agentes_disponibles()
    return disponibles[0] if disponibles else _POR_CODIGO['HEURISTIC']


__all__ = [
    'AgenteIA', 'AgenteGemini', 'AgenteOpenAI', 'AgenteAnthropic',
    'AgenteCopilot', 'AgenteHeuristico',
    'REGISTRO', 'todos_los_agentes', 'agentes_disponibles', 'obtener_agente',
]
