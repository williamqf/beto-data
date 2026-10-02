import hashlib
import json
import unittest
from datetime import datetime, timezone

from src import update_ipva


class IpvaPipelineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 2, tzinfo=timezone.utc)

    def test_builds_versioned_2026_rules_for_only_mg_sp_pr_and_preserves_other_manifest_branches(self):
        previous = {"schemaVersion": 1, "datasetVersion": "fuel-x", "vehicleEfficiency": {"datasetVersion": "pbe-x"}}
        files = {"datasets/fuel/old/BR.json": b"old fuel"}
        built = update_ipva.build_files(previous, files, self.now)
        manifest = json.loads(built["manifest.json"])
        self.assertEqual({"MG", "SP", "PR"}, set(manifest["ipva"]["years"]["2026"]))
        self.assertEqual("pbe-x", manifest["vehicleEfficiency"]["datasetVersion"])
        self.assertEqual("fuel-x", manifest["datasetVersion"])
        for uf, entry in manifest["ipva"]["years"]["2026"].items():
            body = built[entry["path"]]
            self.assertEqual(entry["sha256"], hashlib.sha256(body).hexdigest())
            dataset = json.loads(body)
            self.assertEqual((uf, 2026, 1), (dataset["uf"], dataset["year"], dataset["schemaVersion"]))
            self.assertTrue(dataset["sourceUrl"].startswith("https://"))

    def test_validation_blocks_changed_official_source_markers(self):
        config = update_ipva.RULES
        responses = {}
        for row in config.values():
            responses[row["sourceUrl"]] = " ".join(row["markers"])
            if row.get("baseMarkers"):
                responses[row["baseSourceUrl"]] = " ".join(row["baseMarkers"])
        update_ipva.validate_sources(lambda url: responses[url])
        mg_url = config["MG"]["sourceUrl"]
        responses[mg_url] = "conteúdo sem confirmação"
        with self.assertRaisesRegex(ValueError, "Fonte MG mudou"):
            update_ipva.validate_sources(lambda url: responses[url])

    def test_no_supported_uf_is_added_implicitly(self):
        built = update_ipva.build_files({}, {}, self.now)
        manifest = json.loads(built["manifest.json"])
        self.assertNotIn("RJ", manifest["ipva"]["years"]["2026"])
        self.assertNotIn("SC", manifest["ipva"]["years"]["2026"])


if __name__ == "__main__":
    unittest.main()
