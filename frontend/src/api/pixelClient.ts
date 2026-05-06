/**
 * pixelClient.ts – typed API client for the Pixel Studio backend.
 *
 * All network calls live here. Components and hooks only import from this
 * module, never calling fetch() directly.
 */

export type ModelOption = {
  id: string;
  label: string;
  quality?: string;
};

export type AssetPreset = {
  id: string;
  label: string;
  prompt_tags?: string[];
  post_processing?: Record<string, unknown>;
};

export type CharacterDNA = {
  id: string;
  label: string;
  silhouette?: string;
  proportions?: string;
  eyes?: string;
  texture?: string;
  biome?: string;
  prompt_tags?: string[];
};

export type PalettePreset = {
  id: string;
  label: string;
  size: number;
  colors: string[];
  outline?: string | null;
  highlight?: string | null;
  shadow?: string | null;
  dither?: string;
  max_colors?: number;
  contrast?: string;
  gamma?: number;
  style?: string;
};

export type ExportFormat = {
  id: "png" | "webp" | "gif" | "spritesheet_png";
  label: string;
};

export type PaletteInput = {
  preset: string;
  size: number;
  colors: string[];
};

export type SheetInput = {
  frame_width: number;
  frame_height: number;
  columns: number;
  rows: number;
  padding: number;
};

export type TileOptionsInput = {
  tile_size: number;
  seamless_mode: boolean;
  autotile_mask: string;
  variation_count: number;
  noise_level: number;
  edge_softening: number;
};

export type PostProcessingInput = {
  /** Multi-step pixelation: sharpen → NEAREST downscale → optional palette snap. */
  pixelate: boolean;
  /** Remove background via rembg. Silently skipped if rembg is not installed. */
  remove_background: boolean;
  /** Floyd-Steinberg dither to palette.colors. No-op if palette.colors is empty. */
  quantize_palette: boolean;
  /** Cleanup heuristics: anti-alias snap, isolated pixel cleanup, and edge strengthening. */
  pixel_cleanup: boolean;
  /** Sprite contour reinforcement strength (0-3). */
  outline_strength: number;
  /** Anti-alias cleanup aggressiveness (0-3). */
  anti_alias_level: number;
  /** Isolated-pixel cluster smoothing aggressiveness (0-3). */
  cluster_smoothing: number;
  /** Global cleanup contrast boost (0-2). */
  contrast_boost: number;
  /** Dark-edge reinforcement amount (0-2). */
  shadow_reinforcement: number;
  /** Inner-edge highlight reinforcement amount (0-2). */
  highlight_reinforcement: number;
  /** Palette enforcement strictness (0-2). */
  palette_strictness: number;
  /** Pixelation strength multiplier. 1.0 = frame size. Lower = bigger pixel cells. */
  pixelate_strength: number;
};

export type GenerateRequest = {
  prompt: string;
  negative_prompt: string;
  lane: string;
  output_mode: string;
  output_format: string;
  palette: PaletteInput;
  sheet: SheetInput;
  tile_options: TileOptionsInput;
  post_processing: PostProcessingInput;
  source_image_base64: string | null;
  model_family: string;
  /** RNG seed. -1 = random. Set a fixed value to reproduce the same image. */
  seed: number;
  /** Classifier-free guidance scale. Higher = follows prompt more strictly. */
  cfg_scale: number;
  /** Inject lane-appropriate pixel-art keywords into the prompt automatically. */
  enhance_prompt: boolean;
  /** Use the recommended pixel chain: 8x generation, pixelation, and palette snap (if colors set). */
  auto_pipeline: boolean;
  /** Asset-type preset id (sprite/tile/prop/effect/ui) or auto. */
  asset_preset?: string;
  /** Optional character DNA profile id. */
  character_dna_id?: string | null;
  /** Keyframe-first mode for multi-frame outputs. */
  keyframe_first?: boolean;
  /** Motion deviation strength for derived frames (0-1). */
  variation_strength?: number;
  /** Minimum frame consistency score before accepting frame (0-1). */
  consistency_threshold?: number;
  /** Number of retries per frame in keyframe-first mode. */
  frame_retry_budget?: number;
  /** Motion prior hint: auto|bloom|pulse|sway|rotate|bounce|flicker|dissolve. */
  motion_prior?: string;
};

