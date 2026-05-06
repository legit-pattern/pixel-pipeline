import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type PointerEvent,
} from "react";

type Tab = "app" | "library" | "editor";
type Theme = "light" | "dark";

type ModelOption = {
  id: string;
  label: string;
  quality?: string;
};

type PalettePreset = {
  id: string;
  label: string;
  size: number;
  colors: string[];
};

type ExportFormat = {
  id: "png" | "webp" | "gif" | "spritesheet_png";
  label: string;
};

type GenerateRequest = {
  prompt: string;
  negative_prompt: string;
  lane: string;
  output_mode: string;
  output_format: string;
  palette: {
    preset: string;
    size: number;
    colors: string[];
  };
  sheet: {
    frame_width: number;
    frame_height: number;
    columns: number;
    rows: number;
    padding: number;
  };
  source_image_base64: string | null;
  model_family: string;
};

type JobResult = {
  image_url?: string;
  spritesheet_url?: string;
  download?: {
    png_url?: string;
    webp_url?: string;
    gif_url?: string;
    spritesheet_png_url?: string;
    metadata_url?: string;
  };
  metadata?: Record<string, unknown>;
};

type JobRecord = {
  job_id: string;
  status: string;
  request: GenerateRequest;
  result?: JobResult | null;
  error?: { code?: string; message?: string } | null;
  createdAt: string;
};

const STORAGE_KEY = "pixel-studio-job-history";
const STARS_KEY = "pixel-studio-starred-jobs";

const TEMPLATES = {
  hero: "Create a single-frame game-ready pixel art main character sprite for an isometric 2.5D action RPG. Young male wanderer, practical layered traveler clothing, 3/4 view, neutral ready stance, clean pixel art, 48x48, transparent background, no text, no UI, no environment.",
  frog: "Create a game-ready pixel art enemy sprite sheet for an isometric 2.5D action RPG. Frog-like tower guardian scout, 12 frames total (4 idle, 4 walk, 4 attack), each 48x48, single-row spritesheet, transparent background, no text, no UI, no environment.",
};

const DEFAULT_MODELS: ModelOption[] = [
  { id: "sdxl_base", label: "SDXL Base 1.0 (no LoRA)", quality: "balanced" },
  { id: "sdxl_pixel_art", label: "SDXL + 64x64 Pixel Art LoRA", quality: "pixel-optimized" },
  { id: "sdxl_swordsman", label: "SDXL + Swordsman LoRA", quality: "character-optimized" },
  { id: "sdxl_jinja_shrine", label: "SDXL + Jinja Shrine Zen LoRA", quality: "environment-optimized" },
];

