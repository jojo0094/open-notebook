"""Example script demonstrating how to use caller.Application to upload/register a PDF, poll status, and ask a question.

Run from repository root with Python 3.10+ and ensure the backend API is running (default http://localhost:8000/api).
"""

# Ensure the repository root is on sys.path so "import caller" works even when executing this file directly.
# import sys
# from pathlib import Path
#
# _repo_root = Path(__file__).resolve().parents[2]  # .../open-notebook (two levels up from examples -> caller -> open-notebook root)
# # Fallback: if project layout is shifted, try one level higher
# if not _repo_root.exists() or not ( _repo_root / "api").exists():
#     _repo_root = Path(__file__).resolve().parents[3]
# if str(_repo_root) not in sys.path:
#     sys.path.insert(0, str(_repo_root))
#
import time
from caller.app import Application


def main():
    app = Application()

    # Example 1: upload local file and request async processing
    local_pdf = r"C:\Users\jkyawkyaw\OneDrive - mpdc.govt.nz\workspace\Projects\Morrinsville SW\Data\AsBuilts\GenAI\Pippins Stage 1a\Approved Engineering Plans Stage 1A.PDF"  # <-- change to a real local path
    try:
        resp = app.register_and_process_file(local_path=local_pdf, embed=True, async_processing=True)
        print("Upload response:", resp)

        source_id = resp.get("id")
        if resp.get("command_id"):
            print("Processing in background, command id:", resp.get("command_id"))
            # poll status until finished
            status = app.uploader.poll_source_status(source_id)
            print("Final status:", status)
        else:
            print("Sync processing returned result:", resp)

        # After embedding is complete, ask question using the embedded doc as context
        question = """Does this project include soakage or infiltration systems for stormwater disposal?

Look for evidence of:
- Soakage/infiltration systems
- Product names: GRAF, Atlantis, Stormtech, soakholes, soakage trenches
- Terms: soakage, infiltration, percolation, disposal to ground
- Materials: geotextile-wrapped crates, permeable aggregate surrounds
- Drawing titles containing "soakage" or "infiltration"

Answer with YES or NO followed by a brief explanation citing specific evidence from the documents."""

        # Use source_id to restrict search to the uploaded document (vector search)
        result = app.ask_with_sources(question, source_ids=[source_id])
        print("Search-based result:", result)

    except Exception as e:
        print("Example failed:", e)


if __name__ == "__main__":
    main()
