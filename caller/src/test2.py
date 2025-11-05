import json
import logging
from typing import Dict, Any, List, Optional
import requests
from time import time

# use the package config if available
try:
    from caller.config import default_config
    BASE = default_config.api_base_url.rstrip("/")
except Exception:
    BASE = "http://127.0.0.1:5055/api"

LOG = logging.getLogger("caller.test2")
logging.basicConfig(level=logging.INFO)


def _url(path: str) -> str:
    base = BASE.rstrip("/")
    if path.startswith("/"):
        path = path[1:]
    return f"{base}/{path}"


def get_sources() -> List[Dict[str, Any]]:
    url = _url("/sources")
    LOG.info("GET %s", url)
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def create_session_for_source(source_id: str, title: Optional[str] = None, model_override: Optional[str] = None) -> Dict[str, Any]:
    url = _url(f"/sources/{source_id}/chat/sessions")
    payload = {"source_id": source_id}
    if title:
        payload["title"] = title
    if model_override:
        payload["model_override"] = model_override
    LOG.info("POST %s -> %s", url, json.dumps(payload))
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def send_message_stream(source_id: str, session_id: str, message: str, model_override: Optional[str] = None):
    url = _url(f"/sources/{source_id}/chat/sessions/{session_id}/messages")
    payload = {"message": message}
    if model_override:
        payload["model_override"] = model_override
    LOG.info("POST (stream) %s -> %s", url, json.dumps(payload))
    # streaming SSE-like response; use stream=True and iterate lines
    with requests.post(url, json=payload, stream=True, timeout=60) as r:
        try:
            r.raise_for_status()
        except Exception:
            LOG.error("Streaming request failed: %s %s", r.status_code, r.text)
            raise
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            # SSE lines often start with "data: "
            line = raw.strip()
            if line.startswith("data:"):
                body = line[len("data:"):].strip()
            else:
                body = line
            try:
                ev = json.loads(body)
            except Exception:
                LOG.info("STREAM TEXT: %s", body)
                continue
            # print structured events
            ev_type = ev.get("type") or ev.get("event") or "message"
            LOG.info("EVENT %s: %s", ev_type, json.dumps(ev, ensure_ascii=False)[:2000])


def main():
    try:
        # Fetch and log default models from server
        defaults_url = _url("/models/defaults")
        LOG.info("Fetching default models from %s", defaults_url)
        try:
            dresp = requests.get(defaults_url, timeout=10)
            dresp.raise_for_status()
            defaults = dresp.json()
            LOG.info("=== SERVER DEFAULT MODELS ===")
            LOG.info("  Chat Model:          %s", defaults.get("default_chat_model"))
            LOG.info("  Transformation Model:%s", defaults.get("default_transformation_model"))
            LOG.info("  Embedding Model:     %s", defaults.get("default_embedding_model"))
            LOG.info("=============================")
        except Exception as e:
            LOG.warning("Could not fetch /models/defaults: %s", e)
            defaults = {}

        sources = get_sources()
        if not sources:
            LOG.error("No sources available at %s/sources", BASE)
            return
        first = sources[0]
        source_id = first.get("id") or first.get("source_id") or first.get("uid")
        title = first.get("title") or ""
        LOG.info("Using source: %s (%s)", source_id, title)

        # --- SOURCE-CHAT (existing): create source chat session and stream ---
        sess = create_session_for_source(source_id, title=f"test-session-{int(time())}")
        session_id = sess.get("id")
        LOG.info("Created session: %s", session_id)

        # send a short probe message asking what the document is about
        question = """Does this project include soakage or infiltration systems for stormwater disposal?

Look for evidence of:
- Soakage/infiltration systems
- Product names: GRAF, Atlantis, Stormtech, soakholes, soakage trenches
- Terms: soakage, infiltration, percolation, disposal to ground
- Materials: geotextile-wrapped crates, permeable aggregate surrounds
- Drawing titles containing "soakage" or "infiltration"

Answer with YES or NO followed by a brief explanation citing specific evidence from the documents."""
        # question = "any soakage design/info trench? and show me the extract fo exact text you found for this"
        send_message_stream(source_id, session_id, question)

        # --- NOTEBOOK-STYLE FLOW (using QueryClient.notebook_ask) ---
        LOG.info("=== Running notebook-style ask (via QueryClient.notebook_ask) ===")
        from caller.query_client import QueryClient
        qc = QueryClient()
        result = qc.notebook_ask(source_id=source_id, message=question)
        LOG.info("Notebook ID: %s", result.get("notebook_id"))
        LOG.info("Session ID: %s", result.get("session_id"))
        LOG.info("Message count: %s", len(result.get("messages", [])))
        LOG.info("=== AI Answer (first 1000 chars) ===")
        LOG.info("%s", result.get("ai_answer")[:1000])

    except requests.HTTPError as e:
        LOG.error("HTTP error: %s %s", getattr(e.response, "status_code", None), getattr(e.response, "text", None))
    except Exception as e:
        LOG.exception("Unexpected error: %s", e)


if __name__ == "__main__":
    main()