export type JobResult = {
  image_url?: string;
  spritesheet_url?: string;
  frame_urls?: string[];
  seed?: number;
  enhanced_prompt?: string;
  download?: {
    png_url?: string;
    webp_url?: string;
    gif_url?: string;
    spritesheet_png_url?: string;
    metadata_url?: string;
  };
  metadata?: Record<string, unknown>;
};

export type JobRecord = {
  job_id: string;
  status: string;
  request: GenerateRequest;
  result?: JobResult | null;
  error?: { code?: string; message?: string } | null;
  createdAt: string;
};

export type JobStatus = {
  job_id: string;
  status: string;
  result?: JobResult;
  error?: { code?: string; message?: string };
};

// ── helpers ───────────────────────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    const detail = body?.detail ? `: ${body.detail}` : "";
    throw new Error(`HTTP ${res.status}${detail}`);
  }
  return res.json() as Promise<T>;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function fetchModels(): Promise<ModelOption[]> {
  const data = await handleResponse<{ models: ModelOption[] }>(
    await fetch("/api/pixel/models"),
  );
  return data.models;
}

export async function fetchPalettes(): Promise<PalettePreset[]> {
  const data = await handleResponse<{ palettes: PalettePreset[] }>(
    await fetch("/api/pixel/palettes"),
  );
  return data.palettes;
}

export async function fetchAssetPresets(): Promise<AssetPreset[]> {
  const data = await handleResponse<{ presets: AssetPreset[] }>(
    await fetch("/api/pixel/asset-presets"),
  );
  return data.presets;
}

export async function fetchCharacterDNA(): Promise<CharacterDNA[]> {
  const data = await handleResponse<{ character_dna: CharacterDNA[] }>(
    await fetch("/api/pixel/character-dna"),
  );
  return data.character_dna;
}

export async function fetchExportFormats(): Promise<ExportFormat[]> {
  const data = await handleResponse<{ formats: ExportFormat[] }>(
    await fetch("/api/pixel/export-formats"),
  );
  return data.formats;
}

export async function submitGenerate(
  request: GenerateRequest,
): Promise<{ job_id: string; status: string }> {
  return handleResponse(
    await fetch("/api/pixel/jobs/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }),
  );
}

export async function pollJob(jobId: string): Promise<JobStatus> {
  return handleResponse(await fetch(`/api/pixel/jobs/${jobId}`));
}

export async function cancelJob(jobId: string): Promise<void> {
  await fetch(`/api/pixel/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function fetchJobs(opts: {
  limit?: number;
  search?: string;
  signal?: AbortSignal;
}): Promise<JobRecord[]> {
  const url = new URL("/api/pixel/jobs", window.location.origin);
  url.searchParams.set("limit", String(opts.limit ?? 120));
  if (opts.search?.trim()) {
    url.searchParams.set("search", opts.search.trim());
  }
  const data = await handleResponse<{ jobs: any[] }>(
    await fetch(`${url.pathname}${url.search}`, { signal: opts.signal }),
  );
  return (data.jobs ?? []).map(normalizeJobRecord);
}

/**
 * Upload a PNG swatch image and return the extracted hex colour list.
 * Uses the backend `/api/pixel/palettes/from-image` endpoint which does a
 * server-side pixel scan – no canvas API required.
 */
export async function extractPaletteFromFile(
  file: File,
): Promise<{ colors: string[]; count: number }> {
  const body = new FormData();
  body.append("file", file);
  return handleResponse(
    await fetch("/api/pixel/palettes/from-image", {
      method: "POST",
      body,
    }),
  );
}

// ── record normalizer ─────────────────────────────────────────────────────────

export function normalizeJobRecord(input: any): JobRecord {
  return {
    job_id: String(input.job_id ?? ""),
    status: String(input.status ?? "queued"),
    request: input.request,
    result: input.result ?? null,
    error: input.error ?? null,
    createdAt: String(input.created_at ?? input.createdAt ?? new Date().toISOString()),
  };
}
