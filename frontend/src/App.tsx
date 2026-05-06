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
  fetchCharacterDNA,
  extractPaletteFromFile,
  fetchExportFormats,
  fetchJobs,
  fetchModels,
  fetchPalettes,
  type AssetPreset,
  type CharacterDNA,
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

const STORAGE_KEY = "pixel-studio-job-history";
const STARS_KEY = "pixel-studio-starred-jobs";
const SETTINGS_KEY = "pixel-studio-settings";
const HISTORY_PERSIST_LIMIT = 24;

const TEMPLATES = {
  hero: "Create a single-frame game-ready pixel art main character sprite for an isometric 2.5D action RPG. Young male wanderer, practical layered traveler clothing, 3/4 view, neutral ready stance, clean pixel art, 64x64, transparent background, no text, no UI, no environment.",
  frog: "Create a game-ready pixel art enemy sprite sheet for an isometric 2.5D action RPG. Frog-like tower guardian scout, 12 frames total (4 idle, 4 walk, 4 attack), each 64x64, single-row spritesheet, transparent background, no text, no UI, no environment.",
};

const DEFAULT_MODELS: ModelOption[] = [
  {
    id: "pixel_art_diffusion_xl",
    label: "Pixel Art Diffusion XL SpriteShaper (recommended checkpoint)",
    quality: "pixel-checkpoint",
  },
  { id: "sdxl_base", label: "PAD-XL SpriteShaper (active base)", quality: "pixel-checkpoint" },
  { id: "sdxl_base_legacy", label: "SDXL Base 1.0 (legacy checkpoint)", quality: "balanced" },
  { id: "sdxl_pixel_art", label: "SDXL Base + 64x64 Pixel Art LoRA", quality: "pixel-optimized" },
  { id: "sdxl_swordsman", label: "SDXL + Swordsman LoRA", quality: "character-optimized" },
  { id: "sdxl_jinja_shrine", label: "SDXL + Jinja Shrine Zen LoRA", quality: "environment-optimized" },
];

const DEFAULT_ASSET_PRESETS: AssetPreset[] = [
  { id: "sprite", label: "Sprite" },
  { id: "tile", label: "Tile" },
  { id: "prop", label: "Prop" },
  { id: "effect", label: "Effect" },
  { id: "ui", label: "UI" },
];

