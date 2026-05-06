# SDXL + LoRA Setup - Current Status

**Last Updated**: 2026-05-06 00:07 UTC

## ✅ Download Status

### Base Model
| File | Size | Status | ETA |
|------|------|--------|-----|
| `sd_xl_base_1.0.safetensors` | 7.7 GB | 48% downloading | ~20 min |

### LoRAs  
| File | Size | Status | Downloaded |
|------|------|--------|-----------|
| `64x64_Pixel_Art_SDXL.safetensors` | 218 MB | ✅ Complete | 2026-05-06 00:04 |
| `Jinja_Shrine_Zen_SDXL.safetensors` | 127 MB | ✅ Complete | 2026-05-06 00:05 |
| `SwordsmanXL.safetensors` | 163 MB | ✅ Complete | 2026-05-06 00:07 |
| `FFTA_Style_Isometric_Sprites_V2.safetensors` | 218 MB | ✅ Complete | Earlier |

**Total LoRA Size**: 726 MB (all downloaded)

---

## 📊 Model Stack Summary

```
SDXL Base 1.0 (7.7 GB) - DOWNLOADING
├── LoRA 1: 64x64 Pixel Art (218 MB) - READY
├── LoRA 2: Jinja Shrine Zen (127 MB) - READY  
└── LoRA 3: SwordsmanXL (163 MB) - READY
    └── LoRA 4: FFTA Isometric (218 MB) - OPTIONAL
```

**Recommended Stack**:
- Base: SDXL Base 1.0
- LoRA strengths: [0.6–0.8] + [0.3–0.5] + [0.2–0.4]
- Purpose: 64×64 pixel art sprites with ritual shrine aesthetic

---

## 🔧 Terminal Commands (Key Discovery)

### What Worked
```bash
# Civitai downloads require User-Agent + Referer headers
curl -L \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  -H "Referer: https://civitai.com/" \
  -o output.safetensors \
  "https://civitai.com/api/download/models/MODEL_ID?type=Model&format=SafeTensor"
```

### What Failed  
- Simple `curl` without User-Agent → 30-byte redirects
- HuggingFace `/resolve/main/` URLs → sometimes redirect-heavy
- API endpoints without format parameter → wrong content type

---

## 📝 Next Steps

1. **Monitor SDXL download**: Should complete in ~20 minutes
2. **Verify file integrity**: `ls -lh models/**/*.safetensors`
3. **Start backend**: `python pixel_backend/app.py`
4. **Test generation**: Create first 64×64 sprite with friend's strength settings
5. **Document results**: `docs/pixel-studio/PIXEL_TEST_PROMPTS.md`

---

## 💾 Storage Breakdown

### Current Usage
- Base models: 7.7 GB (in progress)
- LoRAs: 726 MB (complete)
- Total: ~8.4 GB

### Free Space Required
- Recommended: 15 GB free (for generation caching, etc.)
- Minimum: 10 GB free

---

## 🎯 Friend's Specification (Reference)

From conversation with domain expert (65x65 pixel art game developer):

| LoRA | Name | Strength | Purpose |
|------|------|----------|---------|
| 1 | SDXL Pixel Art | 0.6–0.8 | Pixelation, color palette |
| 2 | Zen/Minimalist | 0.3–0.5 | Ritual stillness, clean lines |
| 3 | Swordsman/Monk | 0.2–0.4 | Character silhouettes (optional) |

All tested on 64×64 output specifically for isometric shrine/ritual game setting.
