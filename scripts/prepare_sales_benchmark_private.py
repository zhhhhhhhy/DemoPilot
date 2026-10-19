"""Recreate only missing local scoring plans with the original sealed hashes."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from demopilot.quotation_contract import compile_acceptance  # noqa: E402


def prepare(root=ROOT):
    root = Path(root).resolve()
    dataset = root / "evaluation_sets/sales-benchmark-v3"
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    cases = json.loads((dataset / "cases.json").read_text("utf-8"))["cases"]
    created = verified = 0
    for case in cases:
        identifier = case["id"]
        if not re.fullmatch(r"sales-v3-\d{3}", identifier):
            raise ValueError("Invalid requirement ID")
        relative = f"evaluation_sets/sales-benchmark-v3/private/{identifier}.json"
        target = root / relative
        expected = manifest["files"][relative]
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("Existing scoring plan drift; will not overwrite: " + identifier)
        else:
            public_relative = f"testdata/{identifier}/contract.json"
            source = root / public_relative
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest["files"][public_relative]:
                raise ValueError("Public contract drift")
            compiled = compile_acceptance(json.loads(data), private=True)
            payload = (json.dumps(compiled, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if hashlib.sha256(payload).hexdigest() != expected:
                # The original authoring host used Windows text newlines.
                # Recover whichever exact representation the sealed hash names,
                # without changing labels, manifests or existing files.
                windows_payload = payload.replace(b"\n", b"\r\n")
                if hashlib.sha256(windows_payload).hexdigest() != expected:
                    raise ValueError("Compiler output no longer matches sealed plan")
                payload = windows_payload
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(payload)
            created += 1
        verified += 1
    return dict(
        status="passed",
        created=created,
        verified=verified,
        public_or_manifest_modified=False,
        boundary="Exact missing-file recovery only; does not recreate model runs or independent acceptance results.",
    )


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
