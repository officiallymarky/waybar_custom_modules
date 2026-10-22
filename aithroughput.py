#!/usr/bin/env python3
# /// script
# dependencies = ["requests"]
# ///

"""Waybar custom module for AI inference throughput (prefill/decode t/s).

Supports vllm, sglang and Flare backends. With --backend auto the backend is
detected from every /metrics response. Backend or vllm model changes establish
a fresh counter baseline. If --model is omitted, vllm uses the sole advertised
model; multiple models require explicit selection.

Configuration (in priority order):
  1. CLI flags: --url, --backend, --model
  2. Environment variables: AI_THROUGHPUT_URL, AI_THROUGHPUT_BACKEND,
     AI_THROUGHPUT_MODEL
  3. .env file in the script directory (legacy)

Usage:
  aithroughput.py --url http://host:port/metrics --backend auto
"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from xml.sax.saxutils import escape

import requests

SCRIPT_DIR = Path(__file__).parent
ENV_FILE = SCRIPT_DIR / ".env"
CACHE_FILE = Path("/tmp/aithroughput_cache.json")

BACKENDS = ("vllm", "sglang", "flare")


def format_rate(value: float, width: int) -> str:
    return f"{value:0{width}.0f}"


def load_env() -> dict:
    """Load environment variables from .env file in the script directory."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def parse_metrics(text: str) -> dict[str, float]:
    """Parse Prometheus text exposition into metric name -> value."""
    metrics = {}
    for line in text.splitlines():
        if line.startswith("#") or not line:
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) == 2:
            try:
                metrics[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return metrics


def fetch_metrics(url: str) -> dict[str, float]:
    resp = requests.get(url, timeout=2)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")
    return parse_metrics(resp.text)


def detect_backend(metrics: dict[str, float]) -> str | None:
    """Identify the backend from its metric names."""
    if any(name.startswith("flare_") for name in metrics):
        return "flare"
    if any(name.startswith("vllm:") for name in metrics):
        return "vllm"
    if any(name.startswith("sglang:") for name in metrics) or any(
        "realtime_tokens_total" in name for name in metrics
    ):
        return "sglang"
    return None


def baseline_counters(
    metrics: dict[str, float], backend: str, model: str
) -> tuple[float, float]:
    """Return (prefill, decode) counter totals for the first sample."""
    if backend == "vllm":
        gen_metric = f'vllm:generation_tokens_total{{engine="0",model_name="{model}"}}'
        prompt_metric = f'vllm:prompt_tokens_total{{engine="0",model_name="{model}"}}'
        return metrics.get(prompt_metric, 0.0), metrics.get(gen_metric, 0.0)
    if backend == "sglang":
        decode = 0.0
        prefill = 0.0
        for key, value in metrics.items():
            if "realtime_tokens_total" in key and 'mode="decode"' in key:
                decode = value
            elif "realtime_tokens_total" in key and 'mode="prefill_compute"' in key:
                prefill = value
        return prefill, decode
    if backend == "flare":
        return (
            metrics.get("flare_prefill_tokens_total", 0.0),
            metrics.get("flare_generated_tokens_total", 0.0),
        )
    raise RuntimeError(f"Unknown backend: {backend}")


def fetch_vllm(
    metrics: dict[str, float], model: str, prev: dict | None, now: float
) -> dict | None:
    """Compute vllm throughput from parsed metrics."""
    gen_metric = f'vllm:generation_tokens_total{{engine="0",model_name="{model}"}}'
    prompt_metric = f'vllm:prompt_tokens_total{{engine="0",model_name="{model}"}}'
    gen_tokens = metrics.get(gen_metric, 0.0)
    prompt_tokens = metrics.get(prompt_metric, 0.0)

    if prev is None:
        return None  # need a baseline

    dt = now - prev["time"]
    if dt <= 0:
        return None

    if prev.get("raw_decode") is not None and prev.get("raw_prefill") is not None:
        decode_delta = gen_tokens - prev["raw_decode"]
        prefill_delta = prompt_tokens - prev["raw_prefill"]
    else:
        decode_delta = gen_tokens - prev["decode"]
        prefill_delta = prompt_tokens - prev["prefill"]

    return {
        "prefill": max(prefill_delta / dt, 0.0),
        "decode": max(decode_delta / dt, 0.0),
        "raw_decode": gen_tokens,
        "raw_prefill": prompt_tokens,
        "time": now,
    }


def load_cache() -> dict | None:
    """Load previous state from cache file."""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            # Validate shape
            if "prefill" in data and "decode" in data and "time" in data:
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_cache(data: dict) -> None:
    """Save current state to cache file."""
    try:
        CACHE_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def read_setting(env: dict, key: str) -> str:
    return os.environ.get(key) or env.get(key, "")


def fetch_sglang(
    metrics: dict[str, float], model: str, prev: dict | None, now: float
) -> dict | None:
    """Compute sglang throughput from parsed metrics."""
    decode_tokens = 0.0
    prefill_tokens = 0.0
    for key, value in metrics.items():
        if "realtime_tokens_total" in key and 'mode="decode"' in key:
            decode_tokens = value
        elif "realtime_tokens_total" in key and 'mode="prefill_compute"' in key:
            prefill_tokens = value

    if prev is None:
        return None  # need a baseline

    dt = now - prev["time"]
    if dt <= 0:
        return None

    decode_value = max((decode_tokens - prev["decode"]) / dt, 0.0)
    prefill_value = max((prefill_tokens - prev["prefill"]) / dt, 0.0)

    # Fallback: try gen_throughput gauge if decode is zero
    if decode_value == 0.0:
        gauge_metric = (
            f'sglang:gen_throughput{{engine_type="unified",model_name="{model}"}}'
        )
        gauge_value = metrics.get(gauge_metric, 0.0)
        if gauge_value > 0:
            decode_value = gauge_value

    return {
        "prefill": prefill_value,
        "decode": decode_value,
        "raw_decode": decode_tokens,
        "raw_prefill": prefill_tokens,
        "time": now,
    }


def fetch_flare(
    metrics: dict[str, float], prev: dict | None, now: float
) -> dict | None:
    """Compute Flare throughput from parsed metrics."""
    decode_tokens = metrics.get("flare_generated_tokens_total", 0.0)
    prefill_tokens = metrics.get("flare_prefill_tokens_total", 0.0)

    if prev is None:
        return None

    dt = now - prev["time"]
    if dt <= 0:
        return None

    return {
        "prefill": max((prefill_tokens - prev["prefill"]) / dt, 0.0),
        "decode": max((decode_tokens - prev["decode"]) / dt, 0.0),
        "raw_decode": decode_tokens,
        "raw_prefill": prefill_tokens,
        "time": now,
    }


def emit_unavailable(exc: Exception, prev: dict | None) -> None:
    """Render an offline state, or warming up when there is no baseline."""
    tooltip = escape(str(exc))
    if prev is not None:
        print(
            json.dumps(
                {
                    "text": '<span color="#f38ba8">AI offline</span>',
                    "class": "critical",
                    "tooltip": tooltip,
                }
            )
        )
    else:
        print(
            json.dumps(
                {
                    "text": '<span color="#89b4fa">AI</span> <span color="#6c7086">warming up</span>',
                    "class": "idle",
                    "tooltip": tooltip,
                }
            )
        )


def try_fetch(url: str, prev: dict | None) -> dict[str, float] | None:
    """Fetch metrics, rendering the failure state instead of raising."""
    try:
        return fetch_metrics(url)
    except (requests.RequestException, RuntimeError) as exc:
        emit_unavailable(exc, prev)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="AI inference throughput module")
    parser.add_argument("--url", help="Metrics endpoint URL")
    parser.add_argument(
        "--backend",
        choices=[*BACKENDS, "auto"],
        help="Backend type (auto detects it from each /metrics response)",
    )
    parser.add_argument("--model", help="Model name (inferred for single-model vllm)")
    args = parser.parse_args()

    env = load_env()

    url = args.url or read_setting(env, "AI_THROUGHPUT_URL")
    backend = args.backend or read_setting(env, "AI_THROUGHPUT_BACKEND")
    model = args.model or read_setting(env, "AI_THROUGHPUT_MODEL")

    if not url or not backend:
        print(
            json.dumps(
                {
                    "text": '<span color="#f38ba8">AI config</span>',
                    "class": "critical",
                    "tooltip": "Pass --url and --backend flags, or set AI_THROUGHPUT_URL and AI_THROUGHPUT_BACKEND",
                }
            )
        )
        return

    now = time.time()
    prev = load_cache()
    if prev is not None and prev.get("url") not in (None, url):
        prev = None

    metrics = try_fetch(url, prev)
    if metrics is None:
        return

    if backend == "auto":
        detected = detect_backend(metrics)
        if detected is None:
            print(
                json.dumps(
                    {
                        "text": '<span color="#f38ba8">AI config</span>',
                        "class": "critical",
                        "tooltip": escape(
                            f"Could not detect backend from {url}: "
                            "no vllm, sglang or Flare metrics"
                        ),
                    }
                )
            )
            return
        backend = detected

    if backend not in BACKENDS:
        print(
            json.dumps(
                {
                    "text": '<span color="#f38ba8">AI config</span>',
                    "class": "critical",
                    "tooltip": escape(f"Unknown backend: {backend}"),
                }
            )
        )
        return

    if prev is not None and prev.get("backend") != backend:
        prev = None

    if backend == "vllm":
        if not model:
            models = {
                json.loads(match.group(1))
                for name in metrics
                if name.startswith(
                    ("vllm:generation_tokens_total{", "vllm:prompt_tokens_total{")
                )
                for match in re.finditer(
                    r'(?:\{|,)model_name=("(?:\\.|[^"\\])*")', name
                )
            }
            if len(models) != 1:
                print(
                    json.dumps(
                        {
                            "text": '<span color="#f38ba8">AI config</span>',
                            "class": "critical",
                            "tooltip": "Cannot infer a unique vllm model; pass --model "
                            "or set AI_THROUGHPUT_MODEL",
                        }
                    )
                )
                return
            model = models.pop()
        if prev is not None and prev.get("model") != model:
            prev = None

    if prev is None:
        # First run: save raw counters as the baseline, show warmup

        raw_prefill, raw_decode = baseline_counters(metrics, backend, model)
        save_cache(
            {
                "decode": raw_decode,
                "prefill": raw_prefill,
                "time": now,
                "backend": backend,
                "url": url,
                "model": model,
            }
        )
        print(
            json.dumps(
                {
                    "text": '<span color="#89b4fa">AI</span> <span color="#6c7086">warming up</span>',
                    "class": "idle",
                    "tooltip": f"Collecting first sample...\n{backend} @ {url}",
                }
            )
        )
        return

    # Subsequent runs: compute rates from the fetched metrics

    if backend == "vllm":
        result = fetch_vllm(metrics, model, prev, now)
    elif backend == "sglang":
        result = fetch_sglang(metrics, model, prev, now)
    elif backend == "flare":
        result = fetch_flare(metrics, prev, now)
    else:
        result = None

    if result is None:
        emit_unavailable(RuntimeError(f"{backend} fetch returned no sample"), prev)
        return

    save_cache(
        {
            "decode": result.get("raw_decode", result["decode"]),
            "prefill": result.get("raw_prefill", result["prefill"]),
            "time": now,
            "backend": backend,
            "url": url,
            "model": model,
        }
    )

    prefill = result["prefill"]
    decode = result["decode"]

    color_class = "good"
    is_idle = decode <= 0.0 and prefill <= 0.0
    if is_idle:
        color_class = "idle"

    text = (
        '<span color="#89b4fa">AI</span> '
        f'<span color="#fab387">P {format_rate(prefill, 5)}</span> '
        f'<span color="#a6e3a1">D {format_rate(decode, 3)}</span>'
    )
    tooltip_lines = [
        "AI Throughput",
        f"Prefill: {prefill:.1f} tokens/s",
        f"Decode:  {decode:.1f} tokens/s",
        f"Backend: {backend}",
    ]
    if model:
        tooltip_lines.append(f"Model:   {model}")

    print(
        json.dumps(
            {
                "text": text,
                "tooltip": "\n".join(tooltip_lines),
                "class": color_class,
            }
        )
    )


if __name__ == "__main__":
    main()
