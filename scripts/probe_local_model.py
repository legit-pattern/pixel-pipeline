from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys
from typing import Any


def _probe_single_file(path: pathlib.Path) -> dict[str, Any]:
    probe_code = (
        "import json, pathlib, sys\n"
        "from safetensors import safe_open\n"
        "path = pathlib.Path(sys.argv[1])\n"
        "with safe_open(str(path), framework='np') as handle:\n"
        "    key = next(iter(handle.keys()))\n"
        "    tensor = handle.get_tensor(key)\n"
        "    print(json.dumps({'first_key': key, 'shape': list(tensor.shape), 'dtype': str(tensor.dtype)}))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe_code, str(path)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "kind": "single_file", "path": str(path), "reason": "probe timed out"}
    except Exception as exc:
        return {"ok": False, "kind": "single_file", "path": str(path), "reason": f"probe failed: {exc}"}

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        return {"ok": False, "kind": "single_file", "path": str(path), "reason": detail}

    payload = json.loads(completed.stdout)
    return {"ok": True, "kind": "single_file", "path": str(path), "details": payload}


def _probe_diffusers_dir(path: pathlib.Path) -> dict[str, Any]:
    required_paths = [
        path / "model_index.json",
        path / "unet" / "config.json",
        path / "vae" / "config.json",
    ]
    missing = [str(item) for item in required_paths if not item.exists()]
    if missing:
        return {
            "ok": False,
            "kind": "diffusers",
            "path": str(path),
            "reason": "missing required files",
            "missing": missing,
        }

    weight_candidates = [
        path / "unet" / "diffusion_pytorch_model.safetensors",
        path / "unet" / "diffusion_pytorch_model.bin",
        path / "vae" / "diffusion_pytorch_model.safetensors",
        path / "vae" / "diffusion_pytorch_model.bin",
    ]
    present_weights = [str(item) for item in weight_candidates if item.exists()]
    if len(present_weights) < 2:
        return {
            "ok": False,
            "kind": "diffusers",
            "path": str(path),
            "reason": "missing core weight files",
            "present_weights": present_weights,
        }

    return {
        "ok": True,
        "kind": "diffusers",
        "path": str(path),
        "details": {"present_weights": present_weights},
    }


def _peek_header(path: pathlib.Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(160)
        header_len = struct.unpack("<Q", raw[:8])[0]
        return {
            "size_bytes": path.stat().st_size,
            "header_len": header_len,
            "header_preview": raw[8:160].decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe a local checkpoint or Diffusers model directory.")
    parser.add_argument("path", help="Path to a .safetensors/.ckpt file or Diffusers model directory")
    args = parser.parse_args(argv)

    path = pathlib.Path(args.path).resolve()
    if not path.exists():
        print(json.dumps({"ok": False, "path": str(path), "reason": "path does not exist"}, indent=2))
        return 1

    if path.is_dir():
        result = _probe_diffusers_dir(path)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    suffix = path.suffix.lower()
    if suffix not in {".safetensors", ".ckpt", ".pt", ".pth"}:
        print(json.dumps({"ok": False, "path": str(path), "reason": f"unsupported suffix: {suffix}"}, indent=2))
        return 1

    result = _probe_single_file(path)
    if not result.get("ok"):
        result["header"] = _peek_header(path)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())