from dataclasses import dataclass
from typing import Optional


@dataclass
class CallerConfig:
    """Configuration for caller utilities.

    api_base_url should point to the running backend API root (no trailing slash).
    The model_* fields can be used to override DB defaults by passing model IDs.
    If set, the caller will use these model ids in requests; if None, server defaults are used.
    
    Example:
      config = CallerConfig(
          default_chat_model="claude-sonnet-4-20250514",
          default_transformation_model="gpt-5-mini"
      )
    """
    api_base_url: str = "http://localhost:5055/api"
    # Optional model IDs (stored in DB); if None the backend default models will be used
    default_embedding_model: Optional[str] = None
    default_chat_model: Optional[str] = None  # e.g. "claude-sonnet-4-20250514"
    default_transformation_model: Optional[str] = None  # e.g. "gpt-5-mini"
    large_context_model: Optional[str] = None
    default_text_to_speech_model: Optional[str] = None
    default_speech_to_text_model: Optional[str] = None
    default_tools_model: Optional[str] = None
    timeout_seconds: int = 60


default_config = CallerConfig()
