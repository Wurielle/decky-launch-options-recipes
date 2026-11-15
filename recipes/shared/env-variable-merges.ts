import type { EnvVariableMerge } from './types.js'

// Merge rules belong to the variable, so every recipe uses the same identity.
export const wineDllOverridesMerge = {
    id: 'winedlloverrides',
    name: 'WINEDLLOVERRIDES',
    delimiter: ';',
} satisfies EnvVariableMerge
