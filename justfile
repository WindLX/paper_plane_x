set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
    @just --list

backend *args:
    @just -f paper_plane_x_backend/justfile {{args}}

frontend *args:
    @just -f paper_plane_x_frontend/justfile {{args}}

cli *args:
    @just -f paper_plane_x_cli/justfile {{args}}

zotero *args:
    @just -f paper_plane_x_zotero/justfile {{args}}

radar *args:
    @just -f paper_plane_x_radar/justfile {{args}}

setup:
    just backend setup
    just frontend setup
    just cli setup
    just zotero setup
    just radar setup

test:
    just backend test
    just frontend test
    just cli test
    just zotero test
    just radar test

lint:
    just backend lint
    just frontend lint
    just cli lint
    just zotero lint
    just radar lint

format:
    just backend format
    just frontend format
    just cli format
    just zotero format
    just radar format

build:
    just backend build
    just frontend build
    just cli build
    just zotero build
    just radar build

pre-commit:
    just backend pre-commit
    just frontend pre-commit
    just cli pre-commit
    just zotero pre-commit
    just radar pre-commit

dev:
    just backend dev

dev-frontend:
    just frontend dev

build-console:
    just frontend build-console

version *args:
    python scripts/sync_version.py {{args}}
