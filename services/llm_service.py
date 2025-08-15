import google.genai
import logging

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, api_key):
        self.client = google.genai.Client(api_key=api_key) if api_key else None

    def get_response(self, dialog):
        try:
            resp = self.client.models.generate_content(
                model="gemini-2.5-flash", contents=dialog
            )
            logger.info("LLM response generated.")
            return resp.text or ""
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return ""
