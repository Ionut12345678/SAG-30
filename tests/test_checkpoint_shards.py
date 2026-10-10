import gzip
import tempfile
import unittest
from pathlib import Path
from radar.checkpoint_shards import pack, unpack

class CheckpointShardsTest(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.gz"
            source.write_bytes(gzip.compress(b"sqlite checkpoint" * 100))
            manifest = pack(source, root / "parts", chunk_bytes=15)
            self.assertGreater(len(manifest["chunks"]), 1)
            dest = root / "restored.gz"
            unpack(root / "parts", dest)
            self.assertEqual(source.read_bytes(), dest.read_bytes())

    def test_missing_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.gz"
            source.write_bytes(gzip.compress(b"checkpoint"))
            pack(source, root / "parts", chunk_bytes=4)
            (root / "parts" / "checkpoint.part-00000").unlink()
            with self.assertRaises(ValueError):
                unpack(root / "parts", root / "restored.gz")
            self.assertFalse((root / "restored.gz").exists())
