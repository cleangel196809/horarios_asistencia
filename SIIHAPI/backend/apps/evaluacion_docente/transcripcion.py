"""
SIIHAPI · apps/evaluacion_docente — transcripción de audio (respaldo).

El camino principal de "notas por voz" es la **Web Speech API del
navegador**: transcribe en vivo, no sube audio a ningún lado y no cuesta
CPU del servidor. Este módulo es el RESPALDO para los navegadores que no
la soportan (Firefox, algunos WebView de Android).

`faster-whisper` corre local, en CPU, sin claves de API — coherente con el
resto del proyecto, que ya funciona con GEMINI/OPENAI/ANTHROPIC sin
configurar. Es una dependencia OPCIONAL: si no está instalada, el endpoint
responde 503 con un mensaje claro y el flujo por Web Speech API sigue
intacto. Por eso no está en `requirements.txt` como obligatoria.

Instalación (opcional, donde se quiera el respaldo):
    pip install faster-whisper

El modelo se carga una sola vez por proceso: cargarlo en cada petición
tardaría más que la transcripción misma.
"""
import logging
import os
import tempfile
import threading

from django.conf import settings

log = logging.getLogger(__name__)

_modelo = None
_lock = threading.Lock()

# Formatos que aceptamos. Es una lista blanca a propósito: el archivo lo
# termina abriendo ffmpeg, así que no conviene dejar entrar cualquier cosa.
EXTENSIONES_PERMITIDAS = {'.webm', '.ogg', '.oga', '.wav', '.m4a', '.mp3', '.mp4'}
CONTENT_TYPES_PERMITIDOS = {
    'audio/webm', 'audio/ogg', 'audio/wav', 'audio/x-wav', 'audio/wave',
    'audio/mpeg', 'audio/mp4', 'audio/m4a', 'audio/x-m4a', 'video/webm',
}


class TranscripcionNoDisponible(Exception):
    """faster-whisper no está instalado o el modelo no se pudo cargar."""


def _get_modelo():
    """Carga perezosa y única del modelo (thread-safe)."""
    global _modelo
    if _modelo is not None:
        return _modelo
    with _lock:
        if _modelo is not None:
            return _modelo
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscripcionNoDisponible(
                'faster-whisper no está instalado en este servidor. '
                'Usa la transcripción del navegador (Web Speech API) o instala '
                'la dependencia opcional: pip install faster-whisper'
            ) from e
        nombre = getattr(settings, 'EVALUACION_WHISPER_MODELO', 'base')
        device = getattr(settings, 'EVALUACION_WHISPER_DEVICE', 'cpu')
        log.info('[evaluacion_docente] cargando faster-whisper "%s" en %s', nombre, device)
        try:
            _modelo = WhisperModel(nombre, device=device, compute_type='int8')
        except Exception as e:  # noqa: BLE001 — descarga del modelo, device inválido, etc.
            raise TranscripcionNoDisponible(
                f'No se pudo cargar el modelo de voz "{nombre}": {e}') from e
        return _modelo


def validar_audio(archivo) -> str | None:
    """Revisa tamaño, extensión y content-type. Devuelve el mensaje de
    error, o None si el archivo es aceptable."""
    if archivo is None:
        return 'No se recibió ningún archivo de audio (campo "audio").'

    maximo = getattr(settings, 'EVALUACION_AUDIO_MAX_BYTES', 10 * 1024 * 1024)
    if archivo.size > maximo:
        return f'El audio supera el máximo permitido ({maximo // (1024 * 1024)} MB).'
    if archivo.size == 0:
        return 'El archivo de audio está vacío.'

    # El nombre lo manda el cliente: sólo se usa la extensión, nunca para
    # construir una ruta en disco (el temporal lo nombra el servidor).
    nombre = (getattr(archivo, 'name', '') or '').lower()
    extension = os.path.splitext(nombre)[1]
    if extension and extension not in EXTENSIONES_PERMITIDAS:
        return f'Formato de audio no admitido: {extension}'

    content_type = (getattr(archivo, 'content_type', '') or '').split(';')[0].strip().lower()
    if content_type and content_type not in CONTENT_TYPES_PERMITIDOS:
        return f'Tipo de contenido no admitido: {content_type}'
    if not extension and not content_type:
        return 'No se pudo determinar el formato del audio.'
    return None


def transcribir(archivo, idioma: str = 'es') -> dict:
    """Transcribe un archivo de audio subido.

    Devuelve `{'texto', 'idioma', 'confianza', 'duracion_segundos'}`.
    Lanza `TranscripcionNoDisponible` si el respaldo no está disponible.
    """
    modelo = _get_modelo()

    extension = os.path.splitext((getattr(archivo, 'name', '') or '').lower())[1] or '.webm'
    tmp_path = None
    try:
        # delete=False + unlink explícito en finally: en Windows no se
        # puede reabrir un NamedTemporaryFile todavía abierto, y
        # faster-whisper abre el archivo por ruta.
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
            for chunk in archivo.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        segmentos, info = modelo.transcribe(
            tmp_path,
            language=idioma or None,
            beam_size=5,
            vad_filter=True,  # descarta silencios: notas dictadas suelen tener pausas largas
        )
        partes, probs = [], []
        for seg in segmentos:
            partes.append(seg.text)
            # avg_logprob es logarítmico y negativo; se normaliza a 0..1
            # sólo para dar una señal de "qué tan segura" fue la
            # transcripción en la UI. No es una probabilidad real.
            lp = getattr(seg, 'avg_logprob', None)
            if lp is not None:
                probs.append(max(0.0, min(1.0, 1.0 + lp)))

        texto = ' '.join(p.strip() for p in partes).strip()
        return {
            'texto': texto,
            'idioma': getattr(info, 'language', idioma),
            'confianza': round(sum(probs) / len(probs), 3) if probs else None,
            'duracion_segundos': round(getattr(info, 'duration', 0.0) or 0.0, 2),
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                log.warning('[evaluacion_docente] no se pudo borrar el temporal %s', tmp_path)
