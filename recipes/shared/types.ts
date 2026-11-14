export interface LaunchOption {
    id?: string;
    group?: string;
    name?: string;
    on?: string;
    off?: string;
    enableGlobally?: boolean;
    priority?: number;
    valueId?: string;
    valueName?: string;
    fallbackValue?: boolean;
}

export interface Recipe {
    name: string;
    launchOptions: LaunchOption[];
}

export interface Store {
    name: string;
    description: string;
    type: 'github';
    github: {
        repository: string;
        branch: string;
    };
}
