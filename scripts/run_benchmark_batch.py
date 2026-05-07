from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = REPO_ROOT / "asset-roadmap" / "benchmark-results"


def _raise_for_status_with_detail(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text.strip()
        try:
            payload = response.json()
            detail = json.dumps(payload, ensure_ascii=False)
        except Exception:
            pass
        if detail:
            raise requests.HTTPError(f"{exc} | response={detail}", response=response) from exc
        raise


def _load_manifest(path: pathlib.Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Manifest root must be an object")
    if not isinstance(payload.get("jobs"), list) or not payload["jobs"]:
        raise ValueError("Manifest must contain a non-empty jobs array")
    return payload


def _encode_png_file(path_value: str) -> str:
    path = pathlib.Path(path_value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    raw = path.read_bytes()
    return base64.b64encode(raw).decode("ascii")


def _submit_job(api_base: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{api_base}/api/pixel/jobs/generate", json=request_payload, timeout=60)
    _raise_for_status_with_detail(response)
    return response.json()


def _fetch_model_catalog(api_base: str) -> dict[str, Any]:
    response = requests.get(f"{api_base}/api/pixel/models", timeout=60)
    _raise_for_status_with_detail(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Model catalog response must be an object")
    return payload


def _preflight_manifest(api_base: str, manifest: dict[str, Any]) -> None:
    catalog = _fetch_model_catalog(api_base)
    available_models = catalog.get("models") or []
    unavailable_models = catalog.get("unavailable_models") or []
    available_ids = {
        item.get("id")
        for item in available_models
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    if not available_ids:
        reasons: list[str] = []
        for item in unavailable_models:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("id") or "unknown")
            reason = str(item.get("reason") or "Unavailable")
            reasons.append(f"{label}: {reason}")
        message = "No runnable models are available from /api/pixel/models"
        if reasons:
            message = f"{message}. " + " | ".join(reasons)
        raise RuntimeError(message)

    missing_requests: list[str] = []
    for job in manifest.get("jobs", []):
        if not isinstance(job, dict):
            continue
        request_payload = dict(job.get("request") or {})
        requested_model = str(request_payload.get("model_family") or "").strip()
        if requested_model and requested_model not in available_ids:
            reason = "not listed as runnable"
            for item in unavailable_models:
                if isinstance(item, dict) and item.get("id") == requested_model:
                    reason = str(item.get("reason") or reason)
                    break
            missing_requests.append(f"{requested_model}: {reason}")
    if missing_requests:
        raise RuntimeError("Manifest requests unavailable model families: " + " | ".join(missing_requests))


def _poll_job(api_base: str, job_id: str, poll_interval_s: float, timeout_s: float) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while True:
        response = requests.get(f"{api_base}/api/pixel/jobs/{job_id}", timeout=60)
        _raise_for_status_with_detail(response)
        payload = response.json()
        status = payload.get("status")
        if status in {"success", "failure", "cancelled"}:
            return payload
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for job {job_id}")
        time.sleep(poll_interval_s)


def _normalize_request(job: dict[str, Any]) -> dict[str, Any]:
    request_payload = dict(job.get("request") or {})
    source_image_path = str(job.get("source_image_path") or "").strip()
    if source_image_path:
        request_payload["source_image_base64"] = _encode_png_file(source_image_path)
    return request_payload


def run_manifest(
    manifest_path: pathlib.Path,
    api_base: str,
    wait: bool,
    poll_interval_s: float,
    timeout_s: float,
) -> pathlib.Path:
    manifest = _load_manifest(manifest_path)
    _preflight_manifest(api_base, manifest)
    results: list[dict[str, Any]] = []

    for index, job in enumerate(manifest["jobs"], start=1):
        if not isinstance(job, dict):
            raise ValueError(f"Job entry at index {index - 1} must be an object")
        label = str(job.get("label") or f"job_{index}")
        request_payload = _normalize_request(job)
        submit_payload = _submit_job(api_base, request_payload)
        result_entry: dict[str, Any] = {
            "label": label,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "request": request_payload,
            "submit": submit_payload,
        }
        if wait:
            final_payload = _poll_job(api_base, submit_payload["job_id"], poll_interval_s, timeout_s)
            result_entry["final"] = final_payload
        results.append(result_entry)
        print(f"[{index}/{len(manifest['jobs'])}] submitted {label}: {submit_payload['job_id']}")

    DEFAULT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = DEFAULT_RESULTS_DIR / f"{manifest_path.stem}-{timestamp}.json"
    output_payload = {
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "api_base": api_base,
        "wait": wait,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    output_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
    print(f"Saved benchmark results to {output_path}")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a benchmark batch manifest against the local Pixel Pipeline backend.")
    parser.add_argument("manifest", help="Path to a benchmark manifest JSON file")
    parser.add_argument("--api-base", default="http://127.0.0.1:7860", help="Backend base URL")
    parser.add_argument("--wait", action="store_true", help="Poll jobs until they reach a terminal state")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds when --wait is used")
    parser.add_argument("--timeout", type=float, default=900.0, help="Per-job timeout in seconds when --wait is used")
    args = parser.parse_args(argv)

    manifest_path = pathlib.Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = REPO_ROOT / manifest_path

    run_manifest(
        manifest_path=manifest_path,
        api_base=args.api_base.rstrip("/"),
        wait=args.wait,
        poll_interval_s=args.poll_interval,
        timeout_s=args.timeout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())