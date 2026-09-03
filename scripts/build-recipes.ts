import {promises as fs} from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

import type {Recipe} from '../recipes/types.js';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, '..', '..', '..');
const compiledRecipesDir = path.join(repoRoot, '.generated', 'recipes-build', 'recipes');
const outputPath = path.join(repoRoot, 'recipes.json');
const environmentPlaceholderPattern = /\{\{env:([A-Z_][A-Z0-9_]*)\}\}/g;

function resolveEnvironmentPlaceholders(value: unknown, fileName: string): unknown {
  if (typeof value === 'string') {
    return value.replace(
      environmentPlaceholderPattern,
      (_placeholder: string, variableName: string) => {
        const environmentValue = process.env[variableName];

        if (environmentValue === undefined) {
          throw new Error(
            `Recipe "${fileName}" requires the environment variable "${variableName}".`,
          );
        }

        return environmentValue;
      },
    );
  }

  if (Array.isArray(value)) {
    return value.map((item) => resolveEnvironmentPlaceholders(item, fileName));
  }

  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [
        key,
        resolveEnvironmentPlaceholders(nestedValue, fileName),
      ]),
    );
  }

  return value;
}

async function getExistingRecipeOrder(): Promise<Map<string, number>> {
  try {
    const json = execFileSync('git', ['show', 'HEAD:recipes.json'], {
      cwd: repoRoot,
      encoding: 'utf8',
    });
    const recipes = JSON.parse(json) as Recipe[];

    return new Map(recipes.map((recipe, index) => [recipe.name, index]));
  } catch {
    return new Map();
  }
}

async function loadRecipes(): Promise<Recipe[]> {
  const fileNames = (await fs.readdir(compiledRecipesDir))
    .filter((fileName) => fileName.endsWith('.js'))
    .filter((fileName) => fileName !== 'index.js' && fileName !== 'types.js')
    .sort();

  return Promise.all(
    fileNames.map(async (fileName) => {
      const moduleUrl = pathToFileURL(path.join(compiledRecipesDir, fileName)).href;
      const module = await import(moduleUrl);

      return resolveEnvironmentPlaceholders(module.default, fileName) as Recipe;
    }),
  );
}

async function main() {
  const recipes = await loadRecipes();
  const existingOrder = await getExistingRecipeOrder();
  recipes.sort((a, b) => {
    const aIndex = existingOrder.get(a.name) ?? Number.MAX_SAFE_INTEGER;
    const bIndex = existingOrder.get(b.name) ?? Number.MAX_SAFE_INTEGER;

    if (aIndex !== bIndex) {
      return aIndex - bIndex;
    }

    return a.name.localeCompare(b.name);
  });
  const json = `${JSON.stringify(recipes, null, 2)}\n`;

  await fs.writeFile(outputPath, json, 'utf8');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
