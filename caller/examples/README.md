This example demonstrates how to use the `caller.Application` helper classes to upload or register a PDF and query the system.

Steps:

1. Ensure the backend API is running (default: http://localhost:8000/api).
2. Edit `example_upload_and_query.py` and set `local_pdf` to a valid PDF file on your machine.
3. Run the example from the repository root using module mode (recommended):

```powershell
python -m caller.examples.example_upload_and_query
```

What the example does:
- Uploads a PDF using the `POST /api/sources` endpoint (async processing by default).
- Polls the source status using `GET /api/sources/{id}/status` until the background job completes.
- Runs a simple ask query against the backend using the newly-embedded source as context.

Notes:
- To avoid re-uploading large files, copy the file into the backend uploads folder and use the server file path with `register_and_process_file(server_path=...)`.
- The Application uses backend defaults for models; to override model selections, set them in `caller/config.py` or extend the Application to pass model IDs where supported by the backend.
