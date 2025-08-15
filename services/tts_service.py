from murf import Murf
import logging

logger = logging.getLogger(__name__)

class TTSService:
    def __init__(self, api_key, default_voice="en-US-natalie"):
        self.client = Murf(api_key=api_key) if api_key else None
        self.default_voice = default_voice

    def synthesize(self, text, voice_id=None):
        voice_id = voice_id or self.default_voice
        try:
            res = self.client.text_to_speech.generate(
                text=text, voice_id=voice_id,
                format="MP3", sample_rate=44100.0
            )
            logger.info("TTS synthesis complete.")
            return res.audio_file
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None
