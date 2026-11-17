"""Tests for the resumable LLM-assisted FODA analysis."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

import foda_evaluation
import foda_structure
import tea_foda as foda


class FakeClient:
    def __init__(self):
        self.calls = []
        self.digest = "fake-model-digest"
        self.mode = "valid"

    def identity(self, model):
        return {
            "name": model,
            "digest": self.digest,
            "ollama_version": "test",
            "capabilities": [],
        }

    def chat(self, body, on_progress, cancel_event):
        self.calls.append(body)
        request = json.loads(body["messages"][1]["content"])
        if "targets" in request:
            features = []
            for item in request["targets"]:
                candidates = item["candidates"]
                features.append({
                    "id": item["id"],
                    "canonical_id": item["id"],
                    "parent_id": candidates[0]["id"] if candidates else None,
                    "needs_review": True,
                    "note": "Fixture proposal",
                })
            return {
                "done": True,
                "done_reason": "stop",
                "message": {"content": json.dumps({"features": features}, ensure_ascii=False)},
            }
        features = []
        for item in request["features"]:
            features.append({
                "id": item["id"],
                "canonical_name": item["name"].strip().capitalize(),
                "category": "Organização, rotinas e planejamento",
                "needs_review": False,
                "note": "",
            })
        if self.mode == "missing":
            features.pop()
        elif self.mode == "invalid-category":
            features[0]["category"] = "Categoria inventada"
        return {
            "done": True,
            "done_reason": "stop",
            "message": {"content": json.dumps({"features": features}, ensure_ascii=False)},
        }


class FodaPipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input_dir = self.root / "input"
        self.input_dir.mkdir()
        self.out = self.root / "foda"
        self.client = FakeClient()
        self._write_jsonl("corpus.jsonl", [
            {"appId": "app.one", "title": "Um", "groups": ["TDAH"], "description": "Descrição um"},
            {"appId": "app.two", "title": "Dois", "groups": ["TEA", "TDAH"], "description": "Descrição dois"},
            {"appId": "app.three", "title": "Três", "groups": ["TEA"], "description": "Descrição três"},
        ])
        self._write_jsonl("extractions.jsonl", [
            {"appId": "app.one", "status": "complete", "technical_complete": True},
            {"appId": "app.two", "status": "complete", "technical_complete": True},
            {"appId": "app.three", "status": "partial_error", "technical_complete": False},
        ])
        rows = [
            {"appId": "app.one", "title": "Um", "groups": "TDAH", "name": "Criar rotinas",
             "evidence": "Criar rotinas personalizadas.", "evidence_id": "s1", "start": "0", "end": "29",
             "app_complete": "True"},
            {"appId": "app.two", "title": "Dois", "groups": "TEA|TDAH", "name": "criar  rotinas",
             "evidence": "Crie rotinas ilustradas.", "evidence_id": "s2", "start": "0", "end": "24",
             "app_complete": "True"},
            {"appId": "app.three", "title": "Três", "groups": "TEA", "name": "Organizar agenda",
             "evidence": "Organize sua agenda.", "evidence_id": "s3", "start": "0", "end": "20",
             "app_complete": "False"},
        ]
        with (self.input_dir / "funcionalidades.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def tearDown(self):
        self.temp.cleanup()

    def _write_jsonl(self, name, rows):
        (self.input_dir / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_prepare_deduplicates_names_and_is_idempotent(self):
        first = foda.prepare(self.input_dir, self.out, batch_size=1)
        second = foda.prepare(self.input_dir, self.out, batch_size=1)
        self.assertEqual(first["unique_source_features"], 2)
        self.assertEqual(first["feature_rows"], 3)
        self.assertEqual(first["batches_total"], 2)
        self.assertEqual(second["batches_pending"], 2)

    def test_prepare_rejects_changed_input_or_batch_size(self):
        foda.prepare(self.input_dir, self.out, batch_size=1)
        with self.assertRaisesRegex(ValueError, "nova pasta"):
            foda.prepare(self.input_dir, self.out, batch_size=2)

    def test_prepare_rejects_inconsistent_completion_metadata(self):
        source = self.input_dir / "funcionalidades.csv"
        with source.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["app_complete"] = "False"
        with source.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, "diverge"):
            foda.prepare(self.input_dir, self.out, batch_size=1)

    def test_run_resumes_and_export_builds_auditable_model(self):
        foda.prepare(self.input_dir, self.out, batch_size=1)
        partial = foda.run(self.out, "fixture:1", limit=1, client=self.client)
        self.assertEqual(partial["batches_done"], 1)
        self.assertEqual(len(self.client.calls), 1)
        self.assertFalse(self.client.calls[0]["think"])

        finished = foda.run(self.out, "fixture:1", client=self.client)
        self.assertEqual(finished["batches_done"], 2)
        self.assertEqual(len(self.client.calls), 2)
        self.assertTrue(all(not call["think"] for call in self.client.calls))
        result = foda.export(self.out)
        self.assertTrue(result["model_complete"])
        self.assertEqual(result["feature_rows"], 3)
        self.assertTrue((self.out / "foda-model.json").is_file())
        self.assertTrue((self.out / "normalized-features.csv").is_file())
        with (self.out / "foda-model.json").open(encoding="utf-8") as stream:
            model = json.load(stream)
        self.assertEqual(model["statistics"]["canonical_features"], 2)
        self.assertTrue(all(edge["type"] == "category_contains" for edge in model["relationships"]))
        self.assertIn("variability candidate", model["feature_model"][3]["features"][0]["selection"])

    def test_export_handles_pending_mappings(self):
        foda.prepare(self.input_dir, self.out, batch_size=1)
        foda.run(self.out, "fixture:1", limit=1, client=self.client)

        result = foda.export(self.out)

        self.assertFalse(result["model_complete"])
        with (self.out / "review-queue.csv").open(encoding="utf-8-sig", newline="") as stream:
            review_rows = list(csv.DictReader(stream))
        self.assertTrue(any(row["mapping_status"] == "pending" for row in review_rows))

    def test_stratified_desmet_sample_and_reference_evaluation(self):
        foda.prepare(self.input_dir, self.out, batch_size=1)
        foda.run(self.out, "fixture:1", client=self.client)
        foda.export(self.out)
        sample_path = self.out / "reference.csv"
        sampled = foda_evaluation.create_sample(self.out, 3, 42, sample_path)
        self.assertEqual(sampled["sample_apps"], 3)
        with sample_path.open(encoding="utf-8-sig", newline="") as stream:
            sample_rows = list(csv.DictReader(stream))
        for row in sample_rows:
            app_id = row["appId"]
            gold = ["Organizar agenda"] if app_id == "app.three" else ["Criar rotinas"]
            row["reviewer1_features_json"] = json.dumps(gold, ensure_ascii=False)
            row["reviewer2_features_json"] = json.dumps(gold, ensure_ascii=False)
            row["adjudicated_features_json"] = json.dumps(gold, ensure_ascii=False)
            row["adjudicated_complete"] = "true"
            row["reviewer1_id"] = "reviewer-a"
            row["reviewer2_id"] = "reviewer-b"
            row["adjudicator_id"] = "reviewer-c"
        with sample_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=foda_evaluation.REFERENCE_FIELDS)
            writer.writeheader()
            writer.writerows(sample_rows)
        metrics = foda_evaluation.evaluate(self.out, sample_path)
        self.assertEqual(metrics["weighted_micro"]["precision"], 1.0)
        self.assertEqual(metrics["weighted_micro"]["recall"], 1.0)
        self.assertEqual(metrics["exact_app_match"], 1.0)
        self.assertEqual(metrics["inter_rater_agreement"]["exact_set_match"], 1.0)
        self.assertTrue((self.out / "desmet-report.json").is_file())

    def test_global_structure_proposals_export_without_asserting_validity(self):
        foda.prepare(self.input_dir, self.out, batch_size=1)
        foda.run(self.out, "fixture:1", client=self.client)
        prepared = foda.prepare_structure(self.out, batch_size=1)
        self.assertEqual(prepared["concepts"], 2)
        self.assertEqual(prepared["batches_pending"], 2)
        status = foda.run_structure(self.out, "fixture:1", client=self.client)
        self.assertEqual(status["batches_done"], 2)
        exported = foda.export(self.out)
        self.assertTrue(exported["model_complete"])
        with (self.out / "foda-model.json").open(encoding="utf-8") as stream:
            model = json.load(stream)
        self.assertTrue(model["structure_complete"])
        self.assertFalse(model["semantically_validated"])
        self.assertGreaterEqual(model["statistics"]["global_concepts_proposed"], 1)
        self.assertTrue(model["relationships"])
        self.assertTrue(all(edge["needs_review"] for edge in model["relationships"]
                            if edge["type"] == "proposed_parent_of"))

    def test_global_structure_rejects_ids_outside_candidate_list(self):
        target = {
            "id": "child",
            "candidates": [{"id": "allowed", "name": "Allowed parent"}],
        }
        good = {"features": [{
            "id": "child", "canonical_id": "allowed", "parent_id": None,
            "needs_review": True, "note": "",
        }]}
        self.assertEqual(len(foda_structure._decode(json.dumps(good), [target])), 1)
        bad = {"features": [{
            "id": "child", "canonical_id": "invented", "parent_id": None,
            "needs_review": True, "note": "",
        }]}
        with self.assertRaises(ValueError):
            foda_structure._decode(json.dumps(bad), [target])

    def test_invalid_or_incomplete_llm_output_is_not_accepted(self):
        foda.prepare(self.input_dir, self.out, batch_size=2)
        self.client.mode = "missing"
        result = foda.run(self.out, "fixture:1", client=self.client)
        self.assertEqual(result["batches_error"], 1)
        self.assertEqual(result["batches_done"], 0)
        self.client.mode = "invalid-category"
        retried = foda.run(self.out, "fixture:1", retry_errors=True, client=self.client)
        self.assertEqual(retried["batches_error"], 1)
        self.assertEqual(retried["batches_done"], 0)

    def test_response_rejects_unknown_duplicate_and_missing_ids(self):
        expected = {"a", "b"}
        valid = {
            "features": [
                {"id": key, "canonical_name": key, "category": foda.CATEGORIES[0],
                 "needs_review": False, "note": ""}
                for key in expected
            ]
        }
        self.assertEqual(len(foda._decode_response(json.dumps(valid), expected)), 2)
        for features in (
            valid["features"][:-1],
            valid["features"] + [valid["features"][0]],
            [{**valid["features"][0], "id": "unknown"}, valid["features"][1]],
        ):
            with self.assertRaises(ValueError):
                foda._decode_response(json.dumps({"features": features}), expected)


if __name__ == "__main__":
    unittest.main()
