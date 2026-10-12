"""Upload the vendor master + AP policy to your Evolus knowledge library (via API).

    python scripts/upload_library.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledgerpilot.config import load_settings  # noqa: E402
from ledgerpilot.evolus_client import EvolusClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
s = load_settings()
if not s.library_id:
    sys.exit("Set EVOLUS_LIBRARY_ID in .env first.")
client = EvolusClient(s)
pdf = ROOT / "data" / "vendor_master.pdf"
print(client.upload_library_document(pdf.name, pdf.read_bytes(), language="en"))
print("Indexing runs in the background. Current documents:")
print(client.list_library_documents())
