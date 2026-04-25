# Paper Plane X Conventions

## Versioning

- The repo-root `VERSION` file is the single source of truth.
- Backend and frontend consumers should read from it directly or be synced from it.
- Use `scripts/sync_version.py` when you want to update dependent metadata files.

## Backend Config Profiles

- Backend config selection uses `PPX_CONFIG_FILE`.
- Supported committed profiles:
  - `paper_plane_x_backend/config/default.toml`
  - `paper_plane_x_backend/config/dev.toml`
  - `paper_plane_x_backend/config/test.toml`
- Safe local customization belongs in:
  - `paper_plane_x_backend/.env`
  - `paper_plane_x_backend/config/*.local.toml`

## Frontend Config

- Frontend runtime config goes through Vite env variables.
- Public API base URL is `VITE_API_BASE_URL`.
- Safe local customization belongs in:
  - `paper_plane_x_frontend/.env`
  - `paper_plane_x_frontend/.env.development`

## Documentation

- Repo-level overview lives in `README.md`.
- Backend operational entry docs live in `paper_plane_x_backend/README.md`.
- Backend detail docs live under `paper_plane_x_backend/docs/`.
- When routes, commands, config contracts, or deployment steps change, update docs in the same change.
