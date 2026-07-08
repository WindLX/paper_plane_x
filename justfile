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

setup:
    just backend setup
    just frontend setup
    just cli setup
    just zotero setup

test:
    just backend test
    just frontend test
    just cli test
    just zotero test

lint:
    just backend lint
    just frontend lint
    just cli lint
    just zotero lint

format:
    just backend format
    just frontend format
    just cli format
    just zotero format

build:
    just backend build
    just frontend build
    just cli build
    just zotero build

pre-commit:
    just backend pre-commit
    just frontend pre-commit
    just cli pre-commit
    just zotero pre-commit

dev:
    just backend dev

dev-frontend:
    just frontend dev

build-console:
    just frontend build-console
