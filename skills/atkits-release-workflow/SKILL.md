---
name: atkits-release-workflow
description: "Release versioned skills or plugins in the agent-tool-kits repository: bump metadata versions, validate changes, build packages, tag releases, push tags, and verify catalog/CI. Use when the user asks to publish, upgrade, release, or version-bump an asset in this repository; not for general Git or package management."
metadata:
  version: 0.1.0
---

# atkits Release Workflow

Use this skill when the user asks to release, publish, upgrade, or version-bump a skill or plugin in this repository.

## Objective

Produce a verified, tagged release for exactly one asset without touching unrelated files.

## Preflight

1. Confirm the repository is clean or that only the intended asset is modified.
2. Identify the asset:
   - Skill: `skills/<name>/SKILL.md`
   - Plugin: `plugins/<name>/plugin.yaml`
3. Read the current version.
4. Confirm the target version with the user if the bump level is unclear.
5. Never release a CLI wheel with this skill unless the user explicitly asks for `cli-v<version>`.

## Version policy

Use SemVer 2.0.0.

- Fix typo, docs, or small bug → patch
- Add capability without breaking usage → minor
- Breaking change or major behavior shift → major
- Experimental release → prerelease

Do not reuse an existing version.

## Release steps

1. Update only the version field:
   - Skill: `metadata.version` in `SKILL.md`
   - Plugin: `version` in `plugin.yaml`
2. Run:
   ```bash
   uv run pytest
   uvx ruff format src tests scripts
   uvx ruff check src tests scripts
   uv build --quiet
   ```
3. Build the single asset locally:
   ```bash
   uv run python scripts/package_asset.py skill <name> <version> . dist
   ```
   or:
   ```bash
   uv run python scripts/package_asset.py plugin <name> <version> . dist
   ```
4. Confirm the archive name and SHA-256 file exist.
5. Create the tag:
   ```text
   skill-<name>-v<version>
   plugin-<name>-v<version>
   ```
6. Push the tag only after the user confirms.
7. Verify GitHub Actions and the resulting Release.
8. Confirm `catalog.json` was updated by CI.

## Hard rules

- Never skip tests or lint.
- Never publish a changed asset without bumping the version.
- Never reuse the same version for different content.
- Never push a tag without explicit user approval.
- Never modify unrelated files.
- Never treat external skills as versioned assets in this repository.
- If any check fails, stop and report the failure; do not continue to tagging.
