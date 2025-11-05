import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests

from .config import default_config

logger = logging.getLogger("caller.pdf_uploader")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


class PdfUploader:
    """Upload PDF to backend and optionally trigger embedding.

    Usage patterns:
    - upload_file_and_process(upload_path, notebooks=None, embed=True, async_processing=True)
      Uploads the file and starts processing via POST /api/sources (multipart form).

    - reference_existing_file(source_file_path, title, notebooks=None, embed=True, async_processing=True)
      Tells backend to create a Source record referencing an existing file path already on the server
      (uses POST /api/sources with JSON payload pointing to file_path). This avoids re-upload.
    """

    def __init__(self, config=default_config):
        self.base = config.api_base_url.rstrip("/")
        self.timeout = config.timeout_seconds
        # debug flag: when True, `find_source_for_file` will log candidate matches
        self.debug_candidates = False

    # ---- Internal helpers for consistent responses ----
    def _wrap_response(self, resp: requests.Response) -> Dict[str, Any]:
        """Normalize requests.Response into a consistent dict."""
        out = {
            "ok": False,
            "status_code": getattr(resp, "status_code", None),
            "data": None,
            "text": None,
            "error": None,
        }
        try:
            out["text"] = resp.text
            if resp.text:
                try:
                    out["data"] = resp.json()
                except Exception:
                    out["data"] = resp.text
        except Exception as e:
            out["error"] = str(e)
        if hasattr(resp, "ok"):
            out["ok"] = resp.ok
        return out

    def _normalize_source_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Return a consistent source dict with expected keys (keeps raw under 'raw')."""
        asset = item.get("asset") or {}
        normalized = {
            "id": item.get("id"),
            "title": item.get("title"),
            "asset_file_path": asset.get("file_path") if isinstance(asset, dict) else None,
            "asset_url": asset.get("url") if isinstance(asset, dict) else None,
            "embedded": item.get("embedded", False),
            "embedded_chunks": item.get("embedded_chunks", 0),
            "insights_count": item.get("insights_count", 0),
            "created": item.get("created"),
            "updated": item.get("updated"),
            "file_available": item.get("file_available"),
            "command_id": item.get("command_id"),
            "status": item.get("status"),
            "processing_info": item.get("processing_info"),
            "raw": item,
        }
        return normalized

    def _normalize_sources(self, data: Any) -> List[Dict[str, Any]]:
        """Accept various server shapes and return a list of normalized source dicts."""
        if data is None:
            return []
        if isinstance(data, list):
            return [self._normalize_source_item(i) for i in data]
        if isinstance(data, dict):
            # Some endpoints return {"results": [...]} or a single source dict
            if "results" in data and isinstance(data["results"], list):
                return [self._normalize_source_item(i) for i in data["results"]]
            # Single source dict -> wrap
            if data.get("id") or data.get("title"):
                return [self._normalize_source_item(data)]
            # Unknown dict shape -> try to find nested list
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0]:
                    return [self._normalize_source_item(i) for i in v]
        # fallback: cannot parse -> return empty
        return []

    # ---- Public methods ----
    def source_exists(self, filename: str) -> bool:
        """Check if a source with the given filename already exists.

        Args:
            filename: The filename to search for (e.g., "my_document.pdf")

        Returns:
            bool: True if source exists, False otherwise
        """
        found = self.find_source_for_file(filename)
        return found is not None

    def get_source_id(self, filename: str) -> Optional[str]:
        """Return id of best-matching source or None."""
        src = self.find_source_for_file(filename)
        return src.get("id") if src else None

    def upload_file_and_process(
        self,
        file_path: str,
        title: Optional[str] = None,
        notebooks: Optional[list] = None,
        embed: bool = True,
        async_processing: bool = True,
    ) -> Dict[str, Any]:
        """Upload a local PDF and request processing.
        Returns a normalized response dict:
            {
                "ok": bool,
                "status_code": int,
                "sources": [normalized_source,...],
                "raw": original_response_data,
                "error": optional error string
            }
        """
        filename = title or Path(file_path).name

        # If already exists, return the matched source without re-uploading
        existing = self.find_source_for_file(filename)
        if existing:
            logger.info(f"File '{filename}' already exists on server, skipping upload")
            return {"ok": True, "status_code": 200, "sources": [existing], "raw": None}

        url = f"{self.base}/sources"
        files = {"file": open(file_path, "rb")}
        data = {
            "type": "upload",
            "title": filename,
            "embed": str(embed).lower(),
            "async_processing": str(async_processing).lower(),
        }
        if notebooks:
            data["notebooks"] = json.dumps(notebooks)
        logger.info(f"Uploading {file_path} to {url} (async={async_processing})")
        resp = requests.post(url, files=files, data=data, timeout=self.timeout)
        wrapped = self._wrap_response(resp)
        if not wrapped["ok"]:
            logger.error(f"Upload failed ({wrapped['status_code']}): {wrapped['text']}")
            wrapped.update({"sources": []})
            return wrapped

        sources = self._normalize_sources(wrapped["data"])
        return {"ok": True, "status_code": wrapped["status_code"], "sources": sources, "raw": wrapped["data"]}

    def reference_existing_file(
        self,
        server_file_path: str,
        title: Optional[str] = None,
        notebooks: Optional[list] = None,
        embed: bool = True,
        async_processing: bool = True,
    ) -> Dict[str, Any]:
        """Create a Source record pointing to a file already present on the server uploads folder.

        Returns normalized response dict (same shape as upload_file_and_process).
        """
        url = f"{self.base}/sources"
        payload = {
            "type": "upload",
            "title": title or Path(server_file_path).name,
            "file_path": server_file_path,
            "embed": embed,
            "async_processing": async_processing,
        }
        if notebooks:
            payload["notebooks"] = notebooks

        headers = {"Content-Type": "application/json"}
        logger.info(f"Registering server file {server_file_path} with backend (async={async_processing})")
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        wrapped = self._wrap_response(resp)
        if not wrapped["ok"]:
            logger.error(f"Registering file failed ({wrapped['status_code']}): {wrapped['text']}")
            wrapped.update({"sources": []})
            return wrapped

        sources = self._normalize_sources(wrapped["data"])
        return {"ok": True, "status_code": wrapped["status_code"], "sources": sources, "raw": wrapped["data"]}

    def poll_source_status(self, source_id: str, poll_interval: float = 2.0, timeout: float = 600.0) -> Dict[str, Any]:
        """Poll `/sources/{id}/status` until completed/failed or timeout.

        Returns normalized dict:
            {
                "ok": True/False,
                "status_code": int,
                "status": "running"|"completed"|"failed",
                "processing_info": {...},
                "raw": original_response_data
            }
        """
        url = f"{self.base}/sources/{source_id}/status"
        start = time.time()
        logger.info(f"Polling status for source {source_id} at {url}")
        while True:
            resp = requests.get(url, timeout=self.timeout)
            wrapped = self._wrap_response(resp)
            if wrapped["ok"]:
                data = wrapped["data"] or {}
                status = data.get("status")
                logger.info(f"Status for {source_id}: {status}")
                if status in ("completed", "failed"):
                    return {
                        "ok": True,
                        "status_code": wrapped["status_code"],
                        "status": status,
                        "processing_info": data.get("processing_info"),
                        "raw": data,
                    }
            else:
                logger.warning(f"Status endpoint returned {wrapped['status_code']}: {wrapped.get('text')}")
            if time.time() - start > timeout:
                raise TimeoutError(f"Timed out waiting for source {source_id} status")
            time.sleep(poll_interval)

    def find_source_for_file(self, filename_or_path: str, notebook_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find best-matching source record for a given server file path or filename.

        Strips suffix patterns like " (5)" from both the target filename and source titles
        to match files that have been uploaded multiple times with server-added suffixes.

        Returns the normalized source dict or None if not found.
        If multiple matches exist the most-recently-updated is returned.
        """
        import re
        
        def normalize_filename(fname: str) -> str:
            """Strip suffix patterns like ' (5)' before extension.
            Example: 'file (5).PDF' -> 'file.pdf'
            """
            # Extract basename if path provided
            base = Path(fname).name
            # Split extension
            if '.' in base:
                name_part, ext = base.rsplit('.', 1)
                # Remove patterns like " (5)" at end of name
                name_part = re.sub(r'\s*\(\d+\)\s*$', '', name_part).strip()
                return f"{name_part}.{ext}".lower()
            return base.lower()
        
        params = {}
        if notebook_id:
            params["notebook_id"] = notebook_id

        url = f"{self.base}/sources"
        resp = requests.get(url, params=params, timeout=self.timeout)
        wrapped = self._wrap_response(resp)
        if not wrapped["ok"]:
            logger.error(f"Error listing sources: {wrapped.get('text')}")
            return None

        sources_raw = wrapped["data"]
        candidates = self._normalize_sources(sources_raw)

        target = str(filename_or_path)
        target_normalized = normalize_filename(target)
        target_basename = Path(target).name.lower()

        logger.info(f"Looking for source matching: {target} (normalized: {target_normalized})")

        exact_matches: List[Dict[str, Any]] = []
        basename_matches: List[Dict[str, Any]] = []
        normalized_matches: List[Dict[str, Any]] = []

        for s in candidates:
            file_path = (s.get("asset_file_path") or "") or ""
            title = (s.get("title") or "") or ""
            
            # Exact match on file_path
            if file_path and file_path == target:
                exact_matches.append(s)
                continue
            
            # Basename match on file_path
            if file_path and Path(file_path).name.lower() == target_basename:
                basename_matches.append(s)
                continue
            
            # Exact match on title
            if title and title.lower() == target_basename:
                basename_matches.append(s)
                continue
            
            # Normalized match (strips suffix like "(5)")
            if title:
                title_normalized = normalize_filename(title)
                if title_normalized == target_normalized:
                    logger.info(f"  Match: {title} -> {title_normalized}")
                    normalized_matches.append(s)

        results = exact_matches or basename_matches or normalized_matches or []

        if not results:
            logger.info(f"No matching source found for: {target}")
            return None

        # prefer most recently updated
        results.sort(key=lambda it: it.get("updated") or it.get("created") or "", reverse=True)
        logger.info(f"Selected source: {results[0].get('title')} (id: {results[0].get('id')})")
        return results[0]
