from __future__ import annotations

import argparse
import pathlib
import sys
import time


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT = REPO_ROOT / "models" / "Stable-diffusion" / "pixelArtDiffusionXL_spriteShaper.safetensors"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "models" / "Diffusers" / "pixel_art_diffusion_xl"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a local SDXL .safetensors checkpoint into Diffusers format."
    )
    parser.add_argument(
        "--checkpoint",
        type=pathlib.Path,
        default=DEFAULT_CHECKPOINT,
        help=f"Path to the source checkpoint (default: {DEFAULT_CHECKPOINT})",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write the Diffusers model to (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output directory if it already exists.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Do not download any missing tokenizer/config files from Hugging Face.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    checkpoint_path = args.checkpoint.resolve()
    output_dir = args.output_dir.resolve()

    if not checkpoint_path.exists():
        print(f"[error] checkpoint not found: {checkpoint_path}", file=sys.stderr)
        return 1

    if output_dir.exists():
        if not args.force:
            print(
                f"[error] output directory already exists: {output_dir} (use --force to overwrite)",
                file=sys.stderr,
            )
            return 1
    else:
        output_dir.parent.mkdir(parents=True, exist_ok=True)

    from diffusers import StableDiffusionXLPipeline
    from diffusers.pipelines.stable_diffusion.convert_from_ckpt import (
        download_from_original_stable_diffusion_ckpt,
    )

    try:
        print(f"[convert] building StableDiffusionXLPipeline from {checkpoint_path.name}")
        started = time.perf_counter()
        pipeline = download_from_original_stable_diffusion_ckpt(
            checkpoint_path_or_dict=str(checkpoint_path),
            from_safetensors=checkpoint_path.suffix.lower() == ".safetensors",
            pipeline_class=StableDiffusionXLPipeline,
            load_safety_checker=False,
            local_files_only=args.local_files_only,
        )
        print(f"[convert] pipeline built in {time.perf_counter() - started:.2f}s")

        if output_dir.exists() and args.force:
            for child in output_dir.iterdir():
                if child.is_dir():
                    import shutil

                    shutil.rmtree(child)
                else:
                    child.unlink()

        print(f"[convert] saving Diffusers model to {output_dir}")
        pipeline.save_pretrained(str(output_dir), safe_serialization=True)
        print("[convert] done")
        return 0
    except BaseException as exc:
        print(f"[error] conversion failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())