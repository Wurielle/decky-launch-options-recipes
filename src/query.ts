import {QueryClient, useQuery} from '@tanstack/react-query'

import type {Recipe} from '../recipes/types'

export const queryClient = new QueryClient()

export const useGetRecipesQuery = (url: string) => {
    return useQuery<Recipe[]>({
        queryKey: ['recipes', url],
        queryFn: async () => {
            try {
                const response = await fetch(url);
                const data = await response.json();
                if (Array.isArray(data)) return data
            } catch (e) {
                const message = e instanceof Error ? e.message : ''
                console.error('Error fetching recipes', message)
            }
            return [];
        },
    });
}
