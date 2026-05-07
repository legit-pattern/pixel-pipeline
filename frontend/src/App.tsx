import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type PointerEvent,
} from "react";
import {
  fetchAssetPresets,
  extractPaletteFromFile,
  fetchExportFormats,
  fetchModels,
  fetchPalettes,
  type AssetPreset,
  type ExportFormat,
  type GenerateRequest,
  type JobRecord,
  type ModelOption,
  type PalettePreset,
  type PostProcessingInput,
  type SourceAnalysis,
} from "./api/pixelClient";
import { applyJobPatch, useJobPoller } from "./hooks/useJobPoller";

type Tab = "app" | "library" | "editor";
type Theme = "light" | "dark";
type QualityProfile = "production" | "experimental";
const RECOMMENDED_MODEL_ID = "pixel_art_diffusion_xl";

const STORAGE_KEY = "pixel-studio-job-history";
const STARS_KEY = "pixel-studio-starred-jobs";
const SETTINGS_KEY = "pixel-studio-settings";
const HISTORY_PERSIST_LIMIT = 24;
const CLIP_TOKEN_LIMIT = 77;

function sanitizeFilenamePart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, "_").slice(0, 48) || "asset";
}

function formatElapsed(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

const TEMPLATES = {
  hero: "Create a single-frame game-ready pixel art main character sprite for an isometric 2.5D action RPG. Young male wanderer, practical layered traveler clothing, 3/4 view, neutral ready stance, clean pixel art, 64x64, transparent background, no text, no UI, no environment.",
  frog: "Create a game-ready pixel art enemy sprite sheet for an isometric 2.5D action RPG. Frog-like tower guardian scout, 12 frames total (4 idle, 4 walk, 4 attack), each 64x64, single-row spritesheet, transparent background, no text, no UI, no environment.",
};

const STARTER_PROMPTS_BY_OUTPUT_MODE: Record<string, string> = {
  single_sprite:
    "Pixel Art player character sprite, single frame, 3/4 view, clean silhouette, readable pose, 32-bit style, transparent background, no text, no UI, no watermark.",
  sprite_sheet:
    "Pixel Art character sprite sheet, 12 frames total (idle, walk, attack), each 64x64, consistent proportions across frames, clean silhouette, transparent background, no text, no UI.",
  prop_sheet:
    "Pixel Art prop sheet, top-down game props, consistent scale, clean outlines, limited palette, transparent background, no text, no UI, no watermark.",
  tile_chunk:
    "Pixel Art grass tile, seamless, top-down view, subtle texture, dark green base with light green highlights, tiny wildflowers and small pebbles, 16-bit style, tileable edges, no vignette, no text.",
  tile_iso:
    "Pixel Art isometric tile, 2:1 dimetric projection, seam-safe edges, readable material steps, controlled depth shading, no characters, no text.",
  ui_module:
    "Pixel Art UI module, RPG-style panel and buttons, crisp borders, high contrast readability, transparent background, clean icon slots, no text labels, no watermark.",
};

const STARTER_PROMPTS_BY_LANE: Record<string, string> = {
  sprite:
    "Pixel Art character sprite, game-ready, 3/4 view, readable silhouette, limited palette, crisp edges, transparent background, no text, no UI.",
  iso:
    "Pixel Art isometric character asset, 2:1 dimetric projection, readable three-face volume, clean silhouette, controlled depth shading, transparent background, no text, no UI.",
  world:
    "Pixel Art environment tile, seamless, top-down view, repeat-safe edges, subtle texture variation, balanced contrast, 16-bit style, no vignette, no text.",
  prop:
    "Pixel Art prop asset, game-ready, clean shape language, readable from gameplay distance, limited palette, transparent background, no text.",
  ui:
    "Pixel Art UI element, crisp panel/button module, strong readability, clear edge contrast, transparent background, no text labels.",
  portrait:
    "Pixel Art character portrait bust, centered composition, expressive face, controlled palette, clean shading clusters, transparent background, no text.",
};

function getStarterPrompt(lane: string, outputMode: string): string {
  const byOutput = STARTER_PROMPTS_BY_OUTPUT_MODE[outputMode];
  if (byOutput) {
    return byOutput;
  }
  const byLane = STARTER_PROMPTS_BY_LANE[lane];
  if (byLane) {
    return byLane;
  }
  return STARTER_PROMPTS_BY_LANE.sprite;
}

type QuickStartPreset = {
  label: string;
  lane: string;
  outputMode: string;
  outputFormat: string;
  preferredModelFamilies?: string[];
};

const QUICK_START_PRESETS: QuickStartPreset[] = [
  {
    label: "Standard Pixel Art",
    lane: "sprite",
    outputMode: "single_sprite",
    outputFormat: "png",
    preferredModelFamilies: ["pixel_art_diffusion_xl", "sdxl_pixel_art", "sdxl_base"],
  },
  {
    label: "Isometric Pixel Art",
    lane: "iso",
    outputMode: "single_sprite",
    outputFormat: "png",
    preferredModelFamilies: ["sdxl_iso_landscape", "sdxl_iso_monsters", "pixel_art_diffusion_xl"],
  },
  { label: "Character Sprite", lane: "sprite", outputMode: "single_sprite", outputFormat: "png" },
  { label: "Animation Sheet", lane: "sprite", outputMode: "sprite_sheet", outputFormat: "spritesheet_png" },
  {
    label: "Iso Sprite",
    lane: "iso",
    outputMode: "single_sprite",
    outputFormat: "png",
    preferredModelFamilies: ["sdxl_iso_landscape", "sdxl_iso_monsters", "pixel_art_diffusion_xl"],
  },
  {
    label: "Iso Tile",
    lane: "iso",
    outputMode: "tile_iso",
    outputFormat: "png",
    preferredModelFamilies: ["sdxl_iso_landscape", "sdxl_iso_monsters", "pixel_art_diffusion_xl"],
  },
  { label: "Tile Chunk", lane: "world", outputMode: "tile_chunk", outputFormat: "png" },
  { label: "UI Module", lane: "ui", outputMode: "ui_module", outputFormat: "png" },
];

const DEFAULT_MODELS: ModelOption[] = [
  {
    id: "pixel_art_diffusion_xl",
    label: "Pixel Art Diffusion XL SpriteShaper (recommended checkpoint)",
    quality: "pixel-checkpoint",
    recommended_lanes: ["sprite", "world", "prop", "ui", "detail", "atmosphere", "concept"],
  },
  {
    id: "sdxl_base",
    label: "PAD-XL SpriteShaper (active base)",
    quality: "pixel-checkpoint",
    recommended_lanes: ["sprite", "world", "prop", "ui", "detail", "atmosphere", "concept"],
  },
  {
    id: "sdxl_pixel_art",
    label: "SDXL Base + 64x64 Pixel Art LoRA",
    quality: "pixel-optimized",
    recommended_lanes: ["sprite", "world", "prop"],
  },
  {
    id: "sdxl_iso_landscape",
    label: "SDXL Base + Isometric Landscape Sprites LoRA",
    quality: "iso-optimized",
    recommended_lanes: ["iso"],
  },
  {
    id: "sdxl_iso_monsters",
    label: "SDXL Base + Isometric Monster Sprites LoRA",
    quality: "iso-optimized",
    recommended_lanes: ["iso"],
  },
  {
    id: "sdxl_swordsman",
    label: "SDXL + Swordsman LoRA",
    quality: "character-optimized",
    recommended_lanes: ["sprite", "iso", "portrait", "concept"],
  },
  {
    id: "sdxl_jinja_shrine",
    label: "SDXL + Jinja Shrine Zen LoRA",
    quality: "environment-optimized",
    recommended_lanes: ["world", "iso", "atmosphere", "concept"],
  },
];

function pickQuickStartModel(
  models: ModelOption[],
  lane: string,
  preferredFamilies: string[] | undefined,
): string | null {
  if (models.length === 0) {
    return null;
  }

  for (const id of preferredFamilies ?? []) {
    if (models.some((model) => model.id === id)) {
      return id;
    }
  }

  const laneMatched = models.find((model) => model.recommended_lanes?.includes(lane));
  if (laneMatched) {
    return laneMatched.id;
  }

  return models[0]?.id ?? null;
}

const DEFAULT_ASSET_PRESETS: AssetPreset[] = [
  { id: "sprite", label: "Sprite" },
  { id: "iso_sprite", label: "Iso Sprite (2.5D)" },
  { id: "tile", label: "Tile" },
  { id: "iso_tile", label: "Iso Tile (2.5D)" },
  { id: "prop", label: "Prop" },
  { id: "effect", label: "VFX / Effect" },
  { id: "ui", label: "UI" },
];

const DEFAULT_PALETTES: PalettePreset[] = [
  { id: "custom", label: "Custom", size: 16, colors: [] },
  { id: "gameboy", label: "Game Boy", size: 4, colors: ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"] },
  {
    id: "steam_lords",
    label: "Steam Lords",
    size: 16,
    colors: [
      "#213b25",
      "#3a604a",
      "#4f7754",
      "#a19f7c",
      "#77744f",
      "#775c4f",
      "#603b3a",
      "#3b2137",
      "#170e19",
      "#2f213b",
      "#433a60",
      "#4f5277",
      "#65738c",
      "#7c94a1",
      "#a0b9ba",
      "#c0d1cc",
    ],
  },
];

const DEFAULT_FORMATS: ExportFormat[] = [
  { id: "png", label: "PNG (single frame)" },
  { id: "webp", label: "WebP (animated or still)" },
  { id: "gif", label: "GIF (animated)" },
  { id: "spritesheet_png", label: "Sprite Sheet PNG" },
];

type FrameScore = {
  frame_index: number;
  score: number;
  silhouette: number;
  color: number;
  edge: number;
  attempts: number;
};

// ── Post-processing quick presets ───────────────────────────────────────────
const PP_PRESETS: Record<string, Partial<{
  ppPixelate: boolean; ppPixelateStrength: number;
  ppQuantize: boolean; ppCleanup: boolean;
  ppOutlineStrength: number; ppAntiAliasLevel: number;
  ppClusterSmoothing: number; ppContrastBoost: number;
  ppShadowReinforcement: number; ppHighlightReinforcement: number;
  ppPaletteStrictness: number;
}>> = {
  "Off (none)": { ppPixelate: false, ppQuantize: false, ppCleanup: false, ppOutlineStrength: 0, ppAntiAliasLevel: 0, ppClusterSmoothing: 0, ppContrastBoost: 0, ppShadowReinforcement: 0, ppHighlightReinforcement: 0 },
  "Crisp sprite (16px)": { ppPixelate: true, ppPixelateStrength: 1.0, ppQuantize: true, ppCleanup: true, ppOutlineStrength: 1, ppAntiAliasLevel: 1, ppClusterSmoothing: 1, ppContrastBoost: 0, ppShadowReinforcement: 0, ppHighlightReinforcement: 0, ppPaletteStrictness: 2 },
  "Crisp sprite (32px)": { ppPixelate: true, ppPixelateStrength: 1.0, ppQuantize: true, ppCleanup: true, ppOutlineStrength: 1, ppAntiAliasLevel: 1, ppClusterSmoothing: 2, ppContrastBoost: 0, ppShadowReinforcement: 0, ppHighlightReinforcement: 0, ppPaletteStrictness: 2 },
  "Tile production": { ppPixelate: true, ppPixelateStrength: 1.0, ppQuantize: true, ppCleanup: true, ppOutlineStrength: 0, ppAntiAliasLevel: 2, ppClusterSmoothing: 2, ppContrastBoost: 0.1, ppShadowReinforcement: 0.1, ppHighlightReinforcement: 0.1, ppPaletteStrictness: 2 },
  "Painterly soft": { ppPixelate: false, ppQuantize: false, ppCleanup: false, ppOutlineStrength: 0, ppAntiAliasLevel: 0, ppClusterSmoothing: 0, ppContrastBoost: 0, ppShadowReinforcement: 0, ppHighlightReinforcement: 0 },
};

// ── All available lanes for library filter ───────────────────────────────────
const LIBRARY_LANES = ["sprite", "iso", "world", "prop", "ui", "portrait", "detail", "atmosphere"];

type StudioSettings = {
  tab: Tab;
  theme: Theme;
  search: string;
  filter: "all" | "starred";
  laneFilter: string;
  prompt: string;
  negativePrompt: string;
  lane: string;
  outputMode: string;
  outputFormat: string;
  modelFamily: string;
  assetPreset: string;
  palettePreset: string;
  paletteSize: number;
  customColors: string[];
  frameWidth: number;
  frameHeight: number;
  columns: number;
  rows: number;
  padding: number;
  tileSize: number;
  tileSeamless: boolean;
  tileAutotileMask: string;
  tileVariationCount: number;
  tileNoiseLevel: number;
  tileEdgeSoftening: number;
  ppPixelate: boolean;
  ppPixelateStrength: number;
  postGenerationPixelateFactor: number;
  ppRemoveBg: boolean;
  ppQuantize: boolean;
  ppCleanup: boolean;
  ppOutlineStrength: number;
  ppAntiAliasLevel: number;
  ppClusterSmoothing: number;
  ppContrastBoost: number;
  ppShadowReinforcement: number;
  ppHighlightReinforcement: number;
  ppPaletteStrictness: number;
  sourceProcessingMode: string;
  reframeCanvasScaleX: number;
  reframeCanvasScaleY: number;
  refframeFillMode: string;
  reframeAnchorX: string;
  reframeAnchorY: string;
  motionSpaceHint: string;
  controlMode: string;
  controlStrength: number;
  controlStart: number;
  controlEnd: number;
  isoDepthGuide: boolean;
  isoElevation: number;
  isoAzimuth: number;
  seed: number;
  cfgScale: number;
  enhancePrompt: boolean;
  autoPipeline: boolean;
  keyframeFirst: boolean;
  variationStrength: number;
  consistencyThreshold: number;
  frameRetryBudget: number;
  motionPrior: string;
  qualityProfile: QualityProfile;
  editorGrid: number;
  editorColor: string;
  editorPixels: string[];
  editorCleanupPixelateFactor: number;
  editorCleanupColorStep: number;
  editorCleanupIsolated: boolean;
  editorCleanupNeighborLimit: number;
  numVariants: number;
};

function getAnimationFrameScores(metadata: unknown): FrameScore[] {
  if (!metadata || typeof metadata !== "object") {
    return [];
  }

  const animation = (metadata as Record<string, unknown>).animation;
  if (!animation || typeof animation !== "object") {
    return [];
  }

  const frameScores = (animation as Record<string, unknown>).frame_scores;
  if (!Array.isArray(frameScores)) {
    return [];
  }

  const normalized: FrameScore[] = [];
  for (const item of frameScores) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const raw = item as Record<string, unknown>;
    const frameIndex = Number(raw.frame_index);
    const score = Number(raw.score);
    const silhouette = Number(raw.silhouette);
    const color = Number(raw.color);
    const edge = Number(raw.edge);
    const attempts = Number(raw.attempts);
    if (
      Number.isFinite(frameIndex) &&
      Number.isFinite(score) &&
      Number.isFinite(silhouette) &&
      Number.isFinite(color) &&
      Number.isFinite(edge) &&
      Number.isFinite(attempts)
    ) {
      normalized.push({
        frame_index: frameIndex,
        score,
        silhouette,
        color,
        edge,
        attempts,
      });
    }
  }
  return normalized;
}

function getSourceAnalysis(metadata: unknown): SourceAnalysis | null {
  if (!metadata || typeof metadata !== "object") {
    return null;
  }

  const sourceAnalysis = (metadata as Record<string, unknown>).source_analysis;
  if (!sourceAnalysis || typeof sourceAnalysis !== "object") {
    return null;
  }

  const raw = sourceAnalysis as Record<string, unknown>;
  const isPixelArt = raw.is_pixel_art;
  const detectedPaletteSize = raw.detected_palette_size;
  const processingApplied = raw.processing_applied;

  if (
    typeof isPixelArt !== "boolean" ||
    typeof detectedPaletteSize !== "number" ||
    !Array.isArray(processingApplied)
  ) {
    return null;
  }

  const originalBoundsRaw = raw.original_bounds;
  const reframedBoundsRaw = raw.reframed_bounds;

  const originalBounds =
    originalBoundsRaw &&
    typeof originalBoundsRaw === "object" &&
    typeof (originalBoundsRaw as Record<string, unknown>).width === "number" &&
    typeof (originalBoundsRaw as Record<string, unknown>).height === "number"
      ? {
          width: (originalBoundsRaw as Record<string, number>).width,
          height: (originalBoundsRaw as Record<string, number>).height,
        }
      : undefined;

  const reframedBounds =
    reframedBoundsRaw &&
    typeof reframedBoundsRaw === "object" &&
    typeof (reframedBoundsRaw as Record<string, unknown>).width === "number" &&
    typeof (reframedBoundsRaw as Record<string, unknown>).height === "number"
      ? {
          width: (reframedBoundsRaw as Record<string, number>).width,
          height: (reframedBoundsRaw as Record<string, number>).height,
        }
      : undefined;

  const normalizedProcessing = processingApplied.filter(
    (item): item is string => typeof item === "string",
  );

  return {
    is_pixel_art: isPixelArt,
    detected_palette_size: detectedPaletteSize,
    processing_applied: normalizedProcessing,
    original_bounds: originalBounds,
    reframed_bounds: reframedBounds,
  };
}

function estimateClipTokenCount(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) {
    return 0;
  }

  // Rough estimate for CLIP BPE-like tokenization (words + punctuation).
  const matches = trimmed.match(/[A-Za-z0-9_]+|[^\sA-Za-z0-9_]/g);
  return matches?.length ?? 0;
}

