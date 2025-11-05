import logging
from typing import List, Optional

from .config import default_config
from .pdf_uploader import PdfUploader
from .query_client import QueryClient


logger = logging.getLogger("caller.app")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
logger.addHandler(handler)


class Application:
    """High-level application class combining upload/register and query operations.

    Methods:
    - register_and_process_file: upload or reference file, optionally embed
    - trigger_embedding_for_source: call /commands/jobs to submit 'vectorize_source' or 'embed_single_item'
    - ask_with_sources: send prompt and list of source IDs to use as context
    """

    def __init__(self, config=default_config):
        self.config = config
        self.uploader = PdfUploader(config)
        self.qc = QueryClient(config)

    def register_and_process_file(self, local_path: Optional[str] = None, server_path: Optional[str] = None, title: Optional[str] = None, notebooks: Optional[List[str]] = None, embed: bool = True, async_processing: bool = True) -> dict:
        """If local_path provided, upload; if server_path provided, register existing file on server.

        Returns the created Source response from backend with fields including `id` and possibly `command_id`.
        """
        if local_path and server_path:
            raise ValueError("Provide either local_path or server_path, not both")

        if local_path:
            return self.uploader.upload_file_and_process(local_path, title=title, notebooks=notebooks, embed=embed, async_processing=async_processing)

        if server_path:
            return self.uploader.reference_existing_file(server_path, title=title, notebooks=notebooks, embed=embed, async_processing=async_processing)

        raise ValueError("Either local_path or server_path must be provided")

    def trigger_embedding_for_source(self, source_id: str, mode: str = "vectorize_source") -> dict:
        """Trigger embedding for an already-registered source by submitting a command job.

        mode can be 'vectorize_source' (orchestrates chunk jobs) or 'embed_single_item' (embeds single item).
        Returns job response from /commands/jobs endpoint.
        """
        import requests

        url = f"{self.config.api_base_url.rstrip('/')}/commands/jobs"
        if mode == "vectorize_source":
            cmd = "vectorize_source"
            payload = {"command": cmd, "app": "open_notebook", "input": {"source_id": source_id}}
        else:
            # embed single item
            cmd = "embed_single_item"
            payload = {"command": cmd, "app": "open_notebook", "input": {"item_id": source_id, "item_type": "source"}}

        logger.info(f"Submitting command {cmd} for source {source_id}")
        resp = requests.post(url, json=payload, timeout=self.config.timeout_seconds)
        resp.raise_for_status()
        return resp.json()

    def ask_with_sources(self, prompt: str, source_ids: Optional[List[str]] = None, model_override: Optional[str] = None, limit: int = 20) -> dict:
        """Ask a question and provide a list of source IDs to be used as context (embedding must exist)."""
        return self.qc.ask(prompt, source_ids=source_ids, model_override=model_override, limit=limit)

    def notebook_ask_with_source(self, source_id: str, message: str, model_override: Optional[str] = None, notebook_id: Optional[str] = None, session_id: Optional[str] = None) -> dict:
        """
        Run the notebook (search->transform->chat) pipeline scoped to a single source.
        This replicates the frontend "Chat with Notebook" flow and calls QueryClient.notebook_ask().
        
        Returns dict with keys: notebook_id, session_id, messages, ai_answer.
        """
        return self.qc.notebook_ask(source_id=source_id, message=message, model_override=model_override, notebook_id=notebook_id, session_id=session_id)
