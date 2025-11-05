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

    try:
        # register or upload; PdfUploader now returns a normalized dict with 'sources' list
        resp = app.register_and_process_file(local_path=local_pdf, embed=True, async_processing=True)
        LOG.info("Upload response: %s", resp)

        # Determine source id: prefer normalized response shape, fall back to previous keys
        source_id = None
        if isinstance(resp, dict):
            if resp.get("sources"):
                source_id = resp["sources"][0].get("id")
            elif resp.get("id"):
                source_id = resp.get("id")

        # If not found, try to find via uploader helper using filename
        if not source_id:
            filename = local_pdf.split("\\")[-1]
            found = app.uploader.find_source_for_file(filename)
            if found:
                source_id = found.get("id")

        if not source_id:
            raise RuntimeError("Could not determine source id for uploaded file")

        LOG.info("Using source id: %s", source_id)

        # Create a chat session for this source
        base = app.uploader.base.rstrip("/")
        create_url = f"{base}/sources/{source_id}/chat/sessions"
        sess_payload = {"source_id": source_id, "title": f"test-session-{int(time())}"}
        LOG.info("Creating session: %s -> %s", create_url, sess_payload)
        r = requests.post(create_url, json=sess_payload, timeout=10)
        r.raise_for_status()
        sess = r.json()
        session_id = sess.get("id")
        LOG.info("Created session: %s", session_id)

        # Ask a short question and stream the response
        # question = "Hi — briefly, what is this document about?"
        question = """Does this project include soakage or infiltration systems for stormwater disposal?

Look for evidence of:
- Soakage/infiltration systems
- Product names: GRAF, Atlantis, Stormtech, soakholes, soakage trenches
- Terms: soakage, infiltration, percolation, disposal to ground
- Materials: geotextile-wrapped crates, permeable aggregate surrounds
- Drawing titles containing "soakage" or "infiltration"

Answer with YES or NO followed by a brief explanation citing specific evidence from the documents."""
        msg_url = f"{base}/sources/{source_id}/chat/sessions/{session_id}/messages"
        _stream_post(msg_url, {"message": question}, timeout=120)

    except Exception as e:
        LOG.exception("Test failed: %s", e)


if __name__ == "__main__":
    main()
