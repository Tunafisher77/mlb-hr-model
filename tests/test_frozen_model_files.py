import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrozenModelFilesTest(unittest.TestCase):
    def test_production_model_files_are_unchanged(self):
        manifest = json.loads((ROOT / "FROZEN_MODEL_BASELINE.json").read_text())
        for relative_path, expected_hash in manifest["files"].items():
            actual_hash = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
            self.assertEqual(
                expected_hash,
                actual_hash,
                f"Frozen production file changed: {relative_path}",
            )


if __name__ == "__main__":
    unittest.main()
