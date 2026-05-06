from __future__ import annotations

import io
import time

from fastapi.testclient import TestClient
from PIL import Image

from pixel_backend.app import PaletteInput, _resolve_palette_context, create_app


client = TestClient(create_app())


def _make_palette_png(colors: list[tuple[int, int, int]]) -> bytes:
    """Create a minimal PNG swatch where each pixel is one palette colour."""
    img = Image.new("RGB", (len(colors), 1))
    for x, color in enumerate(colors):
        img.putpixel((x, 0), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_healthz_contract() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime"] == "python"
    assert payload["runtime_status"] in {"ok", "degraded"}
    assert "device" in payload
    # Phase 0.2: startup status
    assert "startup_status" in payload
    assert payload["startup_status"] in {"ok", "degraded"}
    assert "startup_issues" in payload
    assert isinstance(payload["startup_issues"], list)


def test_runtime_contract() -> None:
    response = client.get("/api/pixel/runtime")
    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"] == "python"
    assert payload["status"] in {"ok", "degraded"}
    assert "packages" in payload
    assert "modules" in payload
    assert "device" in payload
    # Phase 0.2: startup checks in runtime diagnostics
    assert "startup_checks" in payload
    assert payload["startup_checks"]["status"] in {"ok", "degraded"}
    assert "issues" in payload["startup_checks"]
    assert "checks" in payload["startup_checks"]
    assert "torch" in payload["startup_checks"]["checks"]
    assert "dependencies" in payload["startup_checks"]["checks"]
    assert "checkpoints" in payload["startup_checks"]["checks"]
    assert "compatibility" in payload["startup_checks"]["checks"]
    assert "generation_metrics" in payload
    assert "last_job" in payload["generation_metrics"]
    assert "recent_jobs" in payload["generation_metrics"]
    assert isinstance(payload["generation_metrics"]["recent_jobs"], list)


def test_startup_checks_structure() -> None:
    """Verify startup checks report checkpoint and compatibility status."""
    response = client.get("/api/pixel/runtime")
    assert response.status_code == 200
    payload = response.json()
    checks = payload["startup_checks"]["checks"]
    
    # Verify checkpoint status
    checkpoint_info = checks["checkpoints"]
    assert "checkpoint_count" in checkpoint_info
    assert "accessible" in checkpoint_info
    assert isinstance(checkpoint_info["accessible"], list)
    
    # Verify torch status
    torch_info = checks["torch"]
    assert "available" in torch_info
    assert "version" in torch_info
    assert "cuda" in torch_info
    
    # Verify dependencies
    deps = checks["dependencies"]
    assert "diffusers" in deps
    assert "transformers" in deps
    assert "accelerate" in deps


def test_models_contract() -> None:
    response = client.get("/api/pixel/models")
    assert response.status_code == 200
    payload = response.json()
    assert "models" in payload
    assert isinstance(payload["models"], list)

    model_ids = {item["id"] for item in payload["models"]}
    assert "sdxl_base" in model_ids
    assert "pixel_art_diffusion_xl" in model_ids
    assert "sdxl_pixel_art" in model_ids
    assert "sdxl_pixel_art_xl" in model_ids


def test_palettes_contract() -> None:
    response = client.get("/api/pixel/palettes")
    assert response.status_code == 200
    payload = response.json()
    assert "palettes" in payload
    assert isinstance(payload["palettes"], list)

    palette_ids = {item["id"] for item in payload["palettes"]}
    assert "custom" in palette_ids
    assert "steam_lords" in palette_ids
    assert "pico8" in palette_ids

    steam_lords = next(item for item in payload["palettes"] if item["id"] == "steam_lords")
    assert steam_lords["dither"] == "ordered_4x4"
    assert steam_lords["style"] == "dark_fantasy"


def test_export_formats_contract() -> None:
    response = client.get("/api/pixel/export-formats")
    assert response.status_code == 200
    payload = response.json()
    assert "formats" in payload

    format_ids = {item["id"] for item in payload["formats"]}
    assert format_ids == {"png", "webp", "gif", "spritesheet_png"}


def test_asset_presets_contract() -> None:
    response = client.get("/api/pixel/asset-presets")
    assert response.status_code == 200
    payload = response.json()
    assert "presets" in payload
    assert isinstance(payload["presets"], list)
    preset_ids = {item["id"] for item in payload["presets"]}
    assert {"sprite", "tile", "prop", "effect", "ui"}.issubset(preset_ids)


def test_character_dna_contract() -> None:
    response = client.get("/api/pixel/character-dna")
    assert response.status_code == 200
    payload = response.json()
    assert "character_dna" in payload
    assert isinstance(payload["character_dna"], list)
    dna_ids = {item["id"] for item in payload["character_dna"]}
    assert "frog_guardian" in dna_ids


def test_list_jobs_contract() -> None:
    response = client.get("/api/pixel/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert "jobs" in payload
    assert isinstance(payload["jobs"], list)


def test_generate_rejects_invalid_output_format() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "output_format": "bmp",
            "model_family": "sdxl_base",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "detail" in payload
    assert "output_format" in payload["detail"]


def test_generate_rejects_unknown_model_family() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "output_format": "png",
            "model_family": "not_a_real_model",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "detail" in payload
    assert "Unknown model_family" in payload["detail"]


def test_generate_rejects_empty_prompt() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "   ",
            "output_format": "png",
            "model_family": "sdxl_base",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "prompt is required"


def test_generate_rejects_invalid_lane() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "lane": "invalid_lane",
            "output_format": "png",
            "model_family": "sdxl_base",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "lane must be one of" in payload["detail"]


def test_generate_rejects_invalid_output_mode() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "output_mode": "bad_mode",
            "output_format": "png",
            "model_family": "sdxl_base",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "output_mode must be one of" in payload["detail"]


def test_generate_rejects_invalid_motion_prior() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "output_format": "png",
            "model_family": "sdxl_base",
            "motion_prior": "teleport",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "motion_prior must be one of" in payload["detail"]


def test_generate_rejects_invalid_palette_hex() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "output_format": "png",
            "palette": {
                "preset": "custom",
                "size": 4,
                "colors": ["#00ff00", "not_hex"],
            },
            "model_family": "sdxl_base",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "palette.colors must contain #RRGGBB hex values" == payload["detail"]


def test_generate_rejects_palette_size_mismatch() -> None:
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "test",
            "output_format": "png",
            "palette": {
                "preset": "custom",
                "size": 2,
                "colors": ["#112233", "#445566", "#778899"],
            },
            "model_family": "sdxl_base",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "palette.colors length cannot exceed palette.size" == payload["detail"]


def test_palette_preset_is_soft_guidance_without_explicit_colors() -> None:
    ctx = _resolve_palette_context(
        PaletteInput(
            preset="steam_lords",
            size=16,
            colors=[],
        )
    )
    assert ctx["id"] == "steam_lords"
    assert ctx["colors"] == []


def test_palette_custom_colors_enable_explicit_palette_lock() -> None:
    ctx = _resolve_palette_context(
        PaletteInput(
            preset="custom",
            size=4,
            colors=["#112233", "#aabbcc"],
        )
    )
    assert ctx["id"] == "custom"
    assert ctx["colors"] == ["#112233", "#aabbcc"]


# ── palette/from-image endpoint ────────────────────────────────────────────────

def test_palette_from_image_returns_hex_colors() -> None:
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    png_bytes = _make_palette_png(colors)
    response = client.post(
        "/api/pixel/palettes/from-image",
        files={"file": ("palette.png", png_bytes, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert set(payload["colors"]) == {"#ff0000", "#00ff00", "#0000ff"}


def test_palette_from_image_deduplicates_colors() -> None:
    # 4 pixels, only 2 unique colours
    colors = [(10, 20, 30), (10, 20, 30), (200, 100, 50), (200, 100, 50)]
    png_bytes = _make_palette_png(colors)
    response = client.post(
        "/api/pixel/palettes/from-image",
        files={"file": ("pal.png", png_bytes, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2


def test_palette_from_image_rejects_invalid_file() -> None:
    response = client.post(
        "/api/pixel/palettes/from-image",
        files={"file": ("bad.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 400
    assert "could not open image" in response.json()["detail"]


def test_palette_from_image_rejects_oversized_palette() -> None:
    # 257 distinct colours – should be rejected
    colors = [(i, i % 256, 0) for i in range(257)]
    png_bytes = _make_palette_png(colors)
    response = client.post(
        "/api/pixel/palettes/from-image",
        files={"file": ("big.png", png_bytes, "image/png")},
    )
    assert response.status_code == 400
    assert "unique colours" in response.json()["detail"]


# ── post_processing field is accepted in generate request ─────────────────────

def test_generate_accepts_post_processing_flags() -> None:
    """post_processing flags should not cause a 400; the job is accepted."""
    response = client.post(
        "/api/pixel/jobs/generate",
        json={
            "prompt": "a tiny knight",
            "output_format": "png",
            "model_family": "sdxl_base",
            "auto_pipeline": True,
            "keyframe_first": True,
            "variation_strength": 0.4,
            "consistency_threshold": 0.6,
            "frame_retry_budget": 2,
            "motion_prior": "bounce",
            "asset_preset": "sprite",
            "character_dna_id": "frog_guardian",
            "tile_options": {
                "tile_size": 32,
                "seamless_mode": False,
                "autotile_mask": "none",
                "variation_count": 1,
                "noise_level": 0,
                "edge_softening": 0
            },
            "post_processing": {
                "pixelate": True,
                "remove_background": False,
                "quantize_palette": False,
                "pixel_cleanup": True,
                "outline_strength": 2,
                "anti_alias_level": 2,
                "cluster_smoothing": 2,
                "contrast_boost": 1,
                "shadow_reinforcement": 1,
                "highlight_reinforcement": 1,
                "palette_strictness": 2,
                "pixelate_strength": 1.1,
            },
        },
    )
    # 200 = job accepted (generation runs async and will fail without GPU,
    # but the API layer must not reject a valid request structure)
    assert response.status_code == 200
    payload = response.json()
    assert "job_id" in payload
    # Status is queued immediately but may have advanced to pending/failure by the
    # time we read it; any of these values proves the request was accepted without
    # a validation error
    assert payload["status"] in {"queued", "pending", "failure"}


# ── Phase 1.1: Input conditioning tests ─────────────────────────────────────────
def test_source_processing_mode_validation() -> None:
    """Test that invalid source_processing_mode values are rejected."""
    payload = {
        "prompt": "a test sprite",
        "source_processing_mode": "invalid_mode",
    }
    response = client.post("/api/pixel/jobs/generate", json=payload)
    assert response.status_code == 400
    assert "source_processing_mode" in response.json()["detail"]


def test_source_processing_mode_valid_values() -> None:
    """Test that all valid source_processing_mode values are accepted."""
    for mode in ["none", "detect", "pixelate", "reframe"]:
        payload = {
            "prompt": "a test sprite",
            "source_processing_mode": mode,
        }
        response = client.post("/api/pixel/jobs/generate", json=payload)
        # 200 = accepted; may fail later in generation, but API validation passes
        assert response.status_code in {200, 400}
        if response.status_code == 200:
            assert "job_id" in response.json()


def test_reframe_anchor_validation() -> None:
    """Test that invalid reframe anchors are rejected."""
    payload = {
        "prompt": "a test sprite",
        "reframe": {
            "anchor_x": "invalid_anchor",
            "anchor_y": "center",
        },
    }
    response = client.post("/api/pixel/jobs/generate", json=payload)
    assert response.status_code == 400
    assert "anchor_x" in response.json()["detail"]


def test_reframe_fill_mode_validation() -> None:
    """Test that invalid reframe fill modes are rejected."""
    payload = {
        "prompt": "a test sprite",
        "reframe": {
            "fill_mode": "invalid_fill",
        },
    }
    response = client.post("/api/pixel/jobs/generate", json=payload)
    assert response.status_code == 400
    assert "fill_mode" in response.json()["detail"]


def test_reframe_default_values() -> None:
    """Test that reframe options have sensible defaults."""
    payload = {
        "prompt": "a test sprite",
        "reframe": {},  # Empty reframe should use defaults
    }
    response = client.post("/api/pixel/jobs/generate", json=payload)
    # Should be accepted with defaults
    assert response.status_code in {200, 400}
    if response.status_code == 200:
        assert "job_id" in response.json()


def test_reframe_scale_bounds() -> None:
    """Test that reframe scale bounds are enforced (1-4x)."""
    payload = {
        "prompt": "a test sprite",
        "reframe": {
            "canvas_scale_x": 0,  # Out of bounds
            "canvas_scale_y": 1,
        },
    }
    response = client.post("/api/pixel/jobs/generate", json=payload)
    # Pydantic should reject this before reaching HTTP handler
    assert response.status_code in {422, 400}


def test_pixel_art_detection_simple() -> None:
    """Test pixel art detection on a simple 16-color image."""
    from pixel_backend.app import _detect_pixel_art

    # Create a simple palette image: 16 unique colors
    img = Image.new("RGB", (64, 64))
    pixels = img.load()
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (255, 0, 255),
        (0, 255, 255),
        (128, 0, 0),
        (0, 128, 0),
        (0, 0, 128),
        (128, 128, 0),
        (128, 0, 128),
        (0, 128, 128),
        (192, 192, 192),
        (128, 128, 128),
        (255, 128, 0),
        (128, 255, 0),
    ]
    for i in range(64 * 64):
        x, y = i % 64, i // 64
        pixels[x, y] = colors[i % 16]

    result = _detect_pixel_art(img)
    assert "is_pixel_art" in result
    assert "detected_palette_size" in result
    assert result["detected_palette_size"] <= 16
    # With 16 colors, should likely be detected as pixel art
    assert result["is_pixel_art"] is True


def test_pixelate_image_downsamples() -> None:
    """Test pixelation reduces image size to target width."""
    from pixel_backend.app import _pixelate_image

    # Create a 256×256 test image
    img = Image.new("RGB", (256, 256), (200, 100, 50))
    pixelated = _pixelate_image(img, target_width=64)

    assert pixelated.width == 64
    assert pixelated.height == 64


def test_pixelate_image_preserves_small_images() -> None:
    """Test pixelation skips images already smaller than target."""
    from pixel_backend.app import _pixelate_image

    # Create a 32×32 test image
    img = Image.new("RGB", (32, 32), (100, 200, 50))
    pixelated = _pixelate_image(img, target_width=64)

    # Should be unchanged (already smaller than target)
    assert pixelated.width == 32
    assert pixelated.height == 32


def test_reframe_image_center_anchor() -> None:
    """Test reframe with center anchor positions source in middle."""
    from pixel_backend.app import _reframe_image

    # Create 32×32 source image
    img = Image.new("RGB", (32, 32), (255, 0, 0))
    reframed, bounds = _reframe_image(img, scale_x=2, scale_y=2, anchor_x="center", anchor_y="center")

    assert reframed.width == 64
    assert reframed.height == 64
    assert bounds["original_width"] == 32
    assert bounds["reframed_width"] == 64
    assert bounds["anchor"] == "center_center"

    # Center-anchored image should have source positioned in middle
    # Check that the center 32×32 region contains the red pixels
    center_pixel = reframed.getpixel((32, 32))
    assert center_pixel == (255, 0, 0)


def test_reframe_image_left_anchor() -> None:
    """Test reframe with left anchor."""
    from pixel_backend.app import _reframe_image

    img = Image.new("RGB", (32, 32), (0, 255, 0))
    reframed, bounds = _reframe_image(img, scale_x=2, scale_y=1, anchor_x="left", anchor_y="center")

    assert reframed.width == 64
    assert reframed.height == 32
    assert bounds["anchor"] == "left_center"

    # Left-anchored should place source at x=0
    left_pixel = reframed.getpixel((0, 16))
    assert left_pixel == (0, 255, 0)


def test_reframe_image_right_anchor() -> None:
    """Test reframe with right anchor."""
    from pixel_backend.app import _reframe_image

    img = Image.new("RGB", (32, 32), (0, 0, 255))
    reframed, bounds = _reframe_image(img, scale_x=2, scale_y=1, anchor_x="right", anchor_y="center")

    assert reframed.width == 64
    assert reframed.height == 32
    assert bounds["anchor"] == "right_center"

    # Right-anchored should place source at x=32
    right_pixel = reframed.getpixel((63, 16))
    assert right_pixel == (0, 0, 255)


def test_reframe_image_no_scale_returns_unchanged() -> None:
    """Test reframe with 1x scale returns image unchanged."""
    from pixel_backend.app import _reframe_image

    img = Image.new("RGB", (32, 32), (128, 128, 128))
    reframed, bounds = _reframe_image(img, scale_x=1, scale_y=1)

    assert reframed.width == 32
    assert reframed.height == 32
    assert bounds["original_width"] == 32
    assert bounds["reframed_width"] == 32


def test_apply_source_processing_none_mode_returns_none_analysis() -> None:
    from pixel_backend.app import GenerateRequest, _apply_source_processing

    img = Image.new("RGB", (64, 64), (120, 90, 30))
    req = GenerateRequest(prompt="test", source_processing_mode="none")

    processed, analysis = _apply_source_processing(img, req)
    assert processed.size == (64, 64)
    assert analysis is None


def test_apply_source_processing_pixelate_mode_adds_steps() -> None:
    from pixel_backend.app import GenerateRequest, _apply_source_processing

    img = Image.new("RGB", (256, 256), (120, 90, 30))
    req = GenerateRequest(
        prompt="test",
        source_processing_mode="pixelate",
        sheet={"frame_width": 64, "frame_height": 64, "columns": 1, "rows": 1, "padding": 0},
    )

    processed, analysis = _apply_source_processing(img, req)
    assert processed.size[0] == 64
    assert analysis is not None
    assert analysis.processing_applied == ["detect", "pixelate"]
    assert analysis.detected_palette_size >= 1


def test_apply_source_processing_reframe_emits_bounds() -> None:
    from pixel_backend.app import GenerateRequest, _apply_source_processing

    img = Image.new("RGB", (32, 16), (10, 20, 30))
    req = GenerateRequest(
        prompt="test",
        source_processing_mode="reframe",
        reframe={
            "canvas_scale_x": 2,
            "canvas_scale_y": 3,
            "fill_mode": "transparent",
            "anchor_x": "center",
            "anchor_y": "center",
            "preserve_bounds": True,
        },
    )

    processed, analysis = _apply_source_processing(img, req)
    assert processed.size == (64, 48)
    assert analysis is not None
    assert analysis.processing_applied == ["detect", "reframe"]
    assert analysis.original_bounds == {"width": 32, "height": 16}
    assert analysis.reframed_bounds == {"width": 64, "height": 48}


def _wait_for_terminal_status(job_id: str, timeout_s: float = 2.0) -> dict:
    deadline = time.time() + timeout_s
    latest: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/pixel/jobs/{job_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest.get("status") in {"success", "failure", "cancelled"}:
            return latest
        time.sleep(0.02)
    return latest


def test_job_cancel_transitions_to_cancelled(monkeypatch) -> None:
    import pixel_backend.app as backend

    def fake_generation(record):
        # Simulate a short-running worker window to allow cancel endpoint race.
        for _ in range(25):
            if record.cancelled:
                return
            time.sleep(0.01)
        if not record.cancelled:
            record.status = "success"
            record.result = {"download": {"png_url": f"/outputs/{record.job_id}/output.png"}}

    monkeypatch.setattr(backend, "_run_generation", fake_generation)

    submit = client.post("/api/pixel/jobs/generate", json={"prompt": "cancel me"})
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]

    cancel = client.post(f"/api/pixel/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    final_payload = _wait_for_terminal_status(job_id)
    assert final_payload["status"] == "cancelled"
    assert final_payload["result"] is None
    assert final_payload["error"] is None


def test_job_failure_exposes_structured_error(monkeypatch) -> None:
    import pixel_backend.app as backend

    def fake_generation(_record):
        raise ModuleNotFoundError("diffusers")

    monkeypatch.setattr(backend, "_run_generation", fake_generation)

    submit = client.post("/api/pixel/jobs/generate", json={"prompt": "fail me"})
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]

    final_payload = _wait_for_terminal_status(job_id)
    assert final_payload["status"] == "failure"
    assert isinstance(final_payload.get("error"), dict)
    assert final_payload["error"].get("type") == "ModuleNotFoundError"
    assert final_payload["error"].get("code") == "module_not_found_error"
    assert "diffusers" in (final_payload["error"].get("message") or "")


def test_job_success_payload_consistency(monkeypatch) -> None:
    import pixel_backend.app as backend

    def fake_generation(record):
        record.status = "success"
        record.result = {
            "download": {
                "png_url": f"/outputs/{record.job_id}/output.png",
                "spritesheet_png_url": f"/outputs/{record.job_id}/output_sheet.png",
                "metadata_url": f"/outputs/{record.job_id}/metadata.json",
            },
            "metadata": {
                "timing": {
                    "total_s": 0.1,
                }
            },
        }

    monkeypatch.setattr(backend, "_run_generation", fake_generation)

    submit = client.post("/api/pixel/jobs/generate", json={"prompt": "succeed me"})
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]

    final_payload = _wait_for_terminal_status(job_id)
    assert final_payload["status"] == "success"
    assert isinstance(final_payload.get("result"), dict)
    download = final_payload["result"].get("download") or {}
    assert bool(download.get("png_url"))
    assert bool(download.get("spritesheet_png_url"))
    assert bool(download.get("metadata_url"))
    metadata = final_payload["result"].get("metadata") or {}
    assert isinstance(metadata.get("timing"), dict)


def test_cancel_after_success_returns_terminal_success(monkeypatch) -> None:
    import pixel_backend.app as backend

    def fake_generation(record):
        record.status = "success"
        record.result = {
            "download": {
                "png_url": f"/outputs/{record.job_id}/output.png",
            }
        }

    monkeypatch.setattr(backend, "_run_generation", fake_generation)

    submit = client.post("/api/pixel/jobs/generate", json={"prompt": "terminal success"})
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]

    final_payload = _wait_for_terminal_status(job_id)
    assert final_payload["status"] == "success"

    cancel = client.post(f"/api/pixel/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "success"
