from __future__ import annotations

import io

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


def test_models_contract() -> None:
    response = client.get("/api/pixel/models")
    assert response.status_code == 200
    payload = response.json()
    assert "models" in payload
    assert isinstance(payload["models"], list)

    model_ids = {item["id"] for item in payload["models"]}
    assert "sdxl_base" in model_ids
    assert "pixel_art_diffusion_xl" in model_ids
    assert "sdxl_base_legacy" in model_ids
    assert "sdxl_pixel_art" in model_ids


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
