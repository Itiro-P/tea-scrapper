export const LANGUAGE = "pt";
export const COUNTRY = "br";
export const SEARCH_RESULTS_PER_TERM = 100;
export const SUGGESTION_MAX_DEPTH = 10;

export const SEARCH_TERMS: Record<string, string[]> = {
  TDAH: [
    "tdah",
    "déficit de atenção",
    "transtorno do déficit de atenção com hiperatividade",
    "adhd",
    "attention deficit",
  ],
  TDL: [
    "transtorno do desenvolvimento da linguagem",
    "atraso de linguagem",
    "atraso na fala",
    "developmental language disorder",
  ],
  DISLEXIA: ["dislexia", "transtorno de leitura", "dyslexia"],
  TDC: [
    "dispraxia",
    "transtorno do desenvolvimento da coordenação",
    "dyspraxia",
    "developmental coordination disorder",
  ],
  DISCALCULIA: [
    "discalculia",
    "dificuldade em matemática",
    "dyscalculia",
  ],
  AHSD: [
    "altas habilidades",
    "superdotação",
    "altas habilidades superdotação",
    "gifted",
  ],
  DISGRAFIA: ["disgrafia", "dificuldade de escrita", "dysgraphia"],
  TEA: [
    "autismo",
    "transtorno do espectro autista",
    "autism",
    "espectro autista",
  ],
  DI: ["deficiência intelectual", "intellectual disability"],
  TOURETTE: ["síndrome de tourette", "tourette", "tourette syndrome"],
  GERAL: [
    "neurodivergente",
    "neurodiversidade",
    "necessidades especiais",
    "educação especial",
  ],
};

export const BLOCKLISTED_GENRES = new Set([
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
  "HEALTH_AND_FITNESS",
  "HOUSE_AND_HOME",
  "MAPS_AND_NAVIGATION",
  "MUSIC_AND_AUDIO",
  "PARENTING",
  "PERSONALIZATION",
  "PHOTOGRAPHY",
  "PRODUCTIVITY",
  "SHOPPING",
  "SOCIAL",
  "SPORTS",
  "TOOLS",
  "TRAVEL_AND_LOCAL",
  "VIDEO_PLAYERS",
  "BOOKS_AND_REFERENCE",
]);

export const OMIT_KEYS = new Set([
  "developer",
  "developerId",
  "developerEmail",
  "developerWebsite",
  "developerAddress",
  "privacyPolicy",
  "histogram",
  "installs",
  "minInstalls",
  "icon",
  "headerImage",
  "screenshots",
  "video",
  "videoImage",
  "comments",
  "developerLegalName",
  "developerLegalEmail",
  "developerLegalAddress",
  "developerLegalPhoneNumber",
  "developerInternalID",
  "androidVersion",
  "androidVersionText",
  "androidMaxVersion",
  "previewVideo"
]);

export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}
