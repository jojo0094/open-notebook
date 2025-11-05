Caller helper utilities for uploading PDFs, triggering embedding, and querying.

Layout note:
The implementation uses a src-layout under `caller/src/caller/` so the package
can be imported both when running from repository root and when installed.

Running the example:

From repository root (recommended):

```powershell
python -m caller.examples.example_upload_and_query
```

Or run directly from examples folder:

```powershell
cd caller\examples
python example_upload_and_query.py
```

If you prefer, install the package in editable mode from repository root:

```powershell
pip install -e .\caller
```

