"""Test script: upload/register a PDF (if needed), create a source-chat session and ask a short question.

This adapts the 'test2' behavior into the top-level `caller/test.py` so you can run the same workflow
from the `caller` folder (e.g. `uv run .\test.py`).
"""

import json
import logging
from time import time
from typing import Optional

import requests

from caller.app import Application

LOG = logging.getLogger("caller.test")
logging.basicConfig(level=logging.INFO)


def _stream_post(url: str, payload: dict, timeout: int = 60):
    LOG.info("POST %s -> %s", url, json.dumps(payload, default=str)[:1000])
    with requests.post(url, json=payload, stream=True, timeout=timeout) as r:
        try:
            r.raise_for_status()
        except Exception:
            LOG.error("Request failed %s: %s", r.status_code, r.text)
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
                LOG.info("EVENT: %s", json.dumps(ev, ensure_ascii=False)[:2000])
            except Exception:
                LOG.info("STREAM: %s", body)


def main():
    app = Application()

    # adjust this path to a real local file on your machine
    local_pdf = r"C:\Users\jkyawkyaw\OneDrive - mpdc.govt.nz\workspace\Projects\Morrinsville SW\Data\AsBuilts\GenAI\Pippins Stage 1a\Approved Engineering Plans Stage 1A.PDF"
    
    # Extract the base filename from the path
    # This will be used to find if the source already exists (even with server suffix like "(5)")
    from pathlib import Path
    base_filename = Path(local_pdf).name
    
    try:
        # Check if source already exists
        # find_source_for_file() will normalize titles by stripping suffix patterns like "(5)"
        LOG.info("Checking if source already exists for: %s", base_filename)
        found = app.uploader.find_source_for_file(base_filename)
        
        if found:
            source_id = found.get("id")
            LOG.info("Found existing source: %s (title: %s)", source_id, found.get("title"))
            
            # Check if embedding is complete
            status_info = found.get("status")
            embedded = found.get("embedded", False)
            
            if not embedded or status_info not in ("completed", None):
                LOG.info("Source exists but embedding not complete. Polling status...")
                poll_result = app.uploader.poll_source_status(source_id, poll_interval=3.0, timeout=600.0)
                LOG.info("Poll result: status=%s", poll_result.get("status"))
                if poll_result.get("status") != "completed":
                    raise RuntimeError(f"Source processing failed or timed out: {poll_result}")
        else:
            # Upload new file
            LOG.info("Source not found, uploading: %s", local_pdf)
            resp = app.register_and_process_file(local_path=local_pdf, embed=True, async_processing=True)
            LOG.info("Upload response: %s", resp)

            # Determine source id from upload response
            source_id = None
            if isinstance(resp, dict):
                if resp.get("sources"):
                    source_id = resp["sources"][0].get("id")
                elif resp.get("id"):
                    source_id = resp.get("id")

            if not source_id:
                raise RuntimeError("Could not determine source id from upload response")

            LOG.info("Uploaded source id: %s, polling until embedding completes...", source_id)
            poll_result = app.uploader.poll_source_status(source_id, poll_interval=3.0, timeout=600.0)
            LOG.info("Poll result: status=%s", poll_result.get("status"))
            
            if poll_result.get("status") != "completed":
                raise RuntimeError(f"Source processing failed or timed out: {poll_result}")

        LOG.info("Source ready: %s", source_id)

        # Ask question using notebook-style pipeline (calls QueryClient.notebook_ask)
        question = """Does this project include soakage or infiltration systems for stormwater disposal?

Look for evidence of:
- Soakage/infiltration systems
- Product names: GRAF, Atlantis, Stormtech, soakholes, soakage trenches
- Terms: soakage, infiltration, percolation, disposal to ground
- Materials: geotextile-wrapped crates, permeable aggregate surrounds
- Drawing titles containing "soakage" or "infiltration"

Answer with YES or NO followed by a brief explanation citing specific evidence from the documents."""
        
        LOG.info("=== Running notebook-style ask (search->transform->chat) ===")
        result = app.notebook_ask_with_source(source_id=source_id, message=question)
        LOG.info("Notebook ID: %s", result.get("notebook_id"))
        LOG.info("Session ID: %s", result.get("session_id"))
        LOG.info("Message count: %s", len(result.get("messages", [])))
        LOG.info("=== AI Answer ===")
        LOG.info("%s", result.get("ai_answer"))

    except Exception as e:
        LOG.exception("Test failed: %s", e)


if __name__ == "__main__":
    main()
