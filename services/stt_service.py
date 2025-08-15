import assemblyai as aai
import logging

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self, api_key):
        aai.settings.api_key = api_key

    def transcribe(self, audio_bytes):
        try:
            transcriber = aai.Transcriber()
            transcript = transcriber.transcribe(audio_bytes)
            logger.info("Transcription complete.")
            return transcript.text or ""
        except Exception as e:
            logger.error(f"STT error: {e}")
            return ""
