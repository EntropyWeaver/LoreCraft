import json

from ficcion.demo import DemoBackend
from ficcion.evaluation import RUBRIC, _signals, evaluate, EvalCase
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


def test_adult_intimacy_suite_covers_ladder_and_stop_without_auto_scores(tmp_path):
    folder, report = evaluate(ModelProfile(), tmp_path, backend=DemoBackend(), suite="intimacy")
    assert report["status"] == "completed" and report["protocol"] == "kepler-intimacy-eval-v2"
    assert [row["intensity"] for row in report["turns"]] == [0, 1, 2, 3, 4, 5, 3, 0]
    assert report["turns"][-1]["case"] == "adulto_7_parada"
    assert all(set(row["human_scores"]) == set(RUBRIC) for row in report["turns"])
    assert all(all(score is None for score in row["human_scores"].values()) for row in report["turns"])
    assert (folder / "report.md").read_text(encoding="utf-8").count("## adulto_") == 8


def test_evaluation_rejects_turn_count_above_suite_size(tmp_path):
    try:
        evaluate(ModelProfile(), tmp_path, backend=DemoBackend(), suite="core", max_turns=7)
    except ValueError as exc:
        assert "entre 1 y 6" in str(exc)
    else:
        raise AssertionError("Debía rechazar un número de turnos fuera de la suite.")


def test_short_generic_refusal_is_detected():
    signals = _signals("Lo siento, no puedo hacer eso.", "", [], EvalCase("x", "x", intensity=5))
    assert signals["response_mode"] == "refusal"
