import type {Store} from './recipes/shared/types.js';

const store = {
    name: 'Decky Launch Options Recipes',
    description: 'A collection of launch option recipes for Decky Launch Options.',
    type: 'github',
    github: {
        repository: '{{env:RECIPE_REPOSITORY_OWNER}}/{{env:RECIPE_REPOSITORY_NAME}}',
        branch: '{{env:RECIPE_BRANCH}}',
    },
} satisfies Store;

export default store;
