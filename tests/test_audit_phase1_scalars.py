import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "drawing-utilities" / "audit_phase1_scalars.py"
SPEC = importlib.util.spec_from_file_location("audit_phase1_scalars", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Phase1ScalarAuditTests(unittest.TestCase):
    def test_load_summarize_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = []
            for iteration, score, school in ((1, .8, .1), (2, .6, .2)):
                candidate = root / "real_sims" / "phase" / f"iter_{iteration}" / "cand_01"
                candidate.mkdir(parents=True)
                candidate.joinpath("config.json").write_text(json.dumps({
                    "transmission_probabilities": {
                        "school": school, "class": .3, "age_coupling_param": .6}}))
                components = {key: {"value": score + index / 10}
                              for index, key in enumerate(MODULE.COMPONENTS)}
                history.append({"status": "completed", "stage": "phase",
                                "iteration": iteration, "candidate": 1, "score": score,
                                "metrics": {"metrics": {
                                    "selection_score_components": components,
                                    "quality_gates": {"achieved_levels": [.5]}}}})
            root.joinpath("optimizer_history.json").write_text(json.dumps(history))
            records = MODULE.load_records(root)
            summary = MODULE.summarize(records)
            self.assertEqual(summary["best"]["iteration"], 2)
            self.assertEqual(summary["quality_gate_level_counts"]["0.5"], 2)
            output = root / "plots"
            MODULE.write_outputs(summary, output)
            self.assertIn("Selection score progression", (output / "score_progress.svg").read_text())
            self.assertTrue((output / "audit_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
