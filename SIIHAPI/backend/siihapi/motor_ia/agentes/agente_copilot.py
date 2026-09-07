"""
SIIHAPI · Agente Microsoft Copilot (Fase 3, 2026-09-04).

Nota importante: Microsoft Copilot (Word/Outlook/Teams) no expone una API
publica de "chat completion" que una aplicacion externa pueda invocar con
una simple API key -- a diferencia de Gemini, OpenAI o Anthropic. El motor
real detras de Copilot es Azure OpenAI Service (los mismos modelos GPT-4o
alojados en el tenant de Azure/Microsoft 365 de la institucion), asi que
este agente se conecta ahi: es la forma honesta y funcional de tener
"Copilot" como una opcion mas del Motor IA.

Requiere que el administrador de TI del Politecnico genere en el portal de
Azure un recurso de Azure OpenAI y configure en backend/.env:
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT      (ej: https://<recurso>.openai.azure.com/)
    AZURE_OPENAI_DEPLOYMENT    (nombre del despliegue, ej: gpt-4o-mini)
    AZURE_OPENAI_API_VERSION   (opcional, ej: 2024-08-01-preview)
Tambien acepta los alias COPILOT_API_KEY / COPILOT_ENDPOINT / etc. si se
prefiere nombrarlas asi.
"""
from ..llm import (
    _get_azure_config, _copilot_configurado,
    analizar_horario_con_ia, chat_llm, extraer_horarios_con_ia,
)
from .base import AgenteIA


class AgenteCopilot(AgenteIA):
    codigo = 'COPILOT'
    nombre_visible = 'Microsoft Copilot'
    descripcion = 'Vía Azure OpenAI Service (AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT).'
    icono = '🔷'

    def disponible(self) -> bool:
        if not _copilot_configurado():
            return False
        try:
            import openai  # noqa (el SDK 'openai' incluye el cliente AzureOpenAI)
            return True
        except ImportError:
            return False

    def analizar_horario(self, datos: dict):
        return analizar_horario_con_ia(datos, forzar_proveedor='COPILOT')

    def chat(self, mensaje: str, historial=None, contexto_archivo: str = '') -> dict:
        return chat_llm(mensaje, historial=historial, contexto_archivo=contexto_archivo,
                         forzar_proveedor='COPILOT')

    def extraer_horarios(self, texto: str, periodo: str = '2026-2', catalogo=None):
        return extraer_horarios_con_ia(texto, periodo=periodo, catalogo=catalogo,
                                        forzar_proveedor='COPILOT')
