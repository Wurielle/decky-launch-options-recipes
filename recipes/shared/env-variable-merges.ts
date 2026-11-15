import type { EnvironmentVariableMerge } from './types.js'

// Merge rules belong to the variable, so every recipe uses the same identity.
export const wineDllOverridesMerge = {
    id: 'winedlloverrides',
    name: 'WINEDLLOVERRIDES',
    delimiter: ';',
} satisfies EnvironmentVariableMerge
