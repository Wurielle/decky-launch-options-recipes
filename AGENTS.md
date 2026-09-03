# Repository Guidelines

## Project Structure & Module Organization

This repository packages launch option recipes for the Decky Launch Options plugin. Recipe sources live in `recipes/<name>.ts` or `recipes/<name>/index.ts`; each source exports one `Recipe` object and `recipes/types.ts` defines the shared shape. Use the directory form when a recipe has supporting files. `recipes.json` is generated from those sources and should not be hand-edited except to inspect output. The Decky frontend is in `src/`, backend helper code is in `backend/`, static assets are in `assets/`, default data is in `defaults/`, and recipe build tooling is in `scripts/`.

## Build, Test, and Development Commands

- `pnpm install`: install JavaScript dependencies using the pinned package manager.
- `pnpm recipes:build`: compile recipe TypeScript and regenerate `recipes.json`.
- `pnpm recipes:check`: regenerate recipes and fail if `recipes.json` differs from the committed file.
- `pnpm build`: build the Decky plugin frontend with Rollup.
- `pnpm watch`: run Rollup in watch mode.
- `just setup`: run repository setup helpers from `.vscode/`.
- `just build`, `just deploy`, `just builddeploy`: build and optionally deploy to a configured Steam Deck.

`pnpm test` is currently a placeholder and exits with an error.

## Coding Style & Naming Conventions

Use TypeScript ESM style and match nearby files. Recipe files and directories use hyphen-case names, for example `lossless-scaling.ts` or `reframework/index.ts`. Import the shared type from `./types.js` in top-level files or `../types.js` in directory indexes. Prefer 4-space indentation in recipe objects, trailing commas, and explicit `satisfies Recipe`.

Launch option IDs should be stable and hyphen-case. A regular option usually uses the feature name only, such as `mangohud`. Dropdown values should include the tool, modified option/config, and value, for example `mangohud-config-preset-1` or `mangohud-fps-limit-60`.

## Testing Guidelines

For recipe changes, run `pnpm recipes:check` before submitting. For frontend or plugin changes, run `pnpm build`. If `recipes.json` changes after a recipe edit, include the generated file in the same change.

## Commit & Pull Request Guidelines

Recent history uses short conventional-style commits such as `feat: add mangohud fps limit`, `fix: add missing MangoHud in name`, and `chore: rebuild recipes.json`. Keep commits scoped and descriptive. Pull requests should explain the recipe or plugin behavior changed, list validation commands run, and include screenshots only for UI-facing changes.

## Security & Configuration Tips

Do not commit Steam Deck credentials or local overrides. Deployment commands read values such as `DECK_IP`, `DECK_USER`, and `DECK_PASS` from `.env.local`; keep that file private.
