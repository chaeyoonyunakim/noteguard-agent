"""Download NHSEDataScience/synthetic_clinical_notes (Silver tier) to data/.

Usage:
    python src/fetch_dataset.py

Downloads three CSVs into ./data/:
    synthetic_clinical_notes.csv  patients.csv  admissions.csv

Run once before starting the server to enable /samples and /sample/* endpoints.
Requires:  huggingface_hub  (pip install huggingface_hub)
"""

from __future__ import annotations

import shutil
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
REPO_ID = "NHSEDataScience/synthetic_clinical_notes"
SILVER_FILES = [
    "silver/synthetic_clinical_notes.csv",
    "silver/patients.csv",
    "silver/admissions.csv",
]


def fetch() -> None:
    from huggingface_hub import hf_hub_download

    DATA_DIR.mkdir(exist_ok=True)
    for remote_path in SILVER_FILES:
        dest = DATA_DIR / Path(remote_path).name
        print(f"  {remote_path} ...", end=" ", flush=True)
        cached = hf_hub_download(repo_id=REPO_ID, filename=remote_path, repo_type="dataset")
        shutil.copy(cached, dest)
        print(f"-> {dest.name}")
    print(f"\nDone. Files in {DATA_DIR}/")


if __name__ == "__main__":
    fetch()
