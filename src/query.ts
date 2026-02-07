import {QueryClient, useQuery} from '@tanstack/react-query'

export const queryClient = new QueryClient()

export const useGetRecipesQuery = (url: string) => {
    return useQuery({
        queryKey: ['recipes', url],
        queryFn: async () => {
            try {
                const response = await fetch(url);
                const data = await response.json();
                if (Array.isArray(data)) return data
            } catch (e) {
                console.error('Error fetching recipes', e.message || '')
            }
            return [];
        },
    });
}