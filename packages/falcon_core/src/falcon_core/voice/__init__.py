"""Voice assistant logic shared by the API and the STT services: wake phrase, intent, ASR guards.

Everything here is deterministic and pure (no I/O, no LLM). Transcripts are handled in memory only.
"""

from falcon_core.voice.intent import Intent, VoiceResult, analyse

__all__ = ["Intent", "VoiceResult", "analyse"]
