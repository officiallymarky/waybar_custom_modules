from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "aithroughput.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aithroughput", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load aithroughput module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetricsResponse:
    status_code = 200

    def __init__(self, prefill: int, generated: int) -> None:
        self.text = (
            f"flare_prefill_tokens_total {prefill}\n"
            f"flare_generated_tokens_total {generated}\n"
        )


class FlareCliTests(unittest.TestCase):
    def test_cli_reports_flare_prefill_and_decode_rates(self) -> None:
        module = load_module()
        responses = [MetricsResponse(1000, 2000), MetricsResponse(1080, 2030)]
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://127.0.0.1:8000/metrics",
            "--backend",
            "flare",
        ]

        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "decode": 2000,
                        "prefill": 1000,
                        "time": 99.0,
                        "backend": "vllm",
                    }
                )
            )
            output = []
            with (
                patch.object(module, "CACHE_FILE", cache_file),
                patch.object(module, "load_env", return_value={}),
                patch.object(module.requests, "get", side_effect=responses),
                patch.object(module.time, "time", side_effect=[100.0, 102.0]),
                patch.object(sys, "argv", argv),
            ):
                for _ in range(2):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                        module.main()
                    output.append(json.loads(stdout.getvalue()))

        self.assertIn("warming up", output[0]["text"])
        self.assertEqual(
            output[1]["text"],
            '<span color="#89b4fa">AI</span> <span color="#fab387">P 00040</span> <span color="#a6e3a1">D 015</span>',
        )
        self.assertIn("Prefill: 40.0 tokens/s", output[1]["tooltip"])
        self.assertIn("Decode:  15.0 tokens/s", output[1]["tooltip"])
        self.assertIn("Backend: flare", output[1]["tooltip"])
        self.assertNotIn("Model:", output[1]["tooltip"])
        self.assertEqual(output[1]["class"], "good")


if __name__ == "__main__":
    unittest.main()
