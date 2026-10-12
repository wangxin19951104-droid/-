"""Local configuration and ComfyUI result retrieval; no provider requests."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import api_keys
import banana_client
import bootstrap

class PortabilityTests(unittest.TestCase):
    def test_bootstrap_resolves_cache_and_never_replaces_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.example.json").write_text('{"cache_root":"","model":"gpt-6.1-sol"}', encoding="utf-8")
            with patch.object(bootstrap, "ROOT", root):
                bootstrap.main()
                target = root / "config.json"
                first = target.read_bytes()
                self.assertEqual(json.loads(first)["cache_root"], str((root / "cache").resolve()))
                bootstrap.main()
                self.assertEqual(target.read_bytes(), first)

    def test_environment_credentials_take_priority_over_local_secret_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            (root / "secrets.json").write_text('{"JUNFLOW_API_KEY":"fixture-file"}', encoding="utf-8")
            with patch.object(api_keys, "ROOT", root):
                self.assertEqual(api_keys.load_keys()["JUNFLOW_API_KEY"], "fixture-file")
                os.environ["JUNFLOW_API_KEY"] = "fixture-env"
                self.assertEqual(api_keys.load_keys()["JUNFLOW_API_KEY"], "fixture-env")
                with self.assertRaises(RuntimeError):
                    api_keys.require("COMFY_API_KEY")

    def test_image_client_uses_main_comfy_address(self):
        config = {"comfy_url": "http://fixture.test:8199/"}
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=json.dumps(config)):
            self.assertEqual(banana_client._local_base(), "http://fixture.test:8199")
            os.environ["JIJI_COMFY_URL"] = "http://override.test/"
            self.assertEqual(banana_client._local_base(), "http://override.test")

    def test_output_download_uses_metadata_and_preserves_bytes(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b"fixture-image-bytes"
        hist = {"outputs": {"2": {"images": [{"filename": "图 1.png", "subfolder": "project/a", "type": "output"}]}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(banana_client, "_local_base", return_value="http://fixture.test"), patch.object(banana_client.urllib.request, "urlopen", return_value=Response()) as request:
            dest = Path(tmp) / "nested" / "result.png"
            self.assertEqual(banana_client._copy_local_output(hist, dest), dest)
            self.assertEqual(dest.read_bytes(), b"fixture-image-bytes")
            url = urlsplit(request.call_args.args[0])
            self.assertEqual(url.path, "/view")
            self.assertEqual(parse_qs(url.query)["filename"], ["图 1.png"])
            self.assertEqual(parse_qs(url.query)["subfolder"], ["project/a"])
