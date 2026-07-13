#!/usr/bin/env python3
# /// script
# dependencies = ["requests"]
# ///

"""Waybar custom module for AI inference throughput (prefill/decode t/s).

Supports sglang and vllm backends.

Configuration (in priority order):
  1. CLI flags: --url, --backend, --model
  2. Environment variables: AI_THROUGHPUT_URL, AI_THROUGHPUT_BACKEND,
     AI_THROUGHPUT_MODEL
  3. .env file in the script directory (legacy)

Usage:
  aithroughput.py --url http://host:port/metrics --backend vllm --model chat
"""

import argparse
import json
import os
import time
from pathlib import Path
from xml.sax.saxutils import escape

import requests

SCRIPT_DIR = Path(__file__).parent
ENV_FILE = SCRIPT_DIR / ".env"
CACHE_FILE = Path("/tmp/aithroughput_cache.json")


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


def fetch_vllm(url: str, model: str, prev: dict | None, now: float) -> dict | None:
    """Fetch vllm metrics and compute throughput."""
    try:
        resp = requests.get(url, timeout=2)
        if resp.status_code != 200:
            return None

        metrics = {}
        for line in resp.text.splitlines():
            if line.startswith("#") or not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    metrics[parts[0]] = float(parts[1])
                except ValueError:
                    pass

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
    except Exception:
        return None


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


def fetch_sglang(url: str, prev: dict | None, now: float) -> dict | None:
    """Fetch sglang metrics and compute throughput."""
    try:
        resp = requests.get(url, timeout=2)
        if resp.status_code != 200:
            return None

        metrics = {}
        for line in resp.text.splitlines():
            if line.startswith("#") or not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    metrics[parts[0]] = float(parts[1])
                except ValueError:
                    pass

        decode_tokens = 0.0
        prefill_tokens = 0.0
        for key, value in metrics.items():
            if 'realtime_tokens_total' in key and 'mode="decode"' in key:
                decode_tokens = value
            elif 'realtime_tokens_total' in key and 'mode="prefill_compute"' in key:
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
            gauge_metric = 'sglang:gen_throughput{engine_type="unified",model_name="chat"}'
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
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="AI inference throughput module")
    parser.add_argument("--url", help="Metrics endpoint URL")
    parser.add_argument("--backend", choices=["sglang", "vllm"], help="Backend type")
    parser.add_argument("--model", help="Model name (required for vllm backend)")
    args = parser.parse_args()

    env = load_env()

    url = args.url or read_setting(env, "AI_THROUGHPUT_URL")
    backend = args.backend or read_setting(env, "AI_THROUGHPUT_BACKEND")
    model = args.model or read_setting(env, "AI_THROUGHPUT_MODEL")

    if not url or not backend:
        print(json.dumps({
            "text": "<span color=\"#f38ba8\">AI config</span>",
            "class": "critical",
            "tooltip": "Pass --url and --backend flags, or set AI_THROUGHPUT_URL and AI_THROUGHPUT_BACKEND",
        }))
        return

    if backend == "vllm" and not model:
        print(json.dumps({
            "text": "<span color=\"#f38ba8\">AI config</span>",
            "class": "critical",
            "tooltip": "Pass --model or set AI_THROUGHPUT_MODEL for vllm backend",
        }))
        return

    now = time.time()
    prev = load_cache()

    try:
        if prev is None:
            # First run: fetch raw counters, save baseline, show warmup
            resp = requests.get(url, timeout=2)
            if resp.status_code != 200:
                raise RuntimeError("non-200 on first fetch")
            raw_metrics = {}
            for line in resp.text.splitlines():
                if line.startswith("#") or not line:
                    continue
                parts = line.rsplit(" ", 1)
                if len(parts) == 2:
                    try:
                        raw_metrics[parts[0]] = float(parts[1])
                    except ValueError:
                        pass

            if backend == "vllm":
                gen_metric = f'vllm:generation_tokens_total{{engine="0",model_name="{model}"}}'
                prompt_metric = f'vllm:prompt_tokens_total{{engine="0",model_name="{model}"}}'
                raw_decode = raw_metrics.get(gen_metric, 0.0)
                raw_prefill = raw_metrics.get(prompt_metric, 0.0)
            elif backend == "sglang":
                raw_decode = 0.0
                raw_prefill = 0.0
                for key, value in raw_metrics.items():
                    if 'realtime_tokens_total' in key and 'mode="decode"' in key:
                        raw_decode = value
                    elif 'realtime_tokens_total' in key and 'mode="prefill_compute"' in key:
                        raw_prefill = value
            else:
                raise RuntimeError(f"Unknown backend: {backend}")

            save_cache({"decode": raw_decode, "prefill": raw_prefill, "time": now})
            print(json.dumps({
                "text": "<span color=\"#89b4fa\">AI</span> <span color=\"#6c7086\">warming up</span>",
                "class": "idle",
                "tooltip": f"Collecting first sample...\n{backend} @ {url}",
            }))
            return

        # Subsequent runs: delegate to backend-specific fetcher
        if backend == "vllm":
            result = fetch_vllm(url, model, prev, now)
        elif backend == "sglang":
            result = fetch_sglang(url, prev, now)
        else:
            raise RuntimeError(f"Unknown backend: {backend}")

        if result is None:
            raise RuntimeError(f"{backend} fetch returned None")

        save_cache({
            "decode": result.get("raw_decode", result["decode"]),
            "prefill": result.get("raw_prefill", result["prefill"]),
            "time": now,
        })

    except Exception as exc:
        if prev is not None:
            print(json.dumps({
                "text": "<span color=\"#f38ba8\">AI offline</span>",
                "class": "critical",
                "tooltip": escape(str(exc)),
            }))
        else:
            print(json.dumps({
                "text": "<span color=\"#89b4fa\">AI</span> <span color=\"#6c7086\">warming up</span>",
                "class": "idle",
                "tooltip": escape(str(exc)),
            }))
        return

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

    print(json.dumps({
        "text": text,
        "tooltip": (
            f"AI Throughput\n"
            f"Prefill: {prefill:.1f} tokens/s\n"
            f"Decode:  {decode:.1f} tokens/s\n"
            f"Backend: {backend}\n"
            f"Model:   {model}"
        ),
        "class": color_class,
    }))


if __name__ == "__main__":
    main()
