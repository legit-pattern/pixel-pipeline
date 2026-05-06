# Clean Slate Inventory

Date: 2026-05-05

## Remaining Top-Level Surface

| Path | Type | File Count | Size |
|---|---:|---:|---:|
| .github | dir | 11 | 43 KB |
| .gitignore | file | 1 | 1 KB |
| docs | dir | 6 | 36 KB |
| embeddings | dir | 1 | 0 KB |
| LICENSE.txt | file | 1 | 36 KB |
| models | dir | 18 | 9.0 GB |
| package.json | file | 1 | 1 KB |
| pixel_backend | dir | 6 | 23 KB |
| pyproject.toml | file | 1 | 4 KB |
| README.md | file | 1 | 4 KB |
| requirements.txt | file | 1 | 1 KB |

## Keep List (Clean Baseline)

- .github/ (repo instructions and skills)
- .gitignore
- docs/pixel-studio/ (reset plan, API contract, inventory)
- pixel_backend/ (new backend package)
- requirements.txt
- README.md
- models/ (checkpoint and model storage)
- embeddings/ (optional model artifacts)
- package.json (temporary dev command surface)
- pyproject.toml (python project metadata)
- LICENSE.txt

## Notes

- This is now backend-first with no bundled WebUI frontend.
- Backend starts from `py -3 -m pixel_backend`.
- Backend endpoints are defined in docs/pixel-studio/MVP_PRODUCT_AND_API.md.
- Job execution is still a stub and must be wired to real model inference next.
