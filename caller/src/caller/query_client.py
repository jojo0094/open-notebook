import logging
from typing import List, Optional, Dict, Any
import json
from time import time

import requests

from .config import default_config

logger = logging.getLogger("caller.query_client")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


class QueryClient:
    """Client to query the backend search/ask APIs using pre-embedded documents."""

    def __init__(self, config=default_config):
        self.base = config.api_base_url.rstrip("/")
        self.timeout = config.timeout_seconds

    def vector_search(self, query: str, results: int = 10, minimum_score: float = 0.2) -> List[Dict[str, Any]]:
        """Call the backend vector search via the generic /search endpoint. Returns list of hits."""
        url = f"{self.base}/search"
        payload = {
            "query": query,
            "type": "vector",
            "limit": results,
            "search_sources": True,
            "search_notes": False,
            "minimum_score": minimum_score,
        }
        logger.info("Running vector search (via /search) for: %s", query)
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("results", [])
        return data

    def text_search(self, query: str, results: int = 10) -> List[Dict[str, Any]]:
        url = f"{self.base}/search"
        payload = {
            "query": query,
            "type": "text",
            "limit": results,
            "search_sources": True,
            "search_notes": False,
        }
        logger.info("Running text search (via /search) for: %s", query)
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("results", [])
        return data

    def ask(self, prompt: str, source_ids: Optional[List[str]] = None, model_override: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """High-level ask helper.

        If `source_ids` is provided we perform a vector search and then client-side filter results to those sources.
        Otherwise we call the ask/simple endpoint using default models fetched from /models/defaults.
        """

        if source_ids:
            # Use the source-chat session endpoints (create session + stream messages)
            # Pick the first provided source_id and create a session for it.
            src = source_ids[0]
            source_id = src if str(src).startswith("source:") else f"{src}"

            # Fetch default models from server to use for session/message if no override provided
            defaults = {}
            try:
                durl = f"{self.base}/models/defaults"
                logger.info("Fetching default models from %s", durl)
                dresp = requests.get(durl, timeout=self.timeout)
                dresp.raise_for_status()
                defaults = dresp.json() or {}
            except Exception:
                logger.info("Unable to fetch /models/defaults; proceeding without defaults")

            strategy_model = model_override or defaults.get("default_transformation_model") or defaults.get("default_chat_model")

            create_url = f"{self.base}/sources/{source_id}/chat/sessions"
            payload = {"source_id": source_id, "title": f"query-{int(time())}", "model_override": strategy_model}
            logger.info("Creating source chat session: %s -> %s", create_url, payload)
            try:
                cresp = requests.post(create_url, json=payload, timeout=self.timeout)
                cresp.raise_for_status()
                session = cresp.json()
                session_id = session.get("id")
            except Exception as e:
                logger.error("Failed to create source chat session: %s %s", getattr(e, 'response', None), e)
                raise

            # Send message to session and stream SSE-like response (text lines)
            stream_url = f"{self.base}/sources/{source_id}/chat/sessions/{session_id}/messages"
            stream_payload = {"message": prompt}
            # prefer explicit model_override, else use server default if available
            if model_override:
                stream_payload["model_override"] = model_override
            elif strategy_model:
                stream_payload["model_override"] = strategy_model

            logger.info("Posting message (stream) to %s", stream_url)
            events: List[Dict[str, Any]] = []
            ai_chunks: List[str] = []
            with requests.post(stream_url, json=stream_payload, stream=True, timeout=max(60, self.timeout)) as r:
                try:
                    r.raise_for_status()
                except Exception:
                    logger.error("Streaming request failed: %s %s", r.status_code, r.text)
                    raise

                for raw in r.iter_lines(decode_unicode=True):
                    if not raw:
                        continue
                    line = raw.strip()
                    if line.startswith("data:"):
                        body = line[len("data:"):].strip()
                    else:
                        body = line
                    try:
                        ev = json.loads(body)
                    except Exception:
                        # plain text chunk
                        events.append({"type": "text", "text": body})
                        continue

                    events.append(ev)
                    ev_type = ev.get("type") or ev.get("event") or "message"
                    if ev_type == "ai_message":
                        content = ev.get("content") or ev.get("data") or ""
                        ai_chunks.append(content)

            answer_text = "".join(ai_chunks)
            return {"search_results": [], "total": len(ai_chunks), "answer": answer_text, "events": events}

        # fetch default models
        defaults_url = f"{self.base}/models/defaults"
        try:
            dresp = requests.get(defaults_url, timeout=self.timeout)
            dresp.raise_for_status()
            defaults = dresp.json()
        except Exception:
            defaults = {}

        strategy = defaults.get("default_transformation_model") or defaults.get("default_chat_model")
        answer = defaults.get("default_chat_model")
        final = defaults.get("default_chat_model")

        ask_url = f"{self.base}/search/ask/simple"
        ask_payload = {
            "question": prompt,
            "strategy_model": strategy,
            "answer_model": answer,
            "final_answer_model": final,
        }
        if model_override:
            ask_payload["strategy_model"] = model_override
            ask_payload["answer_model"] = model_override
            ask_payload["final_answer_model"] = model_override

        logger.info("Sending ask/simple request to backend (strategy=%s)", ask_payload.get("strategy_model"))
        resp = requests.post(ask_url, json=ask_payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def notebook_ask(self, source_id: str, message: str, model_override: Optional[str] = None, notebook_id: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the notebook (search->transform->chat) pipeline scoped to a single source.
        This replicates the frontend "Chat with Notebook" flow:
          1. Fetch default models from /models/defaults
          2. Create a temporary notebook (if notebook_id not provided)
          3. Link the source to the notebook
          4. Build context via POST /chat/context with context_config mapping source to 'full content'
          5. Create a notebook chat session (if session_id not provided)
          6. Execute chat via POST /chat/execute with the built context and model_override
        
        Returns dict with keys:
          - notebook_id, session_id, messages (list), ai_answer (str, last AI message content)
        """
        # 1) Fetch default models
        defaults = {}
        try:
            durl = f"{self.base}/models/defaults"
            logger.info("Fetching default models from %s", durl)
            dresp = requests.get(durl, timeout=self.timeout)
            dresp.raise_for_status()
            defaults = dresp.json() or {}
            logger.info("Server models: chat=%s, transformation=%s", defaults.get("default_chat_model"), defaults.get("default_transformation_model"))
        except Exception as e:
            logger.warning("Unable to fetch /models/defaults: %s", e)

        # 2) Create notebook if not provided
        if not notebook_id:
            nb_url = f"{self.base}/notebooks"
            nb_payload = {"name": f"temp-notebook-{int(time())}", "description": "Temporary notebook for source-scoped query"}
            logger.info("Creating notebook: POST %s", nb_url)
            nb_resp = requests.post(nb_url, json=nb_payload, timeout=self.timeout)
            nb_resp.raise_for_status()
            notebook_id = nb_resp.json().get("id")
            logger.info("Created notebook: %s", notebook_id)

        # 3) Link source to notebook
        link_url = f"{self.base}/notebooks/{notebook_id}/sources/{source_id}"
        logger.info("Linking source to notebook: POST %s", link_url)
        lresp = requests.post(link_url, timeout=self.timeout)
        lresp.raise_for_status()

        # 4) Build context via /chat/context (this runs transformation model)
        context_config = {"sources": {source_id: "full content"}, "notes": {}}
        ctx_url = f"{self.base}/chat/context"
        ctx_payload = {"notebook_id": notebook_id, "context_config": context_config}
        logger.info("Building notebook context: POST %s", ctx_url)
        ctx_resp = requests.post(ctx_url, json=ctx_payload, timeout=max(30, self.timeout))
        ctx_resp.raise_for_status()
        context_data = ctx_resp.json()
        built_context = context_data.get("context")
        logger.info("Context built: token_count=%s char_count=%s", context_data.get("token_count"), context_data.get("char_count"))

        # 5) Create notebook chat session if not provided
        if not session_id:
            sess_url = f"{self.base}/chat/sessions"
            sess_payload = {"notebook_id": notebook_id, "title": f"nb-session-{int(time())}"}
            logger.info("Creating notebook session: POST %s", sess_url)
            sresp = requests.post(sess_url, json=sess_payload, timeout=self.timeout)
            sresp.raise_for_status()
            session_id = sresp.json().get("id")
            logger.info("Created notebook session: %s", session_id)

        # 6) Execute chat via /chat/execute with built context
        exec_url = f"{self.base}/chat/execute"
        exec_payload = {
            "session_id": session_id,
            "message": message,
            "context": built_context,
            "model_override": model_override or defaults.get("default_chat_model")
        }
        logger.info("Executing chat (POST %s) with chat_model=%s", exec_url, exec_payload.get("model_override"))
        exec_resp = requests.post(exec_url, json=exec_payload, timeout=max(60, self.timeout))
        exec_resp.raise_for_status()
        resp_data = exec_resp.json()

        # Extract AI answer from messages
        msgs = resp_data.get("messages", [])
        ai_answer = ""
        if msgs:
            last_msg = msgs[-1]
            if last_msg.get("type") == "ai":
                ai_answer = last_msg.get("content", "")

        return {
            "notebook_id": notebook_id,
            "session_id": session_id,
            "messages": msgs,
            "ai_answer": ai_answer
        }
