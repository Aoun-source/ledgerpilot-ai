"""Upload the vendor master + AP policy and the AP fraud guide to your Evolus knowledge library (via API).

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
# The vendor master (supplier IDs, names, bank accounts, AP policy) and a short fraud guide the agent can
# teach from. A document already in the library is skipped, so the script is safe to run again.
present = {d.get("title") for d in (client.list_library_documents() or []) if isinstance(d, dict)}
for doc in (ROOT / "data" / "vendor_master.pdf", ROOT / "data" / "ap_fraud_guide.md"):
    if doc.name in present:
        print(f"{doc.name}: already in the library, skipped")
        continue
    print(client.upload_library_document(doc.name, doc.read_bytes(), language="en"))
print("Indexing runs in the background. Current documents:")
for d in client.list_library_documents() or []:
    print(f"  {d.get('title')}  (ingestion status {d.get('ingestionStatus')})")