function compactJobRecordForStorage(record: JobRecord): JobRecord {
  return {
    ...record,
    request: {
      ...record.request,
      // Source images can be very large and will easily exhaust localStorage.
      source_image_base64: null,
    },
    result: record.result
      ? {
          image_url: record.result.image_url,
          spritesheet_url: record.result.spritesheet_url,
          seed: record.result.seed,
          // Keep downloads for library reuse, but drop bulky frame arrays/metadata.
          download: record.result.download,
        }
      : record.result,
  };
}

function persistHistorySafe(history: JobRecord[]): void {
  const compacted = history
    .slice(0, HISTORY_PERSIST_LIMIT)
    .map(compactJobRecordForStorage);

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(compacted));
    return;
  } catch {
    // Retry with increasingly smaller history snapshots so the app never crashes.
  }

  for (const limit of [12, 8, 4, 1]) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(compacted.slice(0, limit)));
      return;
    } catch {
      // Keep shrinking until it fits or give up silently.
    }
  }

  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore localStorage failures in dev/private mode.
  }
}

function readHistory(): JobRecord[] {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as JobRecord[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function readStarred(): string[] {
  const raw = localStorage.getItem(STARS_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as string[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function readSettings(): Partial<StudioSettings> {
  const raw = localStorage.getItem(SETTINGS_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as Partial<StudioSettings>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function persistSettingsSafe(settings: StudioSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    return;
  } catch {
    // Fallback for strict/private storage quotas.
  }

  const compacted: StudioSettings = {
    ...settings,
    editorPixels: [],
  };
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(compacted));
    return;
  } catch {
    // Last resort: clear corrupt/oversized settings payload.
  }

  try {
    localStorage.removeItem(SETTINGS_KEY);
  } catch {
    // Ignore storage errors.
  }
}

function App() {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const savedSettings = readSettings();

  const [tab, setTab] = useState<Tab>(savedSettings.tab ?? "app");
  const [theme, setTheme] = useState<Theme>(savedSettings.theme ?? (prefersDark ? "dark" : "light"));

  const [models, setModels] = useState<ModelOption[]>(DEFAULT_MODELS);
  const [modelsLoaded, setModelsLoaded] = useState<boolean>(false);
  const [palettes, setPalettes] = useState<PalettePreset[]>(DEFAULT_PALETTES);
  const [assetPresets, setAssetPresets] = useState<AssetPreset[]>(DEFAULT_ASSET_PRESETS);
  const [formats, setFormats] = useState<ExportFormat[]>(DEFAULT_FORMATS);

  const [history, setHistory] = useState<JobRecord[]>(readHistory());
  const [starredIds, setStarredIds] = useState<string[]>(readStarred());
  const [laneFilter, setLaneFilter] = useState<string>(savedSettings.laneFilter ?? "all");
  const [variantBatch, setVariantBatch] = useState<JobRecord[]>([]);
  const [numVariants, setNumVariants] = useState<number>(savedSettings.numVariants ?? 1);

  const [search, setSearch] = useState<string>(savedSettings.search ?? "");
  const [filter, setFilter] = useState<"all" | "starred">(savedSettings.filter ?? "all");

  const [prompt, setPrompt] = useState<string>(savedSettings.prompt ?? TEMPLATES.hero);
  const [negativePrompt, setNegativePrompt] = useState<string>(
    savedSettings.negativePrompt ?? "blurry, painterly, 3d render, text, logo, watermark",
  );
  const [lane, setLane] = useState<string>(savedSettings.lane ?? "sprite");
  const [outputMode, setOutputMode] = useState<string>(savedSettings.outputMode ?? "sprite_sheet");
  const [outputFormat, setOutputFormat] = useState<string>(savedSettings.outputFormat ?? "spritesheet_png");
  const [modelFamily, setModelFamily] = useState<string>(savedSettings.modelFamily ?? "pixel_art_diffusion_xl");
  const [assetPreset, setAssetPreset] = useState<string>(savedSettings.assetPreset ?? "auto");

  const [palettePreset, setPalettePreset] = useState<string>(savedSettings.palettePreset ?? "steam_lords");
  const [paletteSize, setPaletteSize] = useState<number>(savedSettings.paletteSize ?? 16);
  const [customColors, setCustomColors] = useState<string[]>(savedSettings.customColors ?? []);

  const [frameWidth, setFrameWidth] = useState<number>(savedSettings.frameWidth ?? 64);
  const [frameHeight, setFrameHeight] = useState<number>(savedSettings.frameHeight ?? 64);
  const [columns, setColumns] = useState<number>(savedSettings.columns ?? 1);
  const [rows, setRows] = useState<number>(savedSettings.rows ?? 1);
  const [padding, setPadding] = useState<number>(savedSettings.padding ?? 0);
  const [tileSize, setTileSize] = useState<number>(savedSettings.tileSize ?? 64);
  const [tileSeamless, setTileSeamless] = useState<boolean>(savedSettings.tileSeamless ?? false);
  const [tileAutotileMask, setTileAutotileMask] = useState<string>(savedSettings.tileAutotileMask ?? "none");
  const [tileVariationCount, setTileVariationCount] = useState<number>(savedSettings.tileVariationCount ?? 1);
  const [tileNoiseLevel, setTileNoiseLevel] = useState<number>(savedSettings.tileNoiseLevel ?? 0);
  const [tileEdgeSoftening, setTileEdgeSoftening] = useState<number>(savedSettings.tileEdgeSoftening ?? 0);

  // post-processing – all opt-in, all default off
  const [ppPixelate, setPpPixelate] = useState<boolean>(savedSettings.ppPixelate ?? false);
  const [ppPixelateStrength, setPpPixelateStrength] = useState<number>(savedSettings.ppPixelateStrength ?? 1.0);
  const [postGenerationPixelateFactor, setPostGenerationPixelateFactor] = useState<number>(
    savedSettings.postGenerationPixelateFactor ?? 3,
  );
  const [postGenerationPixelatedPreviewUrl, setPostGenerationPixelatedPreviewUrl] = useState<string>("");
  const [postGenerationPixelateBusy, setPostGenerationPixelateBusy] = useState<boolean>(false);
  const [postGenerationPixelateError, setPostGenerationPixelateError] = useState<string>("");
  const [ppRemoveBg, setPpRemoveBg] = useState<boolean>(savedSettings.ppRemoveBg ?? false);
  const [ppQuantize, setPpQuantize] = useState<boolean>(savedSettings.ppQuantize ?? false);
  const [ppCleanup, setPpCleanup] = useState<boolean>(savedSettings.ppCleanup ?? false);
  const [ppOutlineStrength, setPpOutlineStrength] = useState<number>(savedSettings.ppOutlineStrength ?? 1);
  const [ppAntiAliasLevel, setPpAntiAliasLevel] = useState<number>(savedSettings.ppAntiAliasLevel ?? 1);
  const [ppClusterSmoothing, setPpClusterSmoothing] = useState<number>(savedSettings.ppClusterSmoothing ?? 1);
  const [ppContrastBoost, setPpContrastBoost] = useState<number>(savedSettings.ppContrastBoost ?? 0);
  const [ppShadowReinforcement, setPpShadowReinforcement] = useState<number>(savedSettings.ppShadowReinforcement ?? 0);
  const [ppHighlightReinforcement, setPpHighlightReinforcement] = useState<number>(savedSettings.ppHighlightReinforcement ?? 0);
  const [ppPaletteStrictness, setPpPaletteStrictness] = useState<number>(savedSettings.ppPaletteStrictness ?? 2);

  // generation quality controls
  const [seed, setSeed] = useState<number>(savedSettings.seed ?? -1);
  const [cfgScale, setCfgScale] = useState<number>(savedSettings.cfgScale ?? 7.5);
  const [enhancePrompt, setEnhancePrompt] = useState<boolean>(savedSettings.enhancePrompt ?? false);
  const [autoPipeline, setAutoPipeline] = useState<boolean>(savedSettings.autoPipeline ?? false);
  const [keyframeFirst, setKeyframeFirst] = useState<boolean>(savedSettings.keyframeFirst ?? false);
  const [variationStrength, setVariationStrength] = useState<number>(savedSettings.variationStrength ?? 0.35);
  const [consistencyThreshold, setConsistencyThreshold] = useState<number>(savedSettings.consistencyThreshold ?? 0.65);
  const [frameRetryBudget, setFrameRetryBudget] = useState<number>(savedSettings.frameRetryBudget ?? 2);
  const [motionPrior, setMotionPrior] = useState<string>(savedSettings.motionPrior ?? "auto");
  const [qualityProfile, setQualityProfile] = useState<QualityProfile>(savedSettings.qualityProfile ?? "production");

  const [sourcePreview, setSourcePreview] = useState<string>("");
  const [sourceImageBase64, setSourceImageBase64] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string>("");
  const [paletteUploadLoading, setPaletteUploadLoading] = useState<boolean>(false);

  // Phase 1: Input conditioning state
  const [sourceProcessingMode, setSourceProcessingMode] = useState<string>(
    savedSettings.sourceProcessingMode ?? "detect",
  );
  const [reframeCanvasScaleX, setReframeCanvasScaleX] = useState<number>(
    savedSettings.reframeCanvasScaleX ?? 1,
  );
  const [reframeCanvasScaleY, setReframeCanvasScaleY] = useState<number>(
    savedSettings.reframeCanvasScaleY ?? 1,
  );
  const [refframeFillMode, setRefframeFillMode] = useState<string>(
    savedSettings.refframeFillMode ?? "transparent",
  );
  const [reframeAnchorX, setReframeAnchorX] = useState<string>(
    savedSettings.reframeAnchorX ?? "center",
  );
  const [reframeAnchorY, setReframeAnchorY] = useState<string>(
    savedSettings.reframeAnchorY ?? "center",
  );
  const [motionSpaceHint, setMotionSpaceHint] = useState<string>(
    savedSettings.motionSpaceHint ?? "auto",
  );
  const [controlMode, setControlMode] = useState<string>(savedSettings.controlMode ?? "none");
  const [controlStrength, setControlStrength] = useState<number>(savedSettings.controlStrength ?? 0.5);
  const [controlStart, setControlStart] = useState<number>(savedSettings.controlStart ?? 0);
  const [controlEnd, setControlEnd] = useState<number>(savedSettings.controlEnd ?? 1);
  // iso camera angle controls
  const [isoDepthGuide, setIsoDepthGuide] = useState<boolean>(savedSettings.isoDepthGuide ?? false);
  const [isoElevation, setIsoElevation] = useState<number>(savedSettings.isoElevation ?? 26.565);
  const [isoAzimuth, setIsoAzimuth] = useState<number>(savedSettings.isoAzimuth ?? 45);

  const [editorGrid, setEditorGrid] = useState<number>(savedSettings.editorGrid ?? 24);
  const [editorColor, setEditorColor] = useState<string>(savedSettings.editorColor ?? "#78b0a6");
  const [editorPixels, setEditorPixels] = useState<string[]>(
    savedSettings.editorPixels ?? Array.from({ length: (savedSettings.editorGrid ?? 24) * (savedSettings.editorGrid ?? 24) }, () => ""),
  );
  const [editorCleanupPixelateFactor, setEditorCleanupPixelateFactor] = useState<number>(
    savedSettings.editorCleanupPixelateFactor ?? 1.5,
  );
  const [editorCleanupColorStep, setEditorCleanupColorStep] = useState<number>(
    savedSettings.editorCleanupColorStep ?? 16,
  );
  const [editorCleanupIsolated, setEditorCleanupIsolated] = useState<boolean>(
    savedSettings.editorCleanupIsolated ?? true,
  );
  const [editorCleanupNeighborLimit, setEditorCleanupNeighborLimit] = useState<number>(
    savedSettings.editorCleanupNeighborLimit ?? 1,
  );
  const [editorImportedImageUrl, setEditorImportedImageUrl] = useState<string>("");
  const [editorWorkingImageUrl, setEditorWorkingImageUrl] = useState<string>("");
  const [editorCleanupBusy, setEditorCleanupBusy] = useState<boolean>(false);
  const [editorCleanupError, setEditorCleanupError] = useState<string>("");
  // force-resize state
  const [editorResizeWidth, setEditorResizeWidth] = useState<number>(64);
  const [editorResizeHeight, setEditorResizeHeight] = useState<number>(64);
  const [editorResizeTrimAlpha, setEditorResizeTrimAlpha] = useState<boolean>(true);
  const [editorResizeBusy, setEditorResizeBusy] = useState<boolean>(false);
  const [editorResizeError, setEditorResizeError] = useState<string>("");
  const [isDrawing, setIsDrawing] = useState<boolean>(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const editorGridInitializedRef = useRef<boolean>(false);

  // ── job poller ─────────────────────────────────────────────────────────────
  const handleJobUpdate = useCallback(
    (patch: Pick<JobRecord, "job_id" | "status" | "result" | "error">) => {
      setHistory((prev) => applyJobPatch(prev, patch));
    },
    [],
  );
  const { state: jobState, submit: submitJob, cancel: cancelJob } = useJobPoller(handleJobUpdate);
  const [progressNowMs, setProgressNowMs] = useState<number>(() => Date.now());

  const availableModels = modelsLoaded ? models : DEFAULT_MODELS;
  const hasAvailableModels = availableModels.length > 0;
  const availablePalettes = palettes.length > 0 ? palettes : DEFAULT_PALETTES;
  const availableAssetPresets = assetPresets.length > 0 ? assetPresets : DEFAULT_ASSET_PRESETS;
  const availableFormats = formats.length > 0 ? formats : DEFAULT_FORMATS;
  const frameScores = useMemo(() => getAnimationFrameScores(jobState.result?.metadata), [jobState.result?.metadata]);
  const sourceAnalysis = useMemo(() => getSourceAnalysis(jobState.result?.metadata), [jobState.result?.metadata]);
  const promptTokenEstimate = useMemo(() => estimateClipTokenCount(prompt), [prompt]);
  const negativePromptTokenEstimate = useMemo(() => estimateClipTokenCount(negativePrompt), [negativePrompt]);
  const avgFrameScore = useMemo(() => {
    if (frameScores.length === 0) {
      return null;
    }
    const total = frameScores.reduce((acc, item) => acc + item.score, 0);
    return total / frameScores.length;
  }, [frameScores]);
  const progressPercent = useMemo(() => {
    const step = Number(jobState.progress?.step ?? NaN);
    const total = Number(jobState.progress?.total ?? NaN);
    if (!Number.isFinite(step) || !Number.isFinite(total) || total <= 0) {
      return null;
    }
    return Math.max(0, Math.min(100, (step / total) * 100));
  }, [jobState.progress?.step, jobState.progress?.total]);
  const elapsedSeconds = useMemo(() => {
    const progress = jobState.progress;
    if (!progress) {
      return null;
    }

    const isActive = ["queued", "pending"].includes(jobState.status);
    const anchor = progress.started_at ?? progress.created_at;
    if (isActive && typeof anchor === "number" && Number.isFinite(anchor)) {
      return Math.max(0, (progressNowMs / 1000) - anchor);
    }

    const serverElapsed = Number(progress.elapsed_s ?? NaN);
    if (Number.isFinite(serverElapsed)) {
      return Math.max(0, serverElapsed);
    }
    return null;
  }, [jobState.progress, jobState.status, progressNowMs]);
  const etaSeconds = useMemo(() => {
    if (jobState.status !== "pending") {
      return null;
    }
    const step = Number(jobState.progress?.step ?? NaN);
    const total = Number(jobState.progress?.total ?? NaN);
    if (!Number.isFinite(step) || !Number.isFinite(total) || step <= 0 || total <= step) {
      return null;
    }
    if (elapsedSeconds == null || elapsedSeconds <= 0) {
      return null;
    }
    const secPerStep = elapsedSeconds / step;
    const remaining = secPerStep * (total - step);
    return Number.isFinite(remaining) ? Math.max(0, remaining) : null;
  }, [jobState.progress?.step, jobState.progress?.total, jobState.status, elapsedSeconds]);
  const progressPhaseLabel = useMemo(() => {
    const phase = (jobState.progress?.phase ?? "").toString().trim().toLowerCase();
    if (!phase) {
      return null;
    }
    const labels: Record<string, string> = {
      queued: "Queued",
      starting: "Starting",
      preparing: "Preparing",
      inference: "Generating image",
      post_processing: "Post-processing",
      saving_outputs: "Saving outputs",
      complete: "Complete",
      cancelled: "Cancelled",
      failed: "Failed",
    };
    return labels[phase] ?? phase;
  }, [jobState.progress?.phase]);
  const isGithubPagesFrontend = useMemo(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.location.hostname.endsWith("github.io");
  }, []);
  const lockModelSelection = useMemo(
    () => isGithubPagesFrontend && availableModels.some((model) => model.id === RECOMMENDED_MODEL_ID),
    [isGithubPagesFrontend, availableModels],
  );

  useEffect(() => {
    if (!lockModelSelection) {
      return;
    }
    if (modelFamily !== RECOMMENDED_MODEL_ID) {
      Promise.resolve().then(() => {
        setModelFamily(RECOMMENDED_MODEL_ID);
      });
    }
  }, [lockModelSelection, modelFamily]);

  useEffect(() => {
    if (!["queued", "pending"].includes(jobState.status)) {
      return;
    }
    const id = window.setInterval(() => setProgressNowMs(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [jobState.status]);

  const harmonizedPalette = useMemo(() => {
    return customColors
      .filter((color) => /^#[0-9a-fA-F]{6}$/.test(color))
      .map((color) => {
        const { r, g, b } = hexToRgb(color);
        const { h, s, l } = rgbToHsl(r, g, b);
        return { color, h, s, l };
      })
      .sort((a, b) => {
        if (a.h !== b.h) {
          return a.h - b.h;
        }
        if (a.s !== b.s) {
          return b.s - a.s;
        }
        return a.l - b.l;
      })
      .map((item) => item.color);
  }, [customColors]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    persistHistorySafe(history);
  }, [history]);

  useEffect(() => {
    try {
      localStorage.setItem(STARS_KEY, JSON.stringify(starredIds));
    } catch {
      // Ignore storage quota errors; starred state can remain in-memory.
    }
  }, [starredIds]);

  useEffect(() => {
    persistSettingsSafe({
      tab,
      theme,
      search,
      filter,
      laneFilter,
      numVariants,
      prompt,
      negativePrompt,
      lane,
      outputMode,
      outputFormat,
      modelFamily,
      assetPreset,
      palettePreset,
      paletteSize,
      customColors,
      frameWidth,
      frameHeight,
      columns,
      rows,
      padding,
      tileSize,
      tileSeamless,
      tileAutotileMask,
      tileVariationCount,
      tileNoiseLevel,
      tileEdgeSoftening,
      ppPixelate,
      ppPixelateStrength,
      postGenerationPixelateFactor,
      ppRemoveBg,
      ppQuantize,
      ppCleanup,
      ppOutlineStrength,
      ppAntiAliasLevel,
      ppClusterSmoothing,
      ppContrastBoost,
      ppShadowReinforcement,
      ppHighlightReinforcement,
      ppPaletteStrictness,
      sourceProcessingMode,
      reframeCanvasScaleX,
      reframeCanvasScaleY,
      refframeFillMode,
      reframeAnchorX,
      reframeAnchorY,
      motionSpaceHint,
      controlMode,
      controlStrength,
      controlStart,
      controlEnd,
      isoDepthGuide,
      isoElevation,
      isoAzimuth,
      seed,
      cfgScale,
      enhancePrompt,
      autoPipeline,
      keyframeFirst,
      variationStrength,
      consistencyThreshold,
      frameRetryBudget,
      motionPrior,
      qualityProfile,
      editorGrid,
      editorColor,
      editorPixels,
      editorCleanupPixelateFactor,
      editorCleanupColorStep,
      editorCleanupIsolated,
      editorCleanupNeighborLimit,
    });
  }, [
    tab,
    theme,
    search,
    filter,
    prompt,
    negativePrompt,
    lane,
    outputMode,
    outputFormat,
    modelFamily,
    assetPreset,
    palettePreset,
    paletteSize,
    customColors,
    frameWidth,
    frameHeight,
    columns,
    rows,
    padding,
    tileSize,
    tileSeamless,
    tileAutotileMask,
    tileVariationCount,
    tileNoiseLevel,
    tileEdgeSoftening,
    ppPixelate,
    ppPixelateStrength,
    postGenerationPixelateFactor,
    ppRemoveBg,
    ppQuantize,
    ppCleanup,
    ppOutlineStrength,
    ppAntiAliasLevel,
    ppClusterSmoothing,
    ppContrastBoost,
    ppShadowReinforcement,
    ppHighlightReinforcement,
    ppPaletteStrictness,
    sourceProcessingMode,
    reframeCanvasScaleX,
    reframeCanvasScaleY,
    refframeFillMode,
    reframeAnchorX,
    reframeAnchorY,
    motionSpaceHint,
    controlMode,
    controlStrength,
    controlStart,
    controlEnd,
    isoDepthGuide,
    isoElevation,
    isoAzimuth,
    seed,
    cfgScale,
    enhancePrompt,
    autoPipeline,
    keyframeFirst,
    variationStrength,
    consistencyThreshold,
    frameRetryBudget,
    motionPrior,
    qualityProfile,
    editorGrid,
    editorColor,
    editorPixels,
    editorCleanupPixelateFactor,
    editorCleanupColorStep,
    editorCleanupIsolated,
    editorCleanupNeighborLimit,
    laneFilter,
    numVariants,
  ]);

  const applyQualityProfile = useCallback((profile: QualityProfile) => {
    setQualityProfile(profile);

    if (profile === "production") {
      setModelFamily("pixel_art_diffusion_xl");
      setPalettePreset("steam_lords");
      setPaletteSize(16);
      setCustomColors([]);
      setFrameWidth(64);
      setFrameHeight(64);
      setTileSize(64);
      setAutoPipeline(true);
      setEnhancePrompt(true);
      setKeyframeFirst(true);
      setVariationStrength(0.3);
      setConsistencyThreshold(0.75);
      setFrameRetryBudget(3);
      setMotionPrior("auto");
      setPpPixelate(false);
      setPpRemoveBg(false);
      setPpQuantize(false);
      setPpCleanup(false);
      setPpPaletteStrictness(2);
      setCfgScale(7.0);
      return;
    }

    setModelFamily("sdxl_base");
    setPalettePreset("custom");
    setPaletteSize(24);
    setAutoPipeline(false);
    setEnhancePrompt(true);
    setKeyframeFirst(false);
    setVariationStrength(0.35);
    setConsistencyThreshold(0.65);
    setFrameRetryBudget(2);
    setMotionPrior("auto");
    setPpPixelate(false);
    setPpRemoveBg(false);
    setPpQuantize(false);
    setPpCleanup(false);
    setPpPaletteStrictness(1);
    setCfgScale(7.5);
  }, []);

  const handleResetProductionDefaults = useCallback(() => {
    applyQualityProfile("production");
    setValidationError("");
  }, [applyQualityProfile]);

  useEffect(() => {
    void Promise.all([
      fetchModels(),
      fetchPalettes(),
      fetchAssetPresets(),
      fetchExportFormats(),
    ])
      .then(([m, p, ap, f]) => {
        setModels(m);
        setModelsLoaded(true);
        setPalettes(p.length ? p : DEFAULT_PALETTES);
        setAssetPresets(ap.length ? ap : DEFAULT_ASSET_PRESETS);
        setFormats(f.length ? f : DEFAULT_FORMATS);
      })
      .catch(() => {
        setModels(DEFAULT_MODELS);
        setModelsLoaded(false);
        setPalettes(DEFAULT_PALETTES);
        setAssetPresets(DEFAULT_ASSET_PRESETS);
        setFormats(DEFAULT_FORMATS);
      });
  }, []);

  useEffect(() => {
    Promise.resolve().then(() => {
      setPostGenerationPixelatedPreviewUrl("");
      setPostGenerationPixelateError("");
      setPostGenerationPixelateBusy(false);
    });
  }, [jobState.result?.download?.png_url, jobState.result?.image_url]);

  useEffect(() => {
    if (!modelsLoaded) {
      return;
    }
    if (models.length === 0) {
      if (modelFamily !== "") {
        Promise.resolve().then(() => {
          setModelFamily("");
        });
      }
      return;
    }
    if (!models.some((model) => model.id === modelFamily)) {
      Promise.resolve().then(() => {
        setModelFamily(models[0]?.id ?? "");
      });
    }
  }, [modelFamily, models, modelsLoaded]);

  useEffect(() => {
    if (!availablePalettes.some((palette) => palette.id === palettePreset)) {
      const preferred = availablePalettes.find((palette) => palette.id === "steam_lords");
      // Defer state sync to avoid synchronous setState in effect body.
      Promise.resolve().then(() => {
        setPalettePreset(preferred ? preferred.id : availablePalettes[0]?.id ?? "custom");
        if (preferred?.size) {
          setPaletteSize(preferred.size);
        }
      });
    }
  }, [availablePalettes, palettePreset]);

  useEffect(() => {
    if (!editorGridInitializedRef.current) {
      editorGridInitializedRef.current = true;
      return;
    }
    setEditorPixels(Array.from({ length: editorGrid * editorGrid }, () => ""));
  }, [editorGrid]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const size = editorGrid;
    const scale = 12;
    canvas.width = size * scale;
    canvas.height = size * scale;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const index = y * size + x;
        const color = editorPixels[index];

        if (color) {
          ctx.fillStyle = color;
          ctx.fillRect(x * scale, y * scale, scale, scale);
        } else {
          const checker = (x + y) % 2 === 0 ? "#00000012" : "#ffffff12";
          ctx.fillStyle = checker;
          ctx.fillRect(x * scale, y * scale, scale, scale);
        }
      }
    }

    ctx.strokeStyle = "#00000022";
    for (let i = 0; i <= size; i += 1) {
      ctx.beginPath();
      ctx.moveTo(i * scale, 0);
      ctx.lineTo(i * scale, canvas.height);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(0, i * scale);
      ctx.lineTo(canvas.width, i * scale);
      ctx.stroke();
    }
  }, [editorGrid, editorPixels]);

  useEffect(() => {
    const stopDrawing = () => setIsDrawing(false);
    window.addEventListener("pointerup", stopDrawing);
    return () => window.removeEventListener("pointerup", stopDrawing);
  }, []);

  function setTemplate(kind: "hero" | "frog") {
    setPrompt(TEMPLATES[kind]);
  }

  function applyStarterPromptForSelection() {
    setPrompt(getStarterPrompt(lane, outputMode));
  }

  function applyQuickStart(preset: QuickStartPreset) {
    setLane(preset.lane);
    setOutputMode(preset.outputMode);
    setOutputFormat(preset.outputFormat);
    const selectedModel = pickQuickStartModel(availableModels, preset.lane, preset.preferredModelFamilies);
    if (selectedModel) {
      setModelFamily(selectedModel);
    }
    setPrompt(getStarterPrompt(preset.lane, preset.outputMode));
    setValidationError("");
  }

  async function handleSourceImage(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      return;
    }
    if (file.type !== "image/png") {
      setValidationError("Source image must be PNG.");
      return;
    }
    setValidationError("");

    const dataUrl = await fileToDataUrl(file);
    const cleanBase64 = dataUrl.replace(/^data:image\/png;base64,/, "");
    setSourcePreview(dataUrl);
    setSourceImageBase64(cleanBase64);
  }

  function removeSourceImage() {
    setSourcePreview("");
    setSourceImageBase64(null);
  }

  /** Upload a PNG swatch to the backend and apply the returned colours. */
  async function handlePaletteFileUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      return;
    }
    setValidationError("");
    setPaletteUploadLoading(true);
    try {
      const result = await extractPaletteFromFile(file);
      if (result.colors.length === 0) {
        setValidationError("No colours found in palette image.");
        return;
      }
      setPalettePreset("custom");
      setPaletteSize(Math.max(paletteSize, result.count));
      setCustomColors(result.colors);
    } catch (err) {
      setValidationError(err instanceof Error ? err.message : "Palette upload failed.");
    } finally {
      setPaletteUploadLoading(false);
      // Reset so the same file can be re-uploaded after edits
      e.target.value = "";
    }
  }

  async function handleSubmitJob() {
    setValidationError("");

    if (!hasAvailableModels) {
      setValidationError(
        "No runnable models are currently available. Replace the broken checkpoint or add a healthy Diffusers model directory first.",
      );
      return;
    }

    if (!prompt.trim()) {
      setValidationError("Prompt is required.");
      return;
    }

    const postProcessing: PostProcessingInput = {
      pixelate: ppPixelate,
      pixelate_strength: ppPixelateStrength,
      remove_background: ppRemoveBg,
      quantize_palette: ppQuantize,
      pixel_cleanup: ppCleanup,
      outline_strength: ppOutlineStrength,
      anti_alias_level: ppAntiAliasLevel,
      cluster_smoothing: ppClusterSmoothing,
      contrast_boost: ppContrastBoost,
      shadow_reinforcement: ppShadowReinforcement,
      highlight_reinforcement: ppHighlightReinforcement,
      palette_strictness: ppPaletteStrictness,
    };

    const request: GenerateRequest = {
      prompt: prompt.trim(),
      negative_prompt: negativePrompt,
      lane,
      output_mode: outputMode,
      output_format: outputFormat,
      ephemeral_output: isGithubPagesFrontend,
      asset_preset: assetPreset,
      character_dna_id: null,
      model_family: modelFamily,
      source_image_base64: sourceImageBase64,
      // Phase 1: Input conditioning
      source_processing_mode: sourceProcessingMode,
      reframe: {
        canvas_scale_x: reframeCanvasScaleX,
        canvas_scale_y: reframeCanvasScaleY,
        fill_mode: refframeFillMode,
        anchor_x: reframeAnchorX,
        anchor_y: reframeAnchorY,
        preserve_bounds: true,
      },
      control_mode: controlMode,
      control_strength: controlStrength,
      control_start: controlStart,
      control_end: controlEnd,
      iso_depth_guide: isoDepthGuide,
      iso_elevation: isoElevation,
      iso_azimuth: isoAzimuth,
      tile_options: {
        tile_size: tileSize,
        seamless_mode: tileSeamless,
        autotile_mask: tileAutotileMask,
        variation_count: tileVariationCount,
        noise_level: tileNoiseLevel,
        edge_softening: tileEdgeSoftening,
      },
      post_processing: postProcessing,
      seed,
      cfg_scale: cfgScale,
      enhance_prompt: enhancePrompt,
      auto_pipeline: autoPipeline,
      keyframe_first: keyframeFirst,
      variation_strength: variationStrength,
      consistency_threshold: consistencyThreshold,
      frame_retry_budget: frameRetryBudget,
      motion_prior: motionPrior,
      palette: {
        preset: palettePreset,
        size: paletteSize,
        colors: palettePreset === "custom" ? customColors.filter(Boolean) : [],
      },
      sheet: {
        frame_width: frameWidth,
        frame_height: frameHeight,
        columns,
        rows,
        padding,
      },
    };

    try {
      if (numVariants <= 1) {
        const record = await submitJob(request);
        setHistory((prev) => [record, ...prev].slice(0, 150));
        setVariantBatch([]);
      } else {
        // Submit N variants in sequence (same prompt+settings, each with seed=-1 for random)
        setVariantBatch([]);
        const variantRequest = { ...request, seed: -1 };
        const batch: JobRecord[] = [];
        for (let i = 0; i < numVariants; i++) {
          const record = await submitJob(variantRequest);
          batch.push(record);
          setHistory((prev) => [record, ...prev].slice(0, 150));
          setVariantBatch([...batch]);
          // Small delay between submissions to avoid overwhelming the queue
          if (i < numVariants - 1) await new Promise(r => setTimeout(r, 200));
        }
      }
    } catch {
      // error already reflected in jobState.errorMessage
    }
  }

  function toggleStar(jobId: string) {
    setStarredIds((prev) =>
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [jobId, ...prev],
    );
  }

  function removeLibraryItem(jobId: string) {
    setHistory((prev) => prev.filter((item) => item.job_id !== jobId));
    setStarredIds((prev) => prev.filter((id) => id !== jobId));
  }

  function clearLibrary() {
    if (!window.confirm("Delete all items from your local library?")) {
      return;
    }
    setHistory([]);
    setStarredIds([]);
  }

  function setPixelAt(clientX: number, clientY: number, erase: boolean) {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const x = Math.floor(((clientX - rect.left) / rect.width) * editorGrid);
    const y = Math.floor(((clientY - rect.top) / rect.height) * editorGrid);

    if (x < 0 || y < 0 || x >= editorGrid || y >= editorGrid) {
      return;
    }

    const index = y * editorGrid + x;
    setEditorPixels((prev) => prev.map((value, i) => (i === index ? (erase ? "" : editorColor) : value)));
  }

  function onCanvasPointerDown(event: PointerEvent<HTMLCanvasElement>) {
    event.preventDefault();
    setIsDrawing(true);
    setPixelAt(event.clientX, event.clientY, event.button === 2 || event.altKey);
  }

  function onCanvasPointerMove(event: PointerEvent<HTMLCanvasElement>) {
    if (!isDrawing) {
      return;
    }
    setPixelAt(event.clientX, event.clientY, event.buttons === 2 || event.altKey);
  }

  function clearEditor() {
    setEditorPixels(Array.from({ length: editorGrid * editorGrid }, () => ""));
  }

  function exportEditorPng() {
    const out = document.createElement("canvas");
    out.width = editorGrid;
    out.height = editorGrid;
    const ctx = out.getContext("2d");
    if (!ctx) {
      return;
    }

    for (let y = 0; y < editorGrid; y += 1) {
      for (let x = 0; x < editorGrid; x += 1) {
        const color = editorPixels[y * editorGrid + x];
        if (!color) {
          continue;
        }
        ctx.fillStyle = color;
        ctx.fillRect(x, y, 1, 1);
      }
    }

    const link = document.createElement("a");
    link.href = out.toDataURL("image/png");
    link.download = `pixel-editor-${editorGrid}x${editorGrid}.png`;
    link.click();
  }

  async function extractPaletteFromSource() {
    if (!sourcePreview) {
      setValidationError("Upload a PNG first to extract a palette.");
      return;
    }

    const image = await loadImage(sourcePreview);
    const canvas = document.createElement("canvas");
    const maxSide = 96;
    const ratio = Math.min(1, maxSide / Math.max(image.width, image.height));
    canvas.width = Math.max(1, Math.floor(image.width * ratio));
    canvas.height = Math.max(1, Math.floor(image.height * ratio));

    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) {
      return;
    }

    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const frequencies = new Map<string, number>();

    for (let i = 0; i < data.length; i += 4) {
      const alpha = data[i + 3];
      if (alpha < 24) {
        continue;
      }

      const r = Math.round(data[i] / 16) * 16;
      const g = Math.round(data[i + 1] / 16) * 16;
      const b = Math.round(data[i + 2] / 16) * 16;
      const hex = rgbToHex(clamp255(r), clamp255(g), clamp255(b));
      frequencies.set(hex, (frequencies.get(hex) ?? 0) + 1);
    }

    const limit = Math.max(4, Math.min(48, paletteSize));
    const extracted = [...frequencies.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([hex]) => hex);

    if (extracted.length === 0) {
      setValidationError("No visible colors found in source image.");
      return;
    }

    setPalettePreset("custom");
    setCustomColors(extracted);
    setValidationError("");
  }

  async function handleCancelJob() {
    await cancelJob();
  }

  function updateCustomColor(index: number, value: string) {
    setCustomColors((prev) => prev.map((item, i) => (i === index ? value : item)));
  }

  function addCustomColor() {
    setCustomColors((prev) => [...prev, "#000000"]);
  }

  function removeCustomColor(index: number) {
    setCustomColors((prev) => prev.filter((_, i) => i !== index));
  }

  const filteredHistory = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return history.filter((item) => {
      if (filter === "starred" && !starredIds.includes(item.job_id)) {
        return false;
      }
      if (laneFilter !== "all" && item.request.lane !== laneFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const promptText = item.request.prompt.toLowerCase();
      return (
        promptText.includes(needle) ||
        item.request.model_family.toLowerCase().includes(needle) ||
        item.request.lane.toLowerCase().includes(needle)
      );
    });
  }, [history, search, filter, laneFilter, starredIds]);

  function downloadLink(label: string, url?: string) {
    const disabled = !url;
    const extension =
      label === "PNG"
        ? "png"
        : label === "WebP"
          ? "webp"
          : label === "GIF"
            ? "gif"
            : label === "Sprite Sheet"
              ? "png"
              : "json";

    async function triggerDownload(e: { preventDefault: () => void }) {
      if (disabled || !url) {
        e.preventDefault();
        return;
      }

      e.preventDefault();
      const baseName = sanitizeFilenamePart(prompt || lane);
      const filename = `${baseName}_${label.toLowerCase().replace(/\s+/g, "_")}.${extension}`;

      if (url.startsWith("data:")) {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        return;
      }

      try {
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(objectUrl);
      } catch {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    }

    return (
      <a
        key={label}
        className={`download-pill${disabled ? " disabled" : ""}`}
        href={url || "#"}
        download
        onClick={triggerDownload}
      >
        {label}
      </a>
    );
  }

  const baseGeneratedPreviewUrl =
    jobState.result?.download?.png_url ?? jobState.result?.image_url;
  const activeGeneratedPreviewUrl = postGenerationPixelatedPreviewUrl || baseGeneratedPreviewUrl;

  async function applyPostGenerationPixelate() {
    setPostGenerationPixelateError("");
    if (!baseGeneratedPreviewUrl) {
      setPostGenerationPixelateError("Generate an image first, then apply post-generation pixelate.");
      return;
    }

    setPostGenerationPixelateBusy(true);
    try {
      const pixelated = await pixelateImageToDataUrl(baseGeneratedPreviewUrl, postGenerationPixelateFactor);
      setPostGenerationPixelatedPreviewUrl(pixelated);
    } catch {
      setPostGenerationPixelateError("Could not pixelate the generated image preview.");
    } finally {
      setPostGenerationPixelateBusy(false);
    }
  }

  function resetPostGenerationPixelate() {
    setPostGenerationPixelatedPreviewUrl("");
    setPostGenerationPixelateError("");
  }

  function downloadPostGenerationPixelatedPng() {
    if (!postGenerationPixelatedPreviewUrl) {
      return;
    }
    const anchor = document.createElement("a");
    anchor.href = postGenerationPixelatedPreviewUrl;
    anchor.download = "pixelated-preview.png";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  }

  function sendGeneratedPreviewToEditor() {
    if (!activeGeneratedPreviewUrl) {
      setValidationError("Generate an image first, then send it to Pixel Editor.");
      return;
    }
    setEditorImportedImageUrl(activeGeneratedPreviewUrl);
    setEditorWorkingImageUrl(activeGeneratedPreviewUrl);
    setEditorCleanupError("");
    setTab("editor");
  }

  async function handleEditorImageUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      return;
    }
    if (file.type !== "image/png") {
      setEditorCleanupError("Pixel Editor import currently supports PNG only.");
      return;
    }
    setEditorCleanupError("");
    const dataUrl = await fileToDataUrl(file);
    setEditorImportedImageUrl(dataUrl);
    setEditorWorkingImageUrl(dataUrl);
    e.target.value = "";
  }

  async function applyEditorCleanup() {
    if (!editorWorkingImageUrl) {
      setEditorCleanupError("No editor image loaded yet.");
      return;
    }
    setEditorCleanupError("");
    setEditorCleanupBusy(true);
    try {
      const cleaned = await cleanupImageForEditor(editorWorkingImageUrl, {
        pixelateFactor: editorCleanupPixelateFactor,
        colorStep: editorCleanupColorStep,
        removeIsolated: editorCleanupIsolated,
        maxNeighborsSame: editorCleanupNeighborLimit,
      });
      setEditorWorkingImageUrl(cleaned);
    } catch {
      setEditorCleanupError("Cleanup failed for this image.");
    } finally {
      setEditorCleanupBusy(false);
    }
  }

  function resetEditorImportedImage() {
    if (!editorImportedImageUrl) {
      return;
    }
    setEditorWorkingImageUrl(editorImportedImageUrl);
    setEditorCleanupError("");
  }

  function clearEditorImportedImage() {
    setEditorImportedImageUrl("");
    setEditorWorkingImageUrl("");
    setEditorCleanupError("");
  }

  function exportEditorProcessedImage() {
    if (!editorWorkingImageUrl) {
      return;
    }
    const link = document.createElement("a");
    link.href = editorWorkingImageUrl;
    link.download = "pixel-editor-cleanup.png";
    link.click();
  }

  /**
   * Force-resize the working image to targetW×targetH while preserving subject integrity.
   *
   * Pipeline:
   *  1. Optionally auto-trim transparent borders (keeps the actual sprite subject centred).
   *  2. Iterative half-resolution bilinear downscale until we reach ≤2× the target
   *     (reduces aliasing vs. a single large-to-small jump).
   *  3. Final nearest-neighbor snap to exact target size (correct pixel-art look).
   *
   * Result is a PNG data-URL at the requested pixel dimensions.
   */
  async function resizeImageForEditor(
    src: string,
    targetW: number,
    targetH: number,
    trimAlpha: boolean,
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        let srcCanvas = document.createElement("canvas");
        srcCanvas.width = img.naturalWidth;
        srcCanvas.height = img.naturalHeight;
        const srcCtx = srcCanvas.getContext("2d")!;
        srcCtx.drawImage(img, 0, 0);

        // Step 1: trim transparent border if requested (sprite / prop use-case)
        if (trimAlpha) {
          const data = srcCtx.getImageData(0, 0, srcCanvas.width, srcCanvas.height);
          const px = data.data;
          let minX = srcCanvas.width, minY = srcCanvas.height, maxX = 0, maxY = 0;
          for (let y = 0; y < srcCanvas.height; y++) {
            for (let x = 0; x < srcCanvas.width; x++) {
              const alpha = px[(y * srcCanvas.width + x) * 4 + 3];
              if (alpha > 8) {
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
              }
            }
          }
          if (maxX > minX && maxY > minY) {
            const tw = maxX - minX + 1;
            const th = maxY - minY + 1;
            const trimmed = document.createElement("canvas");
            trimmed.width = tw;
            trimmed.height = th;
            trimmed.getContext("2d")!.drawImage(srcCanvas, minX, minY, tw, th, 0, 0, tw, th);
            srcCanvas = trimmed;
          }
        }

        // Step 2: iterative bilinear halving until ≤2× target
        let cur = srcCanvas;
        while (cur.width > targetW * 2 || cur.height > targetH * 2) {
          const hw = Math.max(targetW, Math.round(cur.width / 2));
          const hh = Math.max(targetH, Math.round(cur.height / 2));
          const half = document.createElement("canvas");
          half.width = hw;
          half.height = hh;
          const hCtx = half.getContext("2d")!;
          hCtx.imageSmoothingEnabled = true;
          hCtx.imageSmoothingQuality = "high";
          hCtx.drawImage(cur, 0, 0, hw, hh);
          cur = half;
        }

        // Step 3: final snap to exact target with nearest-neighbor (pixel-art look)
        const out = document.createElement("canvas");
        out.width = targetW;
        out.height = targetH;
        const outCtx = out.getContext("2d")!;
        outCtx.imageSmoothingEnabled = false;
        outCtx.drawImage(cur, 0, 0, targetW, targetH);

        resolve(out.toDataURL("image/png"));
      };
      img.onerror = () => reject(new Error("Failed to load image for resize"));
      img.src = src;
    });
  }

  async function applyEditorResize() {
    if (!editorWorkingImageUrl) {
      setEditorResizeError("No editor image loaded yet.");
      return;
    }
    if (editorResizeWidth < 1 || editorResizeHeight < 1) {
      setEditorResizeError("Target size must be at least 1×1.");
      return;
    }
    setEditorResizeError("");
    setEditorResizeBusy(true);
    try {
      const resized = await resizeImageForEditor(
        editorWorkingImageUrl,
        editorResizeWidth,
        editorResizeHeight,
        editorResizeTrimAlpha,
      );
      setEditorWorkingImageUrl(resized);
    } catch {
      setEditorResizeError("Resize failed.");
    } finally {
      setEditorResizeBusy(false);
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Pixel Studio</p>
          <h1>Asset Flow</h1>
        </div>
        <div className="topbar-actions">
          <nav className="tabs" aria-label="Primary">
            <button className={tab === "app" ? "active" : ""} onClick={() => setTab("app")}>
              App
            </button>
            <button className={tab === "library" ? "active" : ""} onClick={() => setTab("library")}>
              Library
            </button>
            <button className={tab === "editor" ? "active" : ""} onClick={() => setTab("editor")}>
              Pixel Editor
            </button>
          </nav>
          <button className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </div>
      </header>

      {tab === "app" && (
        <main className="app-grid">
          <section className="panel controls" style={{ animationDelay: "80ms" }}>
            <h2>Create</h2>

            <div className="flow-banner" role="region" aria-label="Quick start">
              <p className="flow-title">Fast path</p>
              <div className="flow-steps" aria-hidden="true">
                <span>1. Pick workflow</span>
                <span>2. Adjust prompt</span>
                <span>3. Submit</span>
              </div>
              <div className="quickstart-row">
                {QUICK_START_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    className="quickstart-pill"
                    onClick={() => applyQuickStart(preset)}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <label>
              Model profile
              {lockModelSelection ? (
                <input value="Pixel Art Diffusion XL SpriteShaper ★ Recommended" readOnly />
              ) : (
                <select value={modelFamily} onChange={(e) => setModelFamily(e.target.value)}>
                  {!hasAvailableModels && <option value="">No runnable models available</option>}
                  {availableModels.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.label}
                    </option>
                  ))}
                </select>
              )}
            </label>
            <p className="muted">
              {lockModelSelection
                ? "Public mode keeps one stable model path to reduce failures and keep output consistency."
                : hasAvailableModels
                  ? "Choose one profile/checkpoint per run; profiles are not combined automatically."
                  : "No runnable backend models are available right now. Repair the local checkpoint or provide a healthy Diffusers model directory."}
            </p>

            <label>
              Asset type
              <select value={assetPreset} onChange={(e) => setAssetPreset(e.target.value)}>
                <option value="auto">Auto (from lane)</option>
                {availableAssetPresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">
              Auto follows selected lane. Use VFX / Effect for particles, spell hits, smoke, sparks, and similar non-character assets.
            </p>

            <label>
              Prompt *
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={5} />
            </label>
            <p className={promptTokenEstimate > CLIP_TOKEN_LIMIT ? "error" : "muted"}>
              CLIP limit: max {CLIP_TOKEN_LIMIT} tokens per prompt field. Current prompt (estimate): {promptTokenEstimate}. Text above the limit can be truncated by the model.
              {enhancePrompt ? " Auto-enhance adds extra tags, so keep some margin." : ""}
            </p>

            <div className="template-row">
              <button onClick={applyStarterPromptForSelection}>Apply starter prompt</button>
              <button onClick={() => setTemplate("hero")}>Character prompt</button>
              <button onClick={() => setTemplate("frog")}>Enemy prompt</button>
            </div>

            <label>
              Negative prompt
              <textarea value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} rows={3} />
            </label>
            <p className={negativePromptTokenEstimate > CLIP_TOKEN_LIMIT ? "error" : "muted"}>
              Negative prompt (estimate): {negativePromptTokenEstimate}/{CLIP_TOKEN_LIMIT} tokens.
            </p>

            <div className="inline-grid three">
              <label>
                Lane
                <select value={lane} onChange={(e) => setLane(e.target.value)}>
                  <option value="sprite">Sprite</option>
                  <option value="iso">Iso</option>
                  <option value="world">World</option>
                  <option value="prop">Prop</option>
                  <option value="ui">UI</option>
                  <option value="portrait">Portrait</option>
                </select>
              </label>
            </div>

            {lane === "iso" && (
              <div className="iso-angle-panel">
                <p className="panel-subtitle">Iso Camera Angle</p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={isoDepthGuide}
                    onChange={(e) => setIsoDepthGuide(e.target.checked)}
                  />
                  Use synthetic depth guide (locks camera via ControlNet — no source image needed)
                </label>
                <label>
                  Elevation: {isoElevation.toFixed(1)}° {isoElevation > 26 && isoElevation < 27.5 ? "(classic 2:1 dimetric)" : ""}
                  <input
                    type="range"
                    min={10}
                    max={60}
                    step={0.5}
                    value={isoElevation}
                    onChange={(e) => setIsoElevation(parseFloat(e.target.value))}
                  />
                </label>
                <label>
                  Azimuth (camera direction)
                  <select value={isoAzimuth} onChange={(e) => setIsoAzimuth(parseFloat(e.target.value))}>
                    <option value={45}>45° — NE facing (SNES/GBA standard)</option>
                    <option value={135}>135° — SE facing</option>
                    <option value={225}>225° — SW facing</option>
                    <option value={315}>315° — NW facing</option>
                    <option value={0}>0° — North (custom)</option>
                    <option value={90}>90° — East (custom)</option>
                    <option value={180}>180° — South (custom)</option>
                    <option value={270}>270° — West (custom)</option>
                  </select>
                </label>
              </div>
            )}

            <div className="inline-grid three">
              <label>
                Output mode
                <select value={outputMode} onChange={(e) => setOutputMode(e.target.value)}>
                  <option value="single_sprite">Single Sprite</option>
                  <option value="sprite_sheet">Sprite Sheet</option>
                  <option value="prop_sheet">Prop Sheet</option>
                  <option value="tile_chunk">Tile Chunk</option>
                  <option value="tile_iso">Iso Tile</option>
                  <option value="ui_module">UI Module</option>
                </select>
              </label>

              <label>
                Primary export format
                <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value)}>
                  {availableFormats.map((format) => (
                    <option key={format.id} value={format.id}>
                      {format.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="submit-dock" role="region" aria-label="Primary action">
              <div className="variant-row">
                <button className="submit submit-primary" onClick={handleSubmitJob} disabled={!hasAvailableModels}>
                  {numVariants > 1 ? `Generate ${numVariants} variants` : "Submit Generation"}
                </button>
                <div className="variant-count-group" title="How many variants to generate in one click">
                  {[1, 2, 4, 6].map((n) => (
                    <button
                      key={n}
                      className={`variant-pill${numVariants === n ? " active" : ""}`}
                      onClick={() => setNumVariants(n)}
                    >{n}</button>
                  ))}
                </div>
              </div>
              <p className="muted">Core settings above. Advanced settings can be expanded below when needed.</p>
            </div>

            <div className="subpanel">
              <h3>Palette</h3>

              <div className="palette-upload-row">
                <label className="palette-upload-label">
                  {paletteUploadLoading ? "Extracting…" : "Load palette from PNG"}
                  <input
                    type="file"
                    accept="image/png"
                    disabled={paletteUploadLoading}
                    onChange={handlePaletteFileUpload}
                    style={{ display: "none" }}
                  />
                </label>
                <p className="muted">
                  Upload a palette-swatch PNG (e.g. 16×1 px) – server extracts the exact hex colours.
                </p>
              </div>

              <div className="inline-grid two">
                <label>
                  Palette preset
                  <select
                    value={palettePreset}
                    onChange={(e) => {
                      const next = e.target.value;
                      setPalettePreset(next);
                      const preset = availablePalettes.find((p) => p.id === next);
                      if (preset) {
                        setPaletteSize(preset.size);
                        if (preset.colors.length > 0) {
                          setCustomColors(preset.colors);
                        }
                      }
                    }}
                  >
                    {availablePalettes.map((palette) => (
                      <option key={palette.id} value={palette.id}>
                        {palette.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Color count
                  <select value={paletteSize} onChange={(e) => setPaletteSize(Number(e.target.value))}>
                    {[8, 16, 24, 32, 48].map((count) => (
                      <option key={count} value={count}>
                        {count} colors
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="color-list">
                {customColors.map((color, index) => (
                  <div key={`${color}-${index}`} className="color-row">
                    <input type="color" value={color} onChange={(e) => updateCustomColor(index, e.target.value)} />
                    <input value={color} onChange={(e) => updateCustomColor(index, e.target.value)} />
                    <button onClick={() => removeCustomColor(index)} aria-label={`Remove color ${index + 1}`}>
                      Remove
                    </button>
                  </div>
                ))}
                <button onClick={addCustomColor}>Add color</button>
              </div>

              {customColors.length > 0 && (
                <div className="palette-preview-panel">
                  <div className="palette-preview-head">
                    <p>Palette preview</p>
                    <span>{customColors.length} colors</span>
                  </div>

                  <div className="swatch-grid" aria-label="Extracted palette preview">
                    {customColors.map((color, index) => (
                      <div key={`raw-${color}-${index}`} className="swatch-card" title={color}>
                        <span className="swatch-chip" style={{ backgroundColor: color }} />
                        <span>{color}</span>
                      </div>
                    ))}
                  </div>

                  <div className="palette-preview-head">
                    <p>Harmonized order (analogous-ish)</p>
                    <span>sorted by hue</span>
                  </div>
                  <div className="swatch-grid" aria-label="Harmonized palette preview">
                    {harmonizedPalette.map((color, index) => (
                      <div key={`harmonized-${color}-${index}`} className="swatch-card" title={color}>
                        <span className="swatch-chip" style={{ backgroundColor: color }} />
                        <span>{color}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="subpanel">
              <h3>Frame sheet</h3>
              <div className="inline-grid five">
                <label>
                  W
                  <input type="number" min={8} value={frameWidth} onChange={(e) => setFrameWidth(Number(e.target.value))} />
                </label>
                <label>
                  H
                  <input type="number" min={8} value={frameHeight} onChange={(e) => setFrameHeight(Number(e.target.value))} />
                </label>
                <label>
                  Col
                  <input type="number" min={1} value={columns} onChange={(e) => setColumns(Number(e.target.value))} />
                </label>
                <label>
                  Rows
                  <input type="number" min={1} value={rows} onChange={(e) => setRows(Number(e.target.value))} />
                </label>
                <label>
                  Pad
                  <input type="number" min={0} value={padding} onChange={(e) => setPadding(Number(e.target.value))} />
                </label>
              </div>
            </div>

            <details className="advanced-disclosure">
              <summary>Advanced settings</summary>
              <p className="muted">Use these only when you need finer control over style, tiling, conditioning, cleanup, or generation behavior.</p>

            <div className="subpanel">
              <h3>Tile controls</h3>
              <p className="muted">Primarily useful for tile-focused outputs; can be left at defaults for sprites and props.</p>
              <div className="inline-grid three">
                <label>
                  Tile size
                  <select value={tileSize} onChange={(e) => setTileSize(Number(e.target.value))}>
                    {[16, 32, 48, 64].map((size) => (
                      <option key={size} value={size}>
                        {size}px
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Variation count
                  <input
                    type="number"
                    min={1}
                    max={16}
                    value={tileVariationCount}
                    onChange={(e) => setTileVariationCount(Number(e.target.value))}
                  />
                </label>
                <label>
                  Autotile mask
                  <select value={tileAutotileMask} onChange={(e) => setTileAutotileMask(e.target.value)}>
                    <option value="none">None</option>
                    <option value="blob_4way">Blob 4-way</option>
                    <option value="wall_top">Wall top</option>
                    <option value="platform">Platform</option>
                  </select>
                </label>
              </div>
              <label className="checkbox-row">
                <input type="checkbox" checked={tileSeamless} onChange={(e) => setTileSeamless(e.target.checked)} />
                <span>
                  <strong>Seamless mode</strong> - force opposite edges to tile cleanly
                </span>
              </label>
              <label className="slider-row">
                <span>Noise level ({tileNoiseLevel})</span>
                <input
                  type="range"
                  min={0}
                  max={3}
                  step={1}
                  value={tileNoiseLevel}
                  onChange={(e) => setTileNoiseLevel(parseInt(e.target.value, 10) || 0)}
                />
              </label>
              <label className="slider-row">
                <span>Edge softening ({tileEdgeSoftening})</span>
                <input
                  type="range"
                  min={0}
                  max={3}
                  step={1}
                  value={tileEdgeSoftening}
                  onChange={(e) => setTileEdgeSoftening(parseInt(e.target.value, 10) || 0)}
                />
              </label>
            </div>

            <div className="subpanel">
              <h3>Source image (PNG)</h3>
              <p className="muted">Optional reference input. Skip this section for pure text-to-image generation.</p>
              <input type="file" accept="image/png" onChange={handleSourceImage} />
              {sourcePreview && (
                <div className="source-preview">
                  <img src={sourcePreview} alt="Source preview" />
                  <button onClick={removeSourceImage}>Remove</button>
                  <button onClick={extractPaletteFromSource}>Extract palette</button>
                </div>
              )}
            </div>

            {/* Phase 1: Input conditioning controls */}
            {sourceImageBase64 && (
              <div className="subpanel">
                <h3>Input Conditioning (Phase 1)</h3>

                <label className="label">
                  <span className="label-text">Processing Mode</span>
                  <select value={sourceProcessingMode} onChange={(e) => setSourceProcessingMode(e.target.value)}>
                    <option value="detect">Detect pixel art</option>
                    <option value="pixelate">Pixelate (downscale)</option>
                    <option value="reframe">Reframe canvas</option>
                    <option value="none">No processing</option>
                  </select>
                </label>

                {(sourceProcessingMode === "reframe" || sourceProcessingMode === "detect") && (
                  <div className="nested-controls">
                    <label className="label">
                      <span className="label-text">Canvas Scale X: {reframeCanvasScaleX}×</span>
                      <input
                        type="range"
                        min="1"
                        max="4"
                        value={reframeCanvasScaleX}
                        onChange={(e) => setReframeCanvasScaleX(Number(e.target.value))}
                      />
                    </label>
                    <label className="label">
                      <span className="label-text">Canvas Scale Y: {reframeCanvasScaleY}×</span>
                      <input
                        type="range"
                        min="1"
                        max="4"
                        value={reframeCanvasScaleY}
                        onChange={(e) => setReframeCanvasScaleY(Number(e.target.value))}
                      />
                    </label>

                    <label className="label">
                      <span className="label-text">Fill Mode</span>
                      <select value={refframeFillMode} onChange={(e) => setRefframeFillMode(e.target.value)}>
                        <option value="transparent">Transparent</option>
                        <option value="color">Mid-gray</option>
                        <option value="edge">Edge color</option>
                      </select>
                    </label>

                    <div className="anchor-grid-label">Anchor Position</div>
                    <div className="anchor-grid">
                      {(["top", "center", "bottom"] as const).map((y) =>
                        (["left", "center", "right"] as const).map((x) => (
                          <button
                            key={`${x}-${y}`}
                            className={`anchor-button ${reframeAnchorX === x && reframeAnchorY === y ? "active" : ""}`}
                            onClick={() => {
                              setReframeAnchorX(x);
                              setReframeAnchorY(y);
                            }}
                            title={`${x}-${y}`}
                          >
                            {x[0].toUpperCase()}{y[0].toUpperCase()}
                          </button>
                        )),
                      )}
                    </div>
                  </div>
                )}

                <label className="label">
                  <span className="label-text">Motion Space Hint</span>
                  <select value={motionSpaceHint} onChange={(e) => setMotionSpaceHint(e.target.value)}>
                    <option value="auto">Auto-detect</option>
                    <option value="confined">Confined (e.g., small sprite)</option>
                    <option value="moderate">Moderate (e.g., walk/run cycle)</option>
                    <option value="open">Open (e.g., full-screen camera)</option>
                  </select>
                </label>

                <label className="label">
                  <span className="label-text">ControlNet Mode</span>
                  <select value={controlMode} onChange={(e) => setControlMode(e.target.value)}>
                    <option value="none">None</option>
                    <option value="depth">Depth</option>
                    <option value="canny">Canny Edges</option>
                  </select>
                </label>

                {controlMode !== "none" && (
                  <div className="nested-controls">
                    <label className="label">
                      <span className="label-text">Control Strength: {controlStrength.toFixed(2)}</span>
                      <input
                        type="range"
                        min="0"
                        max="1.5"
                        step="0.05"
                        value={controlStrength}
                        onChange={(e) => setControlStrength(Number(e.target.value))}
                      />
                    </label>
                    <label className="label">
                      <span className="label-text">Control Start: {controlStart.toFixed(2)}</span>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={controlStart}
                        onChange={(e) => setControlStart(Number(e.target.value))}
                      />
                    </label>
                    <label className="label">
                      <span className="label-text">Control End: {controlEnd.toFixed(2)}</span>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={controlEnd}
                        onChange={(e) => setControlEnd(Number(e.target.value))}
                      />
                    </label>
                  </div>
                )}
              </div>
            )}

            <div className="subpanel">
              <h3>Post-processing</h3>
              <p className="muted">
                All steps are opt-in. Leave all off if the image already looks right – you can always re-generate.
              </p>
              <div className="pp-preset-row">
                <select
                  defaultValue=""
                  onChange={(e) => {
                    const preset = PP_PRESETS[e.target.value];
                    if (!preset) return;
                    if (preset.ppPixelate !== undefined) setPpPixelate(preset.ppPixelate);
                    if (preset.ppPixelateStrength !== undefined) setPpPixelateStrength(preset.ppPixelateStrength);
                    if (preset.ppQuantize !== undefined) setPpQuantize(preset.ppQuantize);
                    if (preset.ppCleanup !== undefined) setPpCleanup(preset.ppCleanup);
                    if (preset.ppOutlineStrength !== undefined) setPpOutlineStrength(preset.ppOutlineStrength);
                    if (preset.ppAntiAliasLevel !== undefined) setPpAntiAliasLevel(preset.ppAntiAliasLevel);
                    if (preset.ppClusterSmoothing !== undefined) setPpClusterSmoothing(preset.ppClusterSmoothing);
                    if (preset.ppContrastBoost !== undefined) setPpContrastBoost(preset.ppContrastBoost);
                    if (preset.ppShadowReinforcement !== undefined) setPpShadowReinforcement(preset.ppShadowReinforcement);
                    if (preset.ppHighlightReinforcement !== undefined) setPpHighlightReinforcement(preset.ppHighlightReinforcement);
                    if (preset.ppPaletteStrictness !== undefined) setPpPaletteStrictness(preset.ppPaletteStrictness);
                    e.target.value = "";
                  }}
                >
                  <option value="" disabled>Load preset…</option>
                  {Object.keys(PP_PRESETS).map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>
              <label className="checkbox-row">
                <input type="checkbox" checked={ppPixelate} onChange={(e) => setPpPixelate(e.target.checked)} />
                <span>
                  <strong>Pixelate</strong> – downscale to frame size then upsample with nearest-neighbour to enforce crisp pixel-art edges
                </span>
              </label>
              <label className="checkbox-row">
                <input type="checkbox" checked={ppRemoveBg} onChange={(e) => setPpRemoveBg(e.target.checked)} />
                <span>
                  <strong>Remove background</strong> – transparent background via rembg (skipped if not installed)
                </span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={ppQuantize}
                  onChange={(e) => setPpQuantize(e.target.checked)}
                  disabled={customColors.length === 0}
                />
                <span>
                  <strong>Quantize to palette</strong> – Floyd-Steinberg dither; only active when custom colours are set
                </span>
              </label>
              <label className="checkbox-row">
                <input type="checkbox" checked={ppCleanup} onChange={(e) => setPpCleanup(e.target.checked)} />
                <span>
                  <strong>Pixel cleanup</strong> – remove isolated pixels, reduce anti-aliasing noise, and strengthen sprite edges
                </span>
              </label>

              {ppCleanup && (
                <>
                  <label className="slider-row">
                    <span>Outline strength ({ppOutlineStrength})</span>
                    <input
                      type="range"
                      min={0}
                      max={3}
                      step={1}
                      value={ppOutlineStrength}
                      onChange={(e) => setPpOutlineStrength(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Anti-alias removal ({ppAntiAliasLevel})</span>
                    <input
                      type="range"
                      min={0}
                      max={3}
                      step={1}
                      value={ppAntiAliasLevel}
                      onChange={(e) => setPpAntiAliasLevel(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Cluster smoothing ({ppClusterSmoothing})</span>
                    <input
                      type="range"
                      min={0}
                      max={3}
                      step={1}
                      value={ppClusterSmoothing}
                      onChange={(e) => setPpClusterSmoothing(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Contrast boost ({ppContrastBoost})</span>
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={1}
                      value={ppContrastBoost}
                      onChange={(e) => setPpContrastBoost(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Shadow reinforcement ({ppShadowReinforcement})</span>
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={1}
                      value={ppShadowReinforcement}
                      onChange={(e) => setPpShadowReinforcement(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Highlight reinforcement ({ppHighlightReinforcement})</span>
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={1}
                      value={ppHighlightReinforcement}
                      onChange={(e) => setPpHighlightReinforcement(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Palette strictness ({ppPaletteStrictness})</span>
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={1}
                      value={ppPaletteStrictness}
                      onChange={(e) => setPpPaletteStrictness(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                </>
              )}

              {ppPixelate && (
                <label className="slider-row">
                  <span>Pixelate strength: {ppPixelateStrength.toFixed(1)}×</span>
                  <input
                    type="range"
                    min={0.1}
                    max={4.0}
                    step={0.1}
                    value={ppPixelateStrength}
                    onChange={(e) => setPpPixelateStrength(parseFloat(e.target.value))}
                  />
                </label>
              )}
            </div>

            <div className="subpanel">
              <h3>Generation controls</h3>
              <p className="muted">Expert controls for consistency and quality tuning. Defaults are usually enough.</p>
              <label className="field-row">
                <span>Quality profile</span>
                <select
                  value={qualityProfile}
                  onChange={(e) => applyQualityProfile(e.target.value as QualityProfile)}
                >
                  <option value="production">Production (stable pixel output)</option>
                  <option value="experimental">Experimental (free exploration)</option>
                </select>
              </label>
              <button type="button" onClick={handleResetProductionDefaults}>
                Reset to production defaults
              </button>
              <label className="checkbox-row">
                <input type="checkbox" checked={autoPipeline} onChange={(e) => setAutoPipeline(e.target.checked)} />
                <span>
                  <strong>Auto pipeline</strong> - 8x generation, pixel snap, and palette quantize (if colors are set)
                </span>
              </label>
              <label className="checkbox-row">
                <input type="checkbox" checked={enhancePrompt} onChange={(e) => setEnhancePrompt(e.target.checked)} />
                <span>
                  <strong>Auto-enhance prompt</strong> – injects lane-specific pixel-art keywords automatically
                </span>
              </label>
              <label className="checkbox-row">
                <input type="checkbox" checked={keyframeFirst} onChange={(e) => setKeyframeFirst(e.target.checked)} />
                <span>
                  <strong>Keyframe-first animation</strong> - generate one keyframe, derive remaining frames, and validate consistency
                </span>
              </label>
              {keyframeFirst && (
                <>
                  <label className="field-row">
                    <span>Motion prior</span>
                    <select value={motionPrior} onChange={(e) => setMotionPrior(e.target.value)}>
                      <option value="auto">Auto</option>
                      <option value="bounce">Bounce</option>
                      <option value="sway">Sway</option>
                      <option value="pulse">Pulse</option>
                      <option value="bloom">Bloom</option>
                      <option value="rotate">Rotate</option>
                      <option value="flicker">Flicker</option>
                      <option value="dissolve">Dissolve</option>
                    </select>
                  </label>
                  <label className="slider-row">
                    <span>Variation strength ({variationStrength.toFixed(2)})</span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={variationStrength}
                      onChange={(e) => setVariationStrength(parseFloat(e.target.value))}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Consistency threshold ({consistencyThreshold.toFixed(2)})</span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={consistencyThreshold}
                      onChange={(e) => setConsistencyThreshold(parseFloat(e.target.value))}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Frame retry budget ({frameRetryBudget})</span>
                    <input
                      type="range"
                      min={0}
                      max={6}
                      step={1}
                      value={frameRetryBudget}
                      onChange={(e) => setFrameRetryBudget(parseInt(e.target.value, 10) || 0)}
                    />
                  </label>
                </>
              )}
              <div className="seed-row">
                <label className="field-row" style={{ flex: 1 }}>
                  <span>Seed {seed !== -1 ? <span className="seed-locked-badge">🔒 Locked</span> : "(random)"}</span>
                  <input
                    type="number"
                    min={-1}
                    max={4294967295}
                    value={seed}
                    onChange={(e) => setSeed(parseInt(e.target.value, 10) || -1)}
                    style={{ width: "140px" }}
                  />
                </label>
                {seed !== -1 && (
                  <button
                    className="seed-reroll-btn"
                    title="Clear seed — next run will use a random seed"
                    onClick={() => setSeed(-1)}
                  >🎲 Re-roll</button>
                )}
              </div>
              <label className="field-row">
                <span>CFG Scale ({cfgScale.toFixed(1)})</span>
                <input
                  type="range"
                  min={1}
                  max={20}
                  step={0.5}
                  value={cfgScale}
                  onChange={(e) => setCfgScale(parseFloat(e.target.value))}
                  style={{ flex: 1 }}
                />
              </label>
            </div>
            </details>

            {validationError && <p className="error">{validationError}</p>}

            <div className="tips">
              <h3>Tips</h3>
              <ul>
                <li>Be specific about silhouette, pose, and held items.</li>
                <li>32-64 px targets usually animate better.</li>
                <li>For animation, choose action-ready poses.</li>
              </ul>
            </div>

          </section>

          <section className="panel results" style={{ animationDelay: "180ms" }}>
            <h2>Output</h2>

            <div className="status-card">
              <p className="status-label">Status</p>
              <p className={`status-value status-${jobState.status}`}>{jobState.status}</p>
              {jobState.jobId && <p className="mono">Job: {jobState.jobId}</p>}
              {["queued", "pending"].includes(jobState.status) && (
                <div className="status-progress-wrap">
                  <div className="status-progress-meta">
                    <span>{progressPhaseLabel ?? (jobState.status === "pending" ? "Generating image" : "Queued")}</span>
                    <span>
                      {elapsedSeconds != null ? `Elapsed ${formatElapsed(elapsedSeconds)}` : ""}
                      {elapsedSeconds != null && etaSeconds != null ? " | " : ""}
                      {etaSeconds != null ? `ETA ca ${formatElapsed(etaSeconds)}` : ""}
                    </span>
                  </div>
                  <div className={`status-progress ${progressPercent == null ? "is-indeterminate" : ""}`}>
                    <div
                      className="status-progress-fill"
                      style={progressPercent == null ? undefined : { width: `${progressPercent}%` }}
                    />
                  </div>
                  {progressPercent != null && jobState.progress?.step != null && jobState.progress?.total != null && (
                    <p className="status-progress-text">
                      Step {jobState.progress.step}/{jobState.progress.total}
                    </p>
                  )}
                </div>
              )}
              {["queued", "pending"].includes(jobState.status) && (
                <button onClick={handleCancelJob}>Cancel Job</button>
              )}
              {jobState.errorMessage && <p className="error">{jobState.errorMessage}</p>}
            </div>

            <div className="preview-card">
              <p className="status-label">Preview</p>
              {activeGeneratedPreviewUrl ? (
                <img src={activeGeneratedPreviewUrl} alt="Generated preview" />
              ) : (
                <div className="empty-preview">Generated preview appears here.</div>
              )}
              {activeGeneratedPreviewUrl && (outputMode.includes("tile") || outputMode === "tile_chunk" || outputMode === "tile_iso") && (
                <details className="seam-preview-details">
                  <summary className="seam-preview-toggle">Tile seam preview (3×3 repeat)</summary>
                  <div className="seam-grid">
                    {Array.from({ length: 9 }).map((_, i) => (
                      <img key={i} src={activeGeneratedPreviewUrl} alt="" className="seam-cell" />
                    ))}
                  </div>
                </details>
              )}
            </div>

            <div className="post-pixelate-card">
              <p className="status-label">Post-generation pixelate</p>
              <p className="muted">
                Apply pixelate after generation when you want to tighten pixel edges without re-running the model.
              </p>
              <label className="slider-row">
                <span>Pixel factor ({postGenerationPixelateFactor.toFixed(1)}x)</span>
                <input
                  type="range"
                  min={1}
                  max={8}
                  step={0.5}
                  value={postGenerationPixelateFactor}
                  onChange={(e) => setPostGenerationPixelateFactor(parseFloat(e.target.value))}
                />
              </label>
              <div className="download-grid">
                <button
                  type="button"
                  onClick={applyPostGenerationPixelate}
                  disabled={!baseGeneratedPreviewUrl || postGenerationPixelateBusy}
                >
                  {postGenerationPixelateBusy ? "Applying..." : "Apply pixelate"}
                </button>
                <button
                  type="button"
                  onClick={resetPostGenerationPixelate}
                  disabled={!postGenerationPixelatedPreviewUrl || postGenerationPixelateBusy}
                >
                  Reset to original
                </button>
                <button
                  type="button"
                  onClick={downloadPostGenerationPixelatedPng}
                  disabled={!postGenerationPixelatedPreviewUrl || postGenerationPixelateBusy}
                >
                  Download pixelated PNG
                </button>
                <button
                  type="button"
                  onClick={sendGeneratedPreviewToEditor}
                  disabled={!activeGeneratedPreviewUrl || postGenerationPixelateBusy}
                >
                  Open in Pixel Editor
                </button>
              </div>
              {postGenerationPixelateError && <p className="error">{postGenerationPixelateError}</p>}
            </div>

            <div className="downloads-card">
              <p className="status-label">Download</p>
              <div className="download-grid">
                {downloadLink("PNG", jobState.result?.download?.png_url)}
                {downloadLink("WebP", jobState.result?.download?.webp_url)}
                {downloadLink("GIF", jobState.result?.download?.gif_url)}
                {downloadLink("Sprite Sheet", jobState.result?.download?.spritesheet_png_url)}
                {downloadLink("Metadata", jobState.result?.download?.metadata_url)}
              </div>
            </div>

            {sourceAnalysis && (
              <div className="source-analysis-card">
                <p className="status-label">Source analysis</p>
                <div className="source-analysis-grid">
                  <p>
                    Pixel art detected: <strong>{sourceAnalysis.is_pixel_art ? "Yes" : "No"}</strong>
                  </p>
                  <p>
                    Palette size: <strong>{sourceAnalysis.detected_palette_size}</strong>
                  </p>
                  <p>
                    Processing: <strong>{sourceAnalysis.processing_applied.join(", ") || "none"}</strong>
                  </p>
                  {sourceAnalysis.original_bounds && (
                    <p>
                      Original bounds: <strong>{sourceAnalysis.original_bounds.width}x{sourceAnalysis.original_bounds.height}</strong>
                    </p>
                  )}
                  {sourceAnalysis.reframed_bounds && (
                    <p>
                      Reframed bounds: <strong>{sourceAnalysis.reframed_bounds.width}x{sourceAnalysis.reframed_bounds.height}</strong>
                    </p>
                  )}
                </div>
              </div>
            )}

            {jobState.result?.frame_urls && jobState.result.frame_urls.length > 0 && (
              <div className="frame-preview-card">
                <p className="status-label">Frames</p>
                <div className="frame-preview-grid">
                  {jobState.result.frame_urls.map((url, index) => (
                    <figure key={url} className="frame-preview-item">
                      <img src={url} alt={`Frame ${index + 1}`} />
                      <figcaption>#{index + 1}</figcaption>
                    </figure>
                  ))}
                </div>
              </div>
            )}

            {frameScores.length > 0 && (
              <div className="frame-score-card">
                <p className="status-label">Frame consistency</p>
                {avgFrameScore != null && <p className="frame-score-summary">Average: {avgFrameScore.toFixed(2)}</p>}
                <div className="frame-score-grid">
                  {frameScores.map((item) => (
                    <div key={`score-${item.frame_index}`} className="frame-score-item">
                      <div className="frame-score-item-head">
                        <span>#{item.frame_index + 1}</span>
                        <strong>{item.score.toFixed(2)}</strong>
                      </div>
                      <div className="frame-score-metrics">
                        <span>Sil {item.silhouette.toFixed(2)}</span>
                        <span>Col {item.color.toFixed(2)}</span>
                        <span>Edge {item.edge.toFixed(2)}</span>
                        <span>Try {item.attempts}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {jobState.result?.seed != null && (
              <div className="seed-card">
                <p className="status-label">Seed used</p>
                <p className="seed-value">
                  {jobState.result.seed}
                  <button
                    className="lock-seed"
                    title="Lock this seed to reproduce the image"
                    onClick={() => setSeed(jobState.result!.seed!)}
                  >
                    🔒 Lock seed
                  </button>
                </p>
                {jobState.result.enhanced_prompt && (
                  <>
                    <p className="status-label" style={{ marginTop: "0.5rem" }}>Enhanced prompt</p>
                    <p className="enhanced-prompt">{jobState.result.enhanced_prompt}</p>
                  </>
                )}
              </div>
            )}

            {variantBatch.length > 1 && (
              <div className="variant-batch-card">
                <p className="status-label">Variant batch ({variantBatch.length})</p>
                <div className="variant-batch-grid">
                  {variantBatch.map((item) => {
                    const imgUrl = item.result?.download?.png_url || item.result?.image_url;
                    const itemSeed = item.result?.seed;
                    return (
                      <div key={item.job_id} className="variant-cell">
                        {imgUrl ? (
                          <img src={imgUrl} alt={`Variant ${item.job_id}`} />
                        ) : (
                          <div className="variant-pending">{item.status}</div>
                        )}
                        <div className="variant-actions">
                          {itemSeed != null && (
                            <button
                              className="variant-use-btn"
                              title="Lock this seed and use these settings"
                              onClick={() => setSeed(itemSeed)}
                            >🔒 Use seed {itemSeed}</button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </section>
        </main>
      )}

      {tab === "library" && (
        <main className="library-page">
          <section className="panel">
            <h2>Library</h2>
            <div className="library-controls">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name, prompt, lane, model"
              />
              <div className="filter-pills">
                <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>
                  All
                </button>
                <button className={filter === "starred" ? "active" : ""} onClick={() => setFilter("starred")}>
                  Starred
                </button>
                <button onClick={clearLibrary}>Clear all</button>
              </div>
              <div className="filter-pills lane-filter-pills">
                <button className={laneFilter === "all" ? "active" : ""} onClick={() => setLaneFilter("all")}>All lanes</button>
                {LIBRARY_LANES.map((l) => (
                  <button key={l} className={laneFilter === l ? "active" : ""} onClick={() => setLaneFilter(l)}>{l}</button>
                ))}
              </div>
            </div>

            <div className="library-grid">
              {filteredHistory.map((item) => (
                <article key={item.job_id} className="library-card">
                  <div className="library-head">
                    <p className="library-title">
                      {item.request.lane.toUpperCase()} / {item.request.output_mode}
                    </p>
                    <button className="star" onClick={() => toggleStar(item.job_id)}>
                      {starredIds.includes(item.job_id) ? "★" : "☆"}
                    </button>
                    <button onClick={() => removeLibraryItem(item.job_id)}>Delete</button>
                  </div>
                  <p className="library-prompt">{item.request.prompt}</p>
                  <p className="library-meta">
                    {item.request.model_family} - {new Date(item.createdAt).toLocaleString()}
                  </p>
                  <p className={`status-value status-${item.status}`}>{item.status}</p>
                  <div className="download-grid">
                    {downloadLink("PNG", item.result?.download?.png_url)}
                    {downloadLink("Sprite Sheet", item.result?.download?.spritesheet_png_url)}
                    {downloadLink("JSON", item.result?.download?.metadata_url)}
                  </div>
                </article>
              ))}
            </div>
          </section>
        </main>
      )}

      {tab === "editor" && (
        <main className="editor-page">
          <section className="panel editor-panel">
            <h2>Pixel Editor</h2>
            <p className="muted">Beta - quick cleanup and blocking sketch tool.</p>

            <div className="editor-import-row">
              <label className="editor-upload-label">
                Import PNG to Editor
                <input type="file" accept="image/png" onChange={handleEditorImageUpload} style={{ display: "none" }} />
              </label>
              <button type="button" onClick={clearEditorImportedImage} disabled={!editorWorkingImageUrl || editorCleanupBusy}>
                Remove imported image
              </button>
            </div>

            {editorWorkingImageUrl && (
              <div className="editor-imported-section">
                <p className="status-label">Imported image cleanup</p>
                <img className="editor-imported-preview" src={editorWorkingImageUrl} alt="Editor imported preview" />
                <div className="editor-cleanup-tools">
                  <label className="slider-row">
                    <span>Pixelate factor ({editorCleanupPixelateFactor.toFixed(1)}x)</span>
                    <input
                      type="range"
                      min={1}
                      max={8}
                      step={0.5}
                      value={editorCleanupPixelateFactor}
                      onChange={(e) => setEditorCleanupPixelateFactor(parseFloat(e.target.value))}
                    />
                  </label>
                  <label className="slider-row">
                    <span>Color simplify step ({editorCleanupColorStep})</span>
                    <input
                      type="range"
                      min={1}
                      max={64}
                      step={1}
                      value={editorCleanupColorStep}
                      onChange={(e) => setEditorCleanupColorStep(parseInt(e.target.value, 10) || 1)}
                    />
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={editorCleanupIsolated}
                      onChange={(e) => setEditorCleanupIsolated(e.target.checked)}
                    />
                    <span>
                      <strong>Remove isolated pixels</strong> - smooth one-off noisy pixels by neighbour majority
                    </span>
                  </label>
                  {editorCleanupIsolated && (
                    <label className="slider-row">
                      <span>Isolation threshold ({editorCleanupNeighborLimit})</span>
                      <input
                        type="range"
                        min={0}
                        max={2}
                        step={1}
                        value={editorCleanupNeighborLimit}
                        onChange={(e) => setEditorCleanupNeighborLimit(parseInt(e.target.value, 10) || 0)}
                      />
                    </label>
                  )}
                </div>
                <div className="download-grid">
                  <button type="button" onClick={applyEditorCleanup} disabled={editorCleanupBusy}>
                    {editorCleanupBusy ? "Applying cleanup..." : "Apply cleanup"}
                  </button>
                  <button type="button" onClick={resetEditorImportedImage} disabled={editorCleanupBusy}>
                    Reset imported image
                  </button>
                  <button type="button" onClick={exportEditorProcessedImage} disabled={editorCleanupBusy}>
                    Export cleaned PNG
                  </button>
                </div>
                {editorCleanupError && <p className="error">{editorCleanupError}</p>}
              </div>
            )}

            {editorWorkingImageUrl && (
              <div className="editor-resize-panel">
                <p className="panel-subtitle">Force resize</p>
                <p className="panel-hint">
                  Trim transparent borders, then downscale to target size preserving subject integrity.
                  Uses iterative bilinear halving + nearest-neighbor snap for clean pixel-art output.
                </p>
                <div className="editor-resize-presets">
                  {[16, 32, 48, 64, 96, 128, 256].map((s) => (
                    <button
                      key={s}
                      type="button"
                      className={editorResizeWidth === s && editorResizeHeight === s ? "active" : ""}
                      onClick={() => { setEditorResizeWidth(s); setEditorResizeHeight(s); }}
                    >
                      {s}×{s}
                    </button>
                  ))}
                </div>
                <div className="editor-resize-custom">
                  <label>
                    W
                    <input
                      type="number"
                      min={1}
                      max={4096}
                      value={editorResizeWidth}
                      onChange={(e) => setEditorResizeWidth(Math.max(1, Number(e.target.value)))}
                    />
                  </label>
                  <label>
                    H
                    <input
                      type="number"
                      min={1}
                      max={4096}
                      value={editorResizeHeight}
                      onChange={(e) => setEditorResizeHeight(Math.max(1, Number(e.target.value)))}
                    />
                  </label>
                  <label className="editor-resize-trim-label">
                    <input
                      type="checkbox"
                      checked={editorResizeTrimAlpha}
                      onChange={(e) => setEditorResizeTrimAlpha(e.target.checked)}
                    />
                    Auto-trim transparent border
                  </label>
                </div>
                <div className="download-grid">
                  <button
                    type="button"
                    onClick={applyEditorResize}
                    disabled={editorResizeBusy}
                  >
                    {editorResizeBusy ? "Resizing…" : `Resize to ${editorResizeWidth}×${editorResizeHeight}`}
                  </button>
                </div>
                {editorResizeError && <p className="error">{editorResizeError}</p>}
              </div>
            )}

            <div className="editor-controls">
              <label>
                Grid
                <select value={editorGrid} onChange={(e) => setEditorGrid(Number(e.target.value))}>
                  <option value={16}>16 x 16</option>
                  <option value={24}>24 x 24</option>
                  <option value={32}>32 x 32</option>
                  <option value={48}>48 x 48</option>
                </select>
              </label>

              <label>
                Color
                <input type="color" value={editorColor} onChange={(e) => setEditorColor(e.target.value)} />
              </label>

              <button onClick={clearEditor}>Clear</button>
              <button className="submit" onClick={exportEditorPng}>
                Export PNG
              </button>
            </div>

            <div className="editor-canvas-wrap">
              <canvas
                ref={canvasRef}
                className="pixel-canvas"
                onPointerDown={onCanvasPointerDown}
                onPointerMove={onCanvasPointerMove}
                onContextMenu={(e) => e.preventDefault()}
              />
            </div>
            <p className="muted">Tip: hold Alt (or right-click drag) to erase pixels.</p>
          </section>
        </main>
      )}
    </div>
  );
}

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    if (!/^data:|^blob:/i.test(src)) {
      img.crossOrigin = "anonymous";
    }
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

async function pixelateImageToDataUrl(src: string, factor: number): Promise<string> {
  const image = await loadImage(src);
  const safeFactor = Math.max(1, Math.min(8, factor));
  const downW = Math.max(1, Math.floor(image.width / safeFactor));
  const downH = Math.max(1, Math.floor(image.height / safeFactor));

  const downscaled = document.createElement("canvas");
  downscaled.width = downW;
  downscaled.height = downH;
  const downCtx = downscaled.getContext("2d");
  if (!downCtx) {
    throw new Error("Could not create downscale canvas context");
  }
  downCtx.imageSmoothingEnabled = false;
  downCtx.drawImage(image, 0, 0, downW, downH);

  const upscaled = document.createElement("canvas");
  upscaled.width = image.width;
  upscaled.height = image.height;
  const upCtx = upscaled.getContext("2d");
  if (!upCtx) {
    throw new Error("Could not create upscale canvas context");
  }
  upCtx.imageSmoothingEnabled = false;
  upCtx.drawImage(downscaled, 0, 0, image.width, image.height);

  return upscaled.toDataURL("image/png");
}

type EditorCleanupOptions = {
  pixelateFactor: number;
  colorStep: number;
  removeIsolated: boolean;
  maxNeighborsSame: number;
};

function removeIsolatedPixelsInPlace(data: Uint8ClampedArray, width: number, height: number, maxNeighborsSame: number): void {
  const source = new Uint8ClampedArray(data);
  const index = (x: number, y: number) => (y * width + x) * 4;

  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const i = index(x, y);
      const alpha = source[i + 3];
      if (alpha < 32) {
        continue;
      }

      const r = source[i];
      const g = source[i + 1];
      const b = source[i + 2];
      let sameCount = 0;
      const neighbors: Array<{ r: number; g: number; b: number; a: number }> = [];
      const coords = [
        [x, y - 1],
        [x + 1, y],
        [x, y + 1],
        [x - 1, y],
      ];

      for (const [nx, ny] of coords) {
        const ni = index(nx, ny);
        const na = source[ni + 3];
        if (na < 32) {
          continue;
        }
        const nr = source[ni];
        const ng = source[ni + 1];
        const nb = source[ni + 2];
        neighbors.push({ r: nr, g: ng, b: nb, a: na });
        if (nr === r && ng === g && nb === b) {
          sameCount += 1;
        }
      }

      if (neighbors.length === 0 || sameCount > maxNeighborsSame) {
        continue;
      }

      const bucket = new Map<string, { count: number; color: { r: number; g: number; b: number; a: number } }>();
      for (const n of neighbors) {
        const key = `${n.r},${n.g},${n.b},${n.a}`;
        const entry = bucket.get(key);
        if (entry) {
          entry.count += 1;
        } else {
          bucket.set(key, { count: 1, color: n });
        }
      }

      let winner: { r: number; g: number; b: number; a: number } | null = null;
      let winnerCount = -1;
      for (const entry of bucket.values()) {
        if (entry.count > winnerCount) {
          winner = entry.color;
          winnerCount = entry.count;
        }
      }

      if (!winner) {
        continue;
      }

      data[i] = winner.r;
      data[i + 1] = winner.g;
      data[i + 2] = winner.b;
      data[i + 3] = winner.a;
    }
  }
}

async function cleanupImageForEditor(src: string, options: EditorCleanupOptions): Promise<string> {
  const image = await loadImage(src);
  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) {
    throw new Error("Could not create cleanup canvas context");
  }

  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(image, 0, 0, image.width, image.height);

  if (options.pixelateFactor > 1.01) {
    const downW = Math.max(1, Math.floor(image.width / options.pixelateFactor));
    const downH = Math.max(1, Math.floor(image.height / options.pixelateFactor));
    const temp = document.createElement("canvas");
    temp.width = downW;
    temp.height = downH;
    const tempCtx = temp.getContext("2d");
    if (!tempCtx) {
      throw new Error("Could not create temp cleanup canvas context");
    }
    tempCtx.imageSmoothingEnabled = false;
    tempCtx.drawImage(canvas, 0, 0, downW, downH);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(temp, 0, 0, canvas.width, canvas.height);
  }

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;
  const step = Math.max(1, options.colorStep);

  if (step > 1) {
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 16) {
        continue;
      }
      data[i] = clamp255(Math.round(data[i] / step) * step);
      data[i + 1] = clamp255(Math.round(data[i + 1] / step) * step);
      data[i + 2] = clamp255(Math.round(data[i + 2] / step) * step);
    }
  }

  if (options.removeIsolated) {
    removeIsolatedPixelsInPlace(data, canvas.width, canvas.height, options.maxNeighborsSame);
  }

  ctx.putImageData(imageData, 0, 0);
  return canvas.toDataURL("image/png");
}

function clamp255(value: number): number {
  return Math.max(0, Math.min(255, value));
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b]
    .map((component) => component.toString(16).padStart(2, "0"))
    .join("")}`;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const value = hex.replace("#", "");
  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);
  return { r, g, b };
}

function rgbToHsl(r: number, g: number, b: number): { h: number; s: number; l: number } {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;

  if (max === min) {
    return { h: 0, s: 0, l };
  }

  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;

  switch (max) {
    case rn:
      h = (gn - bn) / d + (gn < bn ? 6 : 0);
      break;
    case gn:
      h = (bn - rn) / d + 2;
      break;
    default:
      h = (rn - gn) / d + 4;
      break;
  }

  h /= 6;
  return { h: h * 360, s, l };
}

export default App;
