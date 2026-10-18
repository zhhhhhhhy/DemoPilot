import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_sales_intent_paired_real as paired

from demopilot.models import DemoRun, RunStatus
from demopilot.storage import RunStore


def test_terminal_durable_record_is_finalized_without_a_new_cli_call(tmp_path):
    item = paired.load_experiment_cases()[0]
    store = RunStore(tmp_path / "data")
    run = DemoRun(id="012345abcdef", request=paired.core_request(item, "raw-sales"),
                  status=RunStatus.FAILED, error="Previous terminal failure")
    store.create(run)
    output = tmp_path / "results"
    trace = output / item["id"] / "raw-sales"
    paired.write_json(trace / "progress.json", {
        "run_id": run.id, "status": "core_running", "started_at": run.created_at.isoformat(),
    })
    # An object with no provider methods makes any repeated model startup fail.
    result = asyncio.run(paired.run_arm(item, "raw-sales", store, object(), output))
    assert result["run_id"] == run.id
    assert result["status"] == "failed"
    assert result["total_cli_calls"] == 0
    assert (trace / "result.json").is_file()
    assert paired.json.loads((trace / "progress.json").read_text())["status"] == "terminal"
    assert len(store.list()) == 1
