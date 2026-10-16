import gplay from "google-play-scraper";
import { COUNTRY, LANGUAGE, SUGGESTION_MAX_DEPTH } from "./config.js";
import { pause } from "./rate-limit.js";

export interface SuggestionSnowballOptions {
  country?: string;
  lang?: string;
  maxDepth?: number;
}

export class SuggestionSnowball {
  private readonly seeds: string[];
  private readonly country: string;
  private readonly lang: string;
  private readonly maxDepth: number;

  constructor(
    seeds: readonly string[],
    {
      country = COUNTRY,
      lang = LANGUAGE,
      maxDepth = SUGGESTION_MAX_DEPTH,
    }: SuggestionSnowballOptions = {},
  ) {
    if (!Number.isInteger(maxDepth) || maxDepth < 0) {
      throw new RangeError("maxDepth deve ser um número inteiro maior ou igual a zero");
    }

    this.seeds = seeds.map((seed) => seed.trim()).filter(Boolean);
    this.country = country;
    this.lang = lang;
    this.maxDepth = maxDepth;
  }

  async run(): Promise<string[]> {
    const terms = new Map<string, string>();
    let frontier: string[] = [];

    for (const seed of this.seeds) {
      const key = this.normalize(seed);
      if (!terms.has(key)) {
        terms.set(key, seed);
        frontier.push(seed);
      }
    }

    for (let depth = 0; depth < this.maxDepth && frontier.length > 0; depth += 1) {
      const nextFrontier: string[] = [];

      for (const term of frontier) {
        const suggestions = await gplay.suggest({
          term,
          country: this.country,
          lang: this.lang,
        });
        await pause();

        for (const suggestion of suggestions) {
          const normalizedSuggestion = suggestion.trim();
          if (!normalizedSuggestion) {
            continue;
          }

          const key = this.normalize(normalizedSuggestion);
          if (!terms.has(key)) {
            terms.set(key, normalizedSuggestion);
            nextFrontier.push(normalizedSuggestion);
          }
        }
      }

      frontier = nextFrontier;
    }

    return [...terms.values()];
  }

  private normalize(term: string): string {
    return term.toLocaleLowerCase();
  }
}
