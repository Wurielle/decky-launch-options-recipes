export interface LaunchOption {
    id?: string;
    group?: string;
    name?: string;
    on?: string;
    off?: string;
    enableGlobally?: boolean;
    valueId?: string;
    valueName?: string;
    fallbackValue?: boolean;
}

export interface Recipe {
    name: string;
    launchOptions: LaunchOption[];
}
