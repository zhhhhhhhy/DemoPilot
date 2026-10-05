"""Collect a small, reproducible public invoice fixture set.

The source dataset is synthetic and released under CC BY 4.0.  We keep the
downloaded images and a compact manifest in the evaluation-set directory so a
future run does not depend on signed, expiring CDN URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any


DATASET = "alamgirqazi/invoice-ocr-synthetic"
DATASET_URL = f"https://huggingface.co/datasets/{DATASET}"
API_URL = (
    "https://datasets-server.huggingface.co/first-rows?"
    "dataset=alamgirqazi%2Finvoice-ocr-synthetic&config=default&split=train"
)
ALLOWED_TEMPLATES = {
    "formal_corporate",
    "freelancer_invoice",
    "modern_minimal",
    "utility_bill",
}


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "DemoPilot-eval/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DemoPilot-eval/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_sets/codex-cli-v1/assets/invoices"),
    )
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    if args.count != 10:
        raise SystemExit("The v1 contract requires exactly 10 invoice fixtures")

    args.output.mkdir(parents=True, exist_ok=True)
    payload = fetch_json(API_URL)
    rows = payload.get("rows", [])
    selected: list[dict[str, Any]] = []
    for item in rows:
        row = item.get("row", {})
        template = row.get("_template_used")
        if row.get("quality") != "clean" or template not in ALLOWED_TEMPLATES:
            continue
        if not (row.get("invoice_number") or row.get("document_number")):
            continue
        selected.append(item)
        if len(selected) == args.count:
            break
    if len(selected) != args.count:
        raise RuntimeError(f"Only found {len(selected)} eligible invoice rows")

    manifest: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        row = item["row"]
        image_url = row["image"]["src"]
        content = fetch_bytes(image_url)
        filename = f"invoice-{index:02d}.jpg"
        path = args.output / filename
        path.write_bytes(content)
        record_id = f"invoice-{index:02d}"
        manifest.append(
            {
                "id": record_id,
                "local_path": str(path.as_posix()),
                "source": {
                    "dataset": DATASET,
                    "dataset_url": DATASET_URL,
                    "api_url": API_URL,
                    "row_index": item["row_idx"],
                    "source_file_name": row.get("file_name"),
                    "template": row.get("_template_used"),
                    "quality": row.get("quality"),
                },
                "sha256": sha256(content),
                "bytes": len(content),
                "width": row["image"].get("width"),
                "height": row["image"].get("height"),
            }
        )
        gold.append(
            {
                "id": record_id,
                "source_row": item["row_idx"],
                "fields": {
                    "supplier_name": row.get("supplier_name"),
                    "customer_name": row.get("customer_name"),
                    "invoice_number": row.get("invoice_number") or row.get("document_number"),
                    "document_date": row.get("document_date"),
                    "currency": row.get("document_currency"),
                    "total_amount": row.get("document_total_amount"),
                    "total_net": row.get("document_total_net"),
                    "total_tax": row.get("document_total_tax"),
                    "line_items": row.get("line_items", []),
                },
            }
        )

    root = args.output.parent.parent
    (root / "invoice-manifest.json").write_text(
        json.dumps(
            {
                "dataset": DATASET,
                "dataset_url": DATASET_URL,
                "license": "CC BY 4.0",
                "synthetic": True,
                "privacy_note": "The source dataset states that names, addresses and identifiers are machine-generated.",
                "fixtures": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "invoice-gold.json").write_text(
        json.dumps(
            {
                "purpose": "Held-out reference only; do not include in the Codex CLI Builder prompt.",
                "source": DATASET_URL,
                "license": "CC BY 4.0",
                "records": gold,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"count": len(manifest), "manifest": str(root / "invoice-manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
