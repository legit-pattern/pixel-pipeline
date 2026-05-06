# Backend Rewrite Decision

Short answer: we could, but we should not.

Current decision: keep the backend in Python and reduce it aggressively instead of splitting the stack across Python and Go.

## The Real Boundary

There are two different backends in this repository:

1. The model runtime.
2. The product backend.

Those are not the same thing.

### Model runtime

The current model runtime is deeply Python-based:

- `torch`
- existing Stable Diffusion WebUI internals
- Python model loading and extension ecosystem
- `fastapi` API layer inside `webui.py`

Rewriting that entire layer in Go would mean rebuilding or replacing a large chunk of the actual inference system, not just cleaning up app code.

That is technically possible, but it is the wrong move for a pixel-art product reset.

### Product backend

This is the layer that should be rewritten.

It should own:

- job submission
- prompt and lane validation
- palette handling
- queueing
- export packing
- sprite-sheet assembly
- metadata sidecars
- auth and rate limits if needed later

That layer can absolutely be written in Go.

## Recommended Decision

Do this:

- keep Python as the only backend language
- strip the current backend down to a narrow pixel-art API
- remove the old frontend and studio assumptions
- keep model execution, job handling, export packaging, and metadata in one Python service

Do not do this:

- add a Go control plane unless Python becomes a clear operational bottleneck later
- try to port Stable Diffusion inference and extension behavior into Go in the first rewrite

## Why Staying In Python Is Better Right Now

Python is the right fit for the rewritten backend right now because:

- the model runtime is already Python
- the checkpoint and inference ecosystem is already Python
- image processing and export helpers are already easiest to source in Python
- there is no cross-language boundary to debug
- the rework stays focused on deleting scope instead of adding plumbing

## Why Go Is A Bad First Fit For Inference

Go is not the path of least resistance for:

- PyTorch-native model execution
- reuse of existing checkpoint-loading behavior
- reuse of the current extension ecosystem
- reuse of current image-model tuning scripts

If we force Go to own inference immediately, the rework becomes a model-platform rewrite.

That is much larger than a product cleanup.

## Best Architecture

### Layer 1: Python Pixel API

Owns:

- `/api/pixel/jobs/generate`
- `/api/pixel/jobs/{id}`
- `/api/pixel/jobs/{id}/cancel`
- `/api/pixel/models`
- `/api/pixel/palettes`
- `/api/pixel/export/spritesheet`

### Layer 2: Python orchestration

Owns:

- lane-specific prompt assembly
- job queueing
- model-family routing
- export packing
- metadata sidecars

### Layer 3: Python inference adapter

Owns:

- calls into the current model runtime
- checkpoint loading
- txt2img or img2img generation
- pixel-native model execution

## Migration Plan

### Phase 1

Keep the current Python runtime and build a thin Python pixel API around it.

Outcome:

- immediate cleanup of product backend code
- clean contract for the new frontend
- no cross-language complexity

### Phase 2

Reduce the Python side from legacy WebUI assumptions to a narrower worker-oriented service.

Outcome:

- less legacy surface
- fewer WebUI assumptions
- one backend language end-to-end

### Phase 3

Only revisit Go if Python becomes a clear deployment or concurrency bottleneck.

## Recommendation For This Repo

Keep the backend in Python.

Delete the old frontend surface.

Rewrite the remaining backend into a smaller pixel-specific API instead of multiplying languages.