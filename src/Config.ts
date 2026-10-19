import { randomInt } from "crypto";

export namespace Config {
    // Quantidade de requisições por segundo para evitar rate-limit do Google.
    export const THROTTLE = 10;

    export const SEARCH_RESULTS_PER_TERM = 250;

    export const DEPTH = 5;

    export const COUNTRY = "br";
    export const LANGUAGE = "pt";

    const MIN_PAUSE_MS = 5_000;
    const MAX_PAUSE_MS = 10_000;
    // Pausa aleatória para evitar rate-limit.
    export function pause(): Promise<void> {
        const pause_time = randomInt(MIN_PAUSE_MS, MAX_PAUSE_MS + 1);
        return new Promise((resolvePause) => setTimeout(resolvePause, pause_time));
    }

    export function errorMessage(error: unknown): string {
        return error instanceof Error ? error.message : String(error);
    }

    export function slugify(text: string): string {
        return text
            .normalize("NFKD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_+|_+$/g, "");
    }

    // Termos iniciais de pesquisa (sementes). O SuggestionSnowball expande a partir deles,
    // então a lista pode ser enxuta, mais
    // variantes muito comuns. Termos neutros, sem palavras como "jogos" ou "aprender",
    // para não enviesar a amostra para apps de aprendizagem.
    export const INITIAL_SEARCH_TERMS = new Map<string, Set<string>>([
        [
            "TEA",
            new Set([
            "autismo",
            "autism",
            "transtorno do espectro autista",
            "espectro autista",
            // "tea", // em inglês é "chá": traz apps de chá
            ]),
        ],
        [
            "TDAH",
            new Set([
            "tdah",
            "déficit de atenção",
            "transtorno do déficit de atenção com hiperatividade",
            "adhd",
            ]),
        ],
        [
            "TDL",
            new Set([
            "transtorno do desenvolvimento da linguagem",
            "atraso de linguagem",
            "atraso na fala",
            "developmental language disorder",
            // "tdl", // sigla curta e ambígua
            ]),
        ],
        [
            "DISLEXIA",
            new Set([
            "dislexia",
            "dyslexia",
            "transtorno de leitura",
            ]),
        ],
        [
            "TDC",
            new Set([
            "dispraxia",
            "dyspraxia",
            "transtorno do desenvolvimento da coordenação",
            // "tdc", // sigla ambígua
            ]),
        ],
        [
            "DISCALCULIA",
            new Set([
            "discalculia",
            "dyscalculia",
            ]),
        ],
        [
            "AHSD",
            new Set([
            "altas habilidades",
            "superdotação",
            // "gifted" foi removido: a expansão gera sugestões sobre presentes e assuntos alheios a AHSD.
            // "ah/sd", // sigla ambígua
            ]),
        ],
        [
            "DISGRAFIA",
            new Set([
            "disgrafia",
            "dysgraphia",
            "dificuldade de escrita",
            ]),
        ],
        [
            "DI",
            new Set([
            "deficiência intelectual",
            "intellectual disability",
            // "di", // sigla ambígua
            ]),
        ],
        [
            "TOURETTE",
            new Set([
            "síndrome de tourette",
            "tourette",
            ]),
        ],
    ]);

    // Sugestões observadas que desviam para serviços locais, sons ou jogos sem relação com o tema.
    export const OMITTED_SUGGESTIONS = new Map<string, Set<string>>([
        ["TEA", new Set(["autismo perto"])],
        [
            "TOURETTE",
            new Set([
                "signalement tiques",
                "tiques para celular",
                "tourette defense",
                "tourettes guy soundboard",
            ]),
        ],
    ]);

    // Categorias de aplicativos irrelevantes para a pesquisa
    export const OMITTED_CATEGORIES = new Set([
        "ART_AND_DESIGN",
        "AUTO_AND_VEHICLES",
        "BUSINESS",
        "DATING",
        "ENTERTAINMENT",
        "EVENTS",
        "FINANCE",
        "FOOD_AND_DRINK",
        "GAME_ACTION",
        "GAME_ARCADE",
        "GAME_BOARD",
        "GAME_CARD",
        "GAME_CASUAL",
        "GAME_MUSIC",
        "GAME_PUZZLE",
        "GAME_ROLE_PLAYING",
        "GAME_SIMULATION",
        "GAME_STRATEGY",
        "GAME_WORD",
        "GAME_TRIVIA",
        // "HEALTH_AND_FITNESS",
        "HOUSE_AND_HOME",
        "MAPS_AND_NAVIGATION",
        "MUSIC_AND_AUDIO",
        "PARENTING",
        "PERSONALIZATION",
        "PHOTOGRAPHY",
        // "PRODUCTIVITY",
        "SHOPPING",
        "SOCIAL",
        "SPORTS",
        "TOOLS",
        "TRAVEL_AND_LOCAL",
        "VIDEO_PLAYERS",
        "BOOKS_AND_REFERENCE"
    ]);

    // Chaves do JSON de aplicativo que são inúteis para a pesquisa
    export const OMITTED_KEYS = new Set([
        "histogram",
        "offersIAP",
        "IAPRange",
        "androidVersion",
        "androidVersionText",
        "androidMaxVersion",
        "developer",
        "developerId",
        "developerEmail",
        "developerWebsite",
        "developerAddress",
        "developerLegalName",
        "developerLegalEmail",
        "developerLegalAddress",
        "developerLegalPhoneNumber",
        "privacyPolicy",
        "developerInternalID",
        "icon",
        "headerImage",
        "screenshots",
        "video",
        "videoImage",
        "previewVideo",
        "contentRating",
        "contentRatingDescription",
        "released",
        "updated",
        "version",
        "recentChanges",
        "comments",
        "preregister",
        "earlyAccessEnabled",
        "isAvailableInPlayPass"
    ]);
}