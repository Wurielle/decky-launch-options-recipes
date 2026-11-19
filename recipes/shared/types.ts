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

export interface EnvironmentVariableMerge {
    id?: string;
    name: string;
    delimiter: string;
}

export interface Recipe {
    id: string;
    name: string;
    launchOptions: LaunchOption[];
    environmentVariableMerges?: EnvironmentVariableMerge[];
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