const DEFAULT_PALETTES: PalettePreset[] = [
  { id: "custom", label: "Custom", size: 16, colors: [] },
  { id: "gameboy", label: "Game Boy", size: 4, colors: ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"] },
];

const DEFAULT_FORMATS: ExportFormat[] = [
  { id: "png", label: "PNG (single frame)" },
  { id: "webp", label: "WebP (animated or still)" },
  { id: "gif", label: "GIF (animated)" },
  { id: "spritesheet_png", label: "Sprite Sheet PNG" },
];

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

function normalizeJob(input: any): JobRecord {
  return {
    job_id: String(input.job_id ?? ""),
    status: String(input.status ?? "queued"),
    request: input.request,
    result: input.result ?? null,
    error: input.error ?? null,
    createdAt: String(input.created_at ?? input.createdAt ?? new Date().toISOString()),
  };
}

function App() {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;

  const [tab, setTab] = useState<Tab>("app");
  const [theme, setTheme] = useState<Theme>(prefersDark ? "dark" : "light");

  const [models, setModels] = useState<ModelOption[]>(DEFAULT_MODELS);
  const [palettes, setPalettes] = useState<PalettePreset[]>(DEFAULT_PALETTES);
  const [formats, setFormats] = useState<ExportFormat[]>(DEFAULT_FORMATS);

  const [history, setHistory] = useState<JobRecord[]>(readHistory());
  const [libraryJobs, setLibraryJobs] = useState<JobRecord[]>([]);
  const [libraryLoading, setLibraryLoading] = useState<boolean>(false);
  const [starredIds, setStarredIds] = useState<string[]>(readStarred());

  const [activeJobId, setActiveJobId] = useState<string>("");
  const [jobStatus, setJobStatus] = useState<string>("idle");
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [jobError, setJobError] = useState<string>("");

  const [search, setSearch] = useState<string>("");
  const [filter, setFilter] = useState<"all" | "starred">("all");

  const [prompt, setPrompt] = useState<string>(TEMPLATES.hero);
  const [negativePrompt, setNegativePrompt] = useState<string>(
    "blurry, painterly, 3d render, text, logo, watermark",
  );
  const [lane, setLane] = useState<string>("sprite");
  const [outputMode, setOutputMode] = useState<string>("sprite_sheet");
  const [outputFormat, setOutputFormat] = useState<string>("spritesheet_png");
  const [modelFamily, setModelFamily] = useState<string>("sdxl_base");

  const [palettePreset, setPalettePreset] = useState<string>("custom");
  const [paletteSize, setPaletteSize] = useState<number>(24);
  const [customColors, setCustomColors] = useState<string[]>(["#0f1312", "#344a46", "#7f8f74", "#c7c2a8"]);

  const [frameWidth, setFrameWidth] = useState<number>(48);
  const [frameHeight, setFrameHeight] = useState<number>(48);
  const [columns, setColumns] = useState<number>(12);
  const [rows, setRows] = useState<number>(1);
  const [padding, setPadding] = useState<number>(0);

  const [sourcePreview, setSourcePreview] = useState<string>("");
  const [sourceImageBase64, setSourceImageBase64] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string>("");

  const [editorGrid, setEditorGrid] = useState<number>(24);
  const [editorColor, setEditorColor] = useState<string>("#78b0a6");
  const [editorPixels, setEditorPixels] = useState<string[]>(() =>
    Array.from({ length: 24 * 24 }, () => ""),
  );
  const [isDrawing, setIsDrawing] = useState<boolean>(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const availableModels = models.length > 0 ? models : DEFAULT_MODELS;
  const availablePalettes = palettes.length > 0 ? palettes : DEFAULT_PALETTES;
  const availableFormats = formats.length > 0 ? formats : DEFAULT_FORMATS;

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
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    localStorage.setItem(STARS_KEY, JSON.stringify(starredIds));
  }, [starredIds]);

  useEffect(() => {
    void Promise.all([
      fetch("/api/pixel/models").then((r) => r.json()),
      fetch("/api/pixel/palettes").then((r) => r.json()),
      fetch("/api/pixel/export-formats").then((r) => r.json()),
    ])
      .then(([modelsData, palettesData, formatsData]) => {
        setModels(modelsData.models?.length ? modelsData.models : DEFAULT_MODELS);
        setPalettes(palettesData.palettes?.length ? palettesData.palettes : DEFAULT_PALETTES);
        setFormats(formatsData.formats?.length ? formatsData.formats : DEFAULT_FORMATS);
      })
      .catch(() => {
        setModels(DEFAULT_MODELS);
        setPalettes(DEFAULT_PALETTES);
        setFormats(DEFAULT_FORMATS);
        setJobError("Could not load backend option lists. Using local defaults.");
      });
  }, []);

  useEffect(() => {
    if (!activeJobId || !["queued", "pending"].includes(jobStatus)) {
      return;
    }

    const interval = setInterval(() => {
      void pollJob(activeJobId);
    }, 3500);

    return () => clearInterval(interval);
  }, [activeJobId, jobStatus]);

  useEffect(() => {
    if (tab !== "library") {
      return;
    }

    const controller = new AbortController();
    setLibraryLoading(true);

    const url = new URL("/api/pixel/jobs", window.location.origin);
    url.searchParams.set("limit", "120");
    if (search.trim()) {
      url.searchParams.set("search", search.trim());
    }

    void fetch(`${url.pathname}${url.search}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Failed with ${r.status}`))))
      .then((data: { jobs?: any[] }) => {
        const normalized = (data.jobs ?? []).map(normalizeJob);
        setLibraryJobs(normalized);
      })
      .catch(() => {
        setLibraryJobs([]);
      })
      .finally(() => setLibraryLoading(false));

    return () => controller.abort();
  }, [tab, search]);

  useEffect(() => {
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

  async function submitJob() {
    setValidationError("");
    setJobError("");
    setJobResult(null);

    if (!prompt.trim()) {
      setValidationError("Prompt is required.");
      return;
    }

    const request: GenerateRequest = {
      prompt: prompt.trim(),
      negative_prompt: negativePrompt,
      lane,
      output_mode: outputMode,
      output_format: outputFormat,
      model_family: modelFamily,
      source_image_base64: sourceImageBase64,
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
      setJobStatus("queued");
      const response = await fetch("/api/pixel/jobs/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const maybeJson = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        const detail = maybeJson?.detail ? `: ${maybeJson.detail}` : "";
        throw new Error(`Generate failed with status ${response.status}${detail}`);
      }

      const data = (await response.json()) as { job_id: string; status: string };
      setActiveJobId(data.job_id);
      setJobStatus(data.status);

      const record: JobRecord = {
        job_id: data.job_id,
        status: data.status,
        request,
        createdAt: new Date().toISOString(),
      };
      setHistory((prev) => [record, ...prev].slice(0, 150));

      await pollJob(data.job_id);
    } catch (error) {
      setJobStatus("failure");
      setJobError(error instanceof Error ? error.message : "Unknown error");
    }
  }

  async function pollJob(jobId: string) {
    const response = await fetch(`/api/pixel/jobs/${jobId}`);
    if (!response.ok) {
      throw new Error(`Polling failed with status ${response.status}`);
    }
    const data = (await response.json()) as {
      job_id: string;
      status: string;
      result?: JobResult;
      error?: { code?: string; message?: string };
    };

    setJobStatus(data.status);
    setJobResult(data.result ?? null);
    setJobError(data.error?.message ?? "");

    const applyUpdate = (item: JobRecord): JobRecord =>
      item.job_id === data.job_id
        ? {
            ...item,
            status: data.status,
            result: data.result,
            error: data.error,
          }
        : item;

    setHistory((prev) => prev.map(applyUpdate));
    setLibraryJobs((prev) => prev.map(applyUpdate));
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

      // Quantize lightly to avoid near-duplicate shades from anti-aliasing.
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

  async function cancelJob() {
    if (!activeJobId) {
      return;
    }
    const response = await fetch(`/api/pixel/jobs/${activeJobId}/cancel`, {
      method: "POST",
    });
    if (response.ok) {
      setJobStatus("cancelled");
    }
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
              SDXL Base 1.0 is the foundation. Choose one profile/checkpoint per run; profiles are not combined automatically.
            </p>

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

            {validationError && <p className="error">{validationError}</p>}

            <div className="tips">
              <h3>Tips</h3>
              <ul>
                <li>Be specific about silhouette, pose, and held items.</li>
                <li>32-64 px targets usually animate better.</li>
                <li>For animation, choose action-ready poses.</li>
              </ul>
            </div>

            <button className="submit" onClick={submitJob}>
              Submit Generation
            </button>
          </section>

          <section className="panel results" style={{ animationDelay: "180ms" }}>
            <h2>Output</h2>

            <div className="status-card">
              <p className="status-label">Status</p>
              <p className={`status-value status-${jobStatus}`}>{jobStatus}</p>
              {activeJobId && <p className="mono">Job: {activeJobId}</p>}
              {["queued", "pending"].includes(jobStatus) && (
                <button onClick={cancelJob}>Cancel Job</button>
              )}
              {jobError && <p className="error">{jobError}</p>}
            </div>

            <div className="preview-card">
              <p className="status-label">Preview</p>
              {jobResult?.download?.png_url ? (
                <img src={jobResult.download.png_url} alt="Generated preview" />
              ) : (
                <div className="empty-preview">Generated preview appears here.</div>
              )}
            </div>

            <div className="downloads-card">
              <p className="status-label">Download</p>
              <div className="download-grid">
                {downloadLink("PNG", jobResult?.download?.png_url)}
                {downloadLink("WebP", jobResult?.download?.webp_url)}
                {downloadLink("GIF", jobResult?.download?.gif_url)}
                {downloadLink("Sprite Sheet", jobResult?.download?.spritesheet_png_url)}
                {downloadLink("Metadata", jobResult?.download?.metadata_url)}
              </div>
            </div>
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
  let h = 0;

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