const DEFAULT_CHARACTER_DNA: CharacterDNA[] = [
  { id: "frog_guardian", label: "Frog Guardian" },
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

type StudioSettings = {
  tab: Tab;
  theme: Theme;
  search: string;
  filter: "all" | "starred";
  prompt: string;
  negativePrompt: string;
  lane: string;
  outputMode: string;
  outputFormat: string;
  modelFamily: string;
  assetPreset: string;
  characterDnaId: string;
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
  const [palettes, setPalettes] = useState<PalettePreset[]>(DEFAULT_PALETTES);
  const [assetPresets, setAssetPresets] = useState<AssetPreset[]>(DEFAULT_ASSET_PRESETS);
  const [characterDna, setCharacterDna] = useState<CharacterDNA[]>(DEFAULT_CHARACTER_DNA);
  const [formats, setFormats] = useState<ExportFormat[]>(DEFAULT_FORMATS);

  const [history, setHistory] = useState<JobRecord[]>(readHistory());
  const [libraryJobs, setLibraryJobs] = useState<JobRecord[]>([]);
  const [libraryLoading, setLibraryLoading] = useState<boolean>(false);
  const [starredIds, setStarredIds] = useState<string[]>(readStarred());

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
  const [characterDnaId, setCharacterDnaId] = useState<string>(savedSettings.characterDnaId ?? "");

  const [palettePreset, setPalettePreset] = useState<string>(savedSettings.palettePreset ?? "steam_lords");
  const [paletteSize, setPaletteSize] = useState<number>(savedSettings.paletteSize ?? 16);
  const [customColors, setCustomColors] = useState<string[]>(savedSettings.customColors ?? []);

  const [frameWidth, setFrameWidth] = useState<number>(savedSettings.frameWidth ?? 64);
  const [frameHeight, setFrameHeight] = useState<number>(savedSettings.frameHeight ?? 64);
  const [columns, setColumns] = useState<number>(savedSettings.columns ?? 12);
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
  const [enhancePrompt, setEnhancePrompt] = useState<boolean>(savedSettings.enhancePrompt ?? true);
  const [autoPipeline, setAutoPipeline] = useState<boolean>(savedSettings.autoPipeline ?? true);
  const [keyframeFirst, setKeyframeFirst] = useState<boolean>(savedSettings.keyframeFirst ?? true);
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

  const [editorGrid, setEditorGrid] = useState<number>(savedSettings.editorGrid ?? 24);
  const [editorColor, setEditorColor] = useState<string>(savedSettings.editorColor ?? "#78b0a6");
  const [editorPixels, setEditorPixels] = useState<string[]>(
    savedSettings.editorPixels ?? Array.from({ length: (savedSettings.editorGrid ?? 24) * (savedSettings.editorGrid ?? 24) }, () => ""),
  );
  const [isDrawing, setIsDrawing] = useState<boolean>(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const editorGridInitializedRef = useRef<boolean>(false);

  // ── job poller ─────────────────────────────────────────────────────────────
  const handleJobUpdate = useCallback(
    (patch: Pick<JobRecord, "job_id" | "status" | "result" | "error">) => {
      setHistory((prev) => applyJobPatch(prev, patch));
      setLibraryJobs((prev) => applyJobPatch(prev, patch));
    },
    [],
  );
  const { state: jobState, submit: submitJob, cancel: cancelJob } = useJobPoller(handleJobUpdate);

  const availableModels = models.length > 0 ? models : DEFAULT_MODELS;
  const availablePalettes = palettes.length > 0 ? palettes : DEFAULT_PALETTES;
  const availableAssetPresets = assetPresets.length > 0 ? assetPresets : DEFAULT_ASSET_PRESETS;
  const availableCharacterDna = characterDna.length > 0 ? characterDna : DEFAULT_CHARACTER_DNA;
  const availableFormats = formats.length > 0 ? formats : DEFAULT_FORMATS;
  const frameScores = useMemo(() => getAnimationFrameScores(jobState.result?.metadata), [jobState.result?.metadata]);
  const sourceAnalysis = useMemo(() => getSourceAnalysis(jobState.result?.metadata), [jobState.result?.metadata]);
  const avgFrameScore = useMemo(() => {
    if (frameScores.length === 0) {
      return null;
    }
    const total = frameScores.reduce((acc, item) => acc + item.score, 0);
    return total / frameScores.length;
  }, [frameScores]);

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
      prompt,
      negativePrompt,
      lane,
      outputMode,
      outputFormat,
      modelFamily,
      assetPreset,
      characterDnaId,
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
    characterDnaId,
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

    setModelFamily("sdxl_base_legacy");
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
      fetchCharacterDNA(),
      fetchExportFormats(),
    ])
      .then(([m, p, ap, dna, f]) => {
        setModels(m.length ? m : DEFAULT_MODELS);
        setPalettes(p.length ? p : DEFAULT_PALETTES);
        setAssetPresets(ap.length ? ap : DEFAULT_ASSET_PRESETS);
        setCharacterDna(dna.length ? dna : DEFAULT_CHARACTER_DNA);
        setFormats(f.length ? f : DEFAULT_FORMATS);
      })
      .catch(() => {
        setModels(DEFAULT_MODELS);
        setPalettes(DEFAULT_PALETTES);
        setAssetPresets(DEFAULT_ASSET_PRESETS);
        setCharacterDna(DEFAULT_CHARACTER_DNA);
        setFormats(DEFAULT_FORMATS);
      });
  }, []);

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
    if (tab !== "library") {
      return;
    }

    const controller = new AbortController();
    Promise.resolve().then(() => setLibraryLoading(true));

    void fetchJobs({ search, signal: controller.signal })
      .then((jobs) => setLibraryJobs(jobs))
      .catch(() => setLibraryJobs([]))
      .finally(() => setLibraryLoading(false));

    return () => controller.abort();
  }, [tab, search]);

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
      asset_preset: assetPreset,
      character_dna_id: characterDnaId || null,
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
      const record = await submitJob(request);
      setHistory((prev) => [record, ...prev].slice(0, 150));
    } catch {
      // error already reflected in jobState.errorMessage
    }
  }

  function toggleStar(jobId: string) {
    setStarredIds((prev) =>
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [jobId, ...prev],
    );
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

    const source = libraryJobs.length > 0 ? libraryJobs : history;

    return source.filter((item) => {
      if (filter === "starred" && !starredIds.includes(item.job_id)) {
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
  }, [libraryJobs, history, search, filter, starredIds]);

  function downloadLink(label: string, url?: string) {
    const disabled = !url;
    return (
      <a
        key={label}
        className={`download-pill${disabled ? " disabled" : ""}`}
        href={url || "#"}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => {
          if (disabled) {
            e.preventDefault();
          }
        }}
      >
        {label}
      </a>
    );
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

            <label>
              Style profile
              <select value={modelFamily} onChange={(e) => setModelFamily(e.target.value)}>
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">
              PAD-XL SpriteShaper is now the active foundation. Choose one profile/checkpoint per run; profiles are not combined automatically.
            </p>

            <div className="inline-grid two">
              <label>
                Asset preset
                <select value={assetPreset} onChange={(e) => setAssetPreset(e.target.value)}>
                  <option value="auto">Auto (from lane)</option>
                  {availableAssetPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.label}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Character DNA
                <select value={characterDnaId} onChange={(e) => setCharacterDnaId(e.target.value)}>
                  <option value="">None</option>
                  {availableCharacterDna.map((dna) => (
                    <option key={dna.id} value={dna.id}>
                      {dna.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label>
              Prompt *
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={5} />
            </label>

            <div className="template-row">
              <button onClick={() => setTemplate("hero")}>Character template</button>
              <button onClick={() => setTemplate("frog")}>Enemy sheet template</button>
            </div>

            <label>
              Negative prompt
              <textarea value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} rows={3} />
            </label>

            <div className="inline-grid three">
              <label>
                Lane
                <select value={lane} onChange={(e) => setLane(e.target.value)}>
                  <option value="sprite">Sprite</option>
                  <option value="world">World</option>
                  <option value="prop">Prop</option>
                  <option value="ui">UI</option>
                  <option value="portrait">Portrait</option>
                </select>
              </label>

              <label>
                Output mode
                <select value={outputMode} onChange={(e) => setOutputMode(e.target.value)}>
                  <option value="single_sprite">Single Sprite</option>
                  <option value="sprite_sheet">Sprite Sheet</option>
                  <option value="prop_sheet">Prop Sheet</option>
                  <option value="tile_chunk">Tile Chunk</option>
                  <option value="ui_module">UI Module</option>
                </select>
              </label>

              <label>
                Download as
                <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value)}>
                  {availableFormats.map((format) => (
                    <option key={format.id} value={format.id}>
                      {format.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="subpanel">
              <h3>Colors</h3>

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
              <h3>Sheet</h3>
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

            <div className="subpanel">
              <h3>Tile controls</h3>
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
              </div>
            )}

            <div className="subpanel">
              <h3>Post-processing</h3>
              <p className="muted">
                All steps are opt-in. Leave all off if the image already looks right – you can always re-generate.
              </p>
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
              <label className="field-row">
                <span>Seed (-1 = random)</span>
                <input
                  type="number"
                  min={-1}
                  max={4294967295}
                  value={seed}
                  onChange={(e) => setSeed(parseInt(e.target.value, 10) || -1)}
                  style={{ width: "140px" }}
                />
              </label>
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

            {validationError && <p className="error">{validationError}</p>}

            <div className="tips">
              <h3>Tips</h3>
              <ul>
                <li>Be specific about silhouette, pose, and held items.</li>
                <li>32-64 px targets usually animate better.</li>
                <li>For animation, choose action-ready poses.</li>
              </ul>
            </div>

            <button className="submit" onClick={handleSubmitJob}>
              Submit Generation
            </button>
          </section>

          <section className="panel results" style={{ animationDelay: "180ms" }}>
            <h2>Output</h2>

            <div className="status-card">
              <p className="status-label">Status</p>
              <p className={`status-value status-${jobState.status}`}>{jobState.status}</p>
              {jobState.jobId && <p className="mono">Job: {jobState.jobId}</p>}
              {["queued", "pending"].includes(jobState.status) && (
                <button onClick={handleCancelJob}>Cancel Job</button>
              )}
              {jobState.errorMessage && <p className="error">{jobState.errorMessage}</p>}
            </div>

            <div className="preview-card">
              <p className="status-label">Preview</p>
              {jobState.result?.download?.png_url ? (
                <img src={jobState.result.download.png_url} alt="Generated preview" />
              ) : (
                <div className="empty-preview">Generated preview appears here.</div>
              )}
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
                    Lock seed
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
              </div>
            </div>

            {libraryLoading && <p className="muted">Syncing jobs...</p>}

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
                  </div>
                  <p className="library-prompt">{item.request.prompt}</p>
                  <p className="library-meta">
                    {item.request.model_family} - {new Date(item.createdAt).toLocaleString()}
                  </p>
                  <p className={`status-value status-${item.status}`}>{item.status}</p>
                  <div className="download-grid">
                    {downloadLink("PNG", item.result?.download?.png_url)}
                    {downloadLink("Sheet", item.result?.download?.spritesheet_png_url)}
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
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
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
