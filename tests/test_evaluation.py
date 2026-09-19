import json

from ficcion.demo import DemoBackend
from ficcion.evaluation import evaluate
from ficcion.llm import ModelError
from ficcion.runtime import ModelProfile


def test_evaluation_saves_evidence_without_inventing_quality_scores(tmp_path):
    folder, report = evaluate(ModelProfile(), tmp_path, backend=DemoBackend())
    assert report["status"] == "completed" and report["demo"]
    assert len(report["turns"]) == 6
    assert (folder / "report.md").is_file()
    saved = json.loads((folder / "report.json").read_text())
    assert saved["quality_status"] == "pending_human_review"
    assert all(all(v is None for v in t["human_scores"].values()) for t in saved["turns"])
    assert not any(t["signals"]["protected_markers_in_actor_context"] for t in saved["turns"])


def test_failed_generation_keeps_a_partial_report(tmp_path):
    class Failing(DemoBackend):
        def complete(self, *args):
            raise ModelError("Fallo simulado")
    folder, report = evaluate(ModelProfile(), tmp_path, backend=Failing())
    assert report["status"] == "failed"
    assert report["turns"][0]["status"] == "failed"
    assert json.loads((folder / "report.json").read_text())["status"] == "failed"
