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


class VllmResponse:
    status_code = 200

    def __init__(self, prefill: int, generated: int, model: str = "chat") -> None:
        self.text = (
            f'vllm:prompt_tokens_total{{engine="0",model_name="{model}"}} {prefill}\n'
            f'vllm:generation_tokens_total{{engine="0",model_name="{model}"}} {generated}\n'
        )


class PlainResponse:
    status_code = 200
    text = "some_unrelated_metric 1\n"


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


class AutoBackendTests(unittest.TestCase):
    def run_module(
        self,
        module: ModuleType,
        argv: list[str],
        cache_file: Path,
        responses: list[object],
        times: list[float],
    ) -> tuple[list[dict], object]:
        output: list[dict] = []
        with (
            patch.object(module, "CACHE_FILE", cache_file),
            patch.object(module, "load_env", return_value={}),
            patch.object(module.requests, "get", side_effect=responses) as get,
            patch.object(module.time, "time", side_effect=times),
            patch.object(sys, "argv", argv),
        ):
            for _ in times:
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    module.main()
                output.append(json.loads(stdout.getvalue()))
        return output, get

    def test_auto_preserves_baseline_for_same_backend(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://127.0.0.1:8000/metrics",
            "--backend",
            "auto",
        ]
        responses = [MetricsResponse(1000, 2000), MetricsResponse(1080, 2030)]

        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "cache.json"
            output, get = self.run_module(
                module, argv, cache_file, responses, [100.0, 102.0]
            )

            self.assertEqual(get.call_count, 2)
            self.assertIn("warming up", output[0]["text"])
            self.assertIn("flare @ http://127.0.0.1:8000/metrics", output[0]["tooltip"])
            self.assertEqual(
                output[1]["text"],
                '<span color="#89b4fa">AI</span> <span color="#fab387">P 00040</span> <span color="#a6e3a1">D 015</span>',
            )
            self.assertIn("Backend: flare", output[1]["tooltip"])
            cache = json.loads(cache_file.read_text())
            self.assertEqual(cache["backend"], "flare")
            self.assertEqual(cache["url"], "http://127.0.0.1:8000/metrics")

    def test_auto_redetects_when_url_changes(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://127.0.0.1:9000/metrics",
            "--backend",
            "auto",
            "--model",
            "chat",
        ]

        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "decode": 2000,
                        "prefill": 1000,
                        "time": 99.0,
                        "backend": "flare",
                        "url": "http://127.0.0.1:8000/metrics",
                    }
                )
            )
            output, get = self.run_module(
                module, argv, cache_file, [VllmResponse(500, 700)], [100.0]
            )

            self.assertEqual(get.call_count, 1)
            self.assertIn("warming up", output[0]["text"])
            self.assertIn("vllm @ http://127.0.0.1:9000/metrics", output[0]["tooltip"])
            cache = json.loads(cache_file.read_text())
            self.assertEqual(cache["backend"], "vllm")
            self.assertEqual(cache["url"], "http://127.0.0.1:9000/metrics")

    def test_explicit_backend_resets_baseline_when_url_changes(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://127.0.0.1:9000/metrics",
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
                        "backend": "flare",
                        "url": "http://127.0.0.1:8000/metrics",
                    }
                )
            )
            output, get = self.run_module(
                module, argv, cache_file, [MetricsResponse(5000, 9000)], [100.0]
            )

            self.assertEqual(get.call_count, 1)
            self.assertIn("warming up", output[0]["text"])
            self.assertIn("flare @ http://127.0.0.1:9000/metrics", output[0]["tooltip"])
            cache = json.loads(cache_file.read_text())
            self.assertEqual(cache["decode"], 9000)
            self.assertEqual(cache["prefill"], 5000)
            self.assertEqual(cache["url"], "http://127.0.0.1:9000/metrics")

    def test_auto_reports_unrecognized_metrics(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://127.0.0.1:8000/metrics",
            "--backend",
            "auto",
        ]

        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "cache.json"
            output, get = self.run_module(
                module, argv, cache_file, [PlainResponse()], [100.0]
            )

            self.assertEqual(get.call_count, 1)
            self.assertEqual(output[0]["class"], "critical")
            self.assertIn("AI config", output[0]["text"])
            self.assertIn("Could not detect backend", output[0]["tooltip"])
            self.assertFalse(cache_file.exists())

    def test_auto_switches_backends_without_model_configuration(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://localhost/metrics",
            "--backend",
            "auto",
        ]
        responses = [
            MetricsResponse(100, 10),
            VllmResponse(1000, 100),
            VllmResponse(1200, 140),
            MetricsResponse(200, 30),
            MetricsResponse(260, 50),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output, _ = self.run_module(
                module,
                argv,
                Path(directory) / "cache.json",
                responses,
                [1.0, 3.0, 5.0, 7.0, 9.0],
            )
        self.assertIn("warming up", output[1]["text"])
        self.assertIn("Prefill: 100.0 tokens/s", output[2]["tooltip"])
        self.assertIn("Decode:  20.0 tokens/s", output[2]["tooltip"])
        self.assertIn("Model:   chat", output[2]["tooltip"])
        self.assertIn("warming up", output[3]["text"])
        self.assertIn("Decode:  10.0 tokens/s", output[4]["tooltip"])
        self.assertIn("Backend: flare", output[4]["tooltip"])

    def test_auto_model_change_resets_baseline(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://localhost/metrics",
            "--backend",
            "auto",
        ]
        with tempfile.TemporaryDirectory() as directory:
            output, _ = self.run_module(
                module,
                argv,
                Path(directory) / "cache.json",
                [
                    VllmResponse(1000, 100),
                    VllmResponse(5000, 500, "other"),
                    VllmResponse(5100, 530, "other"),
                ],
                [1.0, 3.0, 5.0],
            )
        self.assertIn("warming up", output[1]["text"])
        self.assertIn("Decode:  15.0 tokens/s", output[2]["tooltip"])
        self.assertIn("Model:   other", output[2]["tooltip"])

    def test_multiple_models_require_explicit_selection(self) -> None:
        module = load_module()
        argv = [
            str(MODULE_PATH),
            "--url",
            "http://localhost/metrics",
            "--backend",
            "auto",
        ]
        first = VllmResponse(1000, 100)
        first.text += VllmResponse(5000, 500, "other").text
        second = VllmResponse(1200, 140)
        second.text += VllmResponse(9000, 900, "other").text
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            output, _ = self.run_module(module, argv, cache, [first], [1.0])
            self.assertEqual(output[0]["class"], "critical")
            self.assertFalse(cache.exists())
            output, _ = self.run_module(
                module, [*argv, "--model", "chat"], cache, [first, second], [3.0, 5.0]
            )
        self.assertIn("warming up", output[0]["text"])
        self.assertIn("Decode:  20.0 tokens/s", output[1]["tooltip"])

    def test_detect_backend_identifies_each_flavor(self) -> None:
        module = load_module()
        cases = {
            "flare": "flare_prefill_tokens_total 1\nflare_generated_tokens_total 2\n",
            "vllm": 'vllm:prompt_tokens_total{engine="0",model_name="chat"} 1\n',
            "sglang": 'sglang:realtime_tokens_total{mode="decode"} 1\n',
        }
        for expected, text in cases.items():
            with self.subTest(expected):
                self.assertEqual(
                    module.detect_backend(module.parse_metrics(text)), expected
                )
        self.assertIsNone(module.detect_backend(module.parse_metrics("x 1\n")))


if __name__ == "__main__":
    unittest.main()
