import gplay from "google-play-scraper";
import { Config } from "./Config.js";

export interface TermEntry {
    term: string; // texto original (aparado), usado na busca
    group: string; // condição de origem; as sugestões herdam o grupo do termo pai
    depth: number; // 0 = semente
    parent: string | null; // chave normalizada do pai; null nas sementes
}

export interface SnowballOptions {
    maxRetries?: number; // tentativas por termo antes de desistir dele
    retryBackoffMs?: number; // espera base entre tentativas (dobra a cada nova tentativa)
    maxConsecutiveFailures?: number; // aborta se tantos termos seguidos falharem (possível bloqueio)
    onLevelComplete?: (depth: number, results: ReadonlyMap<string, TermEntry>) => void | Promise<void>;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// Classe que, dada uma lista de termos, usa a funcionalidade de sugestões do Google Play
// Store para obter o autocomplete de termos parecidos.
// Criando um snowballing de termos de acordo com os termos populares da loja.
export default class SuggestionSnowball {
    private readonly seeds: Map<string, Set<string>>;
    private readonly maxRetries: number;
    private readonly retryBackoffMs: number;
    private readonly maxConsecutiveFailures: number;
    private readonly onLevelComplete?: SnowballOptions["onLevelComplete"];
    private consecutiveFailures = 0;

    public constructor(seeds: Map<string, Set<string>>, options: SnowballOptions = {}) {
        this.seeds = seeds;
        this.maxRetries = options.maxRetries ?? 3;
        this.retryBackoffMs = options.retryBackoffMs ?? 30_000;
        this.maxConsecutiveFailures = options.maxConsecutiveFailures ?? 5;
        this.onLevelComplete = options.onLevelComplete;
    }

    // Executa o snowballing de sugestões
    public async snowball(maxDepth: number = 2): Promise<Map<string, TermEntry>> {
        const results = new Map<string, TermEntry>();
        if (!Number.isInteger(maxDepth) || maxDepth < 0) return results;

        // A fronteira guarda chaves normalizadas; o texto de busca está em results.get(chave).term
        let frontier: string[] = [];

        // Primeiro populamos com as sementes. Um termo que aparece em dois grupos fica com o primeiro.
        for (const [group, terms] of this.seeds) {
            for (const raw of terms) {
                const term = raw.trim();
                const key = this.normalize(term);
                if (!key || results.has(key)) continue;
                results.set(key, { term, group, depth: 0, parent: null });
                frontier.push(key);
            }
        }
        await this.onLevelComplete?.(0, results);

        for (let depth = 1; depth <= maxDepth && frontier.length > 0; depth++) {
            const nextFrontier: string[] = [];

            for (const parentKey of frontier) {
                const parent = results.get(parentKey)!;
                const suggestions = await this.fetchSuggestions(parent.term);

                for (const suggestion of suggestions) {
                    const term = suggestion.trim();
                    const key = this.normalize(term);
                    if (!key || results.has(key)) continue;
                    // a sugestão herda o grupo do pai e aponta para a chave do pai
                    results.set(key, { term, group: parent.group, depth, parent: parentKey });
                    nextFrontier.push(key);
                }
            }
            frontier = nextFrontier;
            await this.onLevelComplete?.(depth, results);
        }

        return results;
    }

    // Busca as sugestões de um termo
    private async fetchSuggestions(term: string): Promise<string[]> {
        for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
            try {
                const suggestions = await gplay.suggest({
                    term,
                    country: Config.COUNTRY,
                    lang: Config.LANGUAGE,
                    throttle: Config.THROTTLE,
                });
                this.consecutiveFailures = 0;
                await Config.pause();
                return suggestions;
            } catch (error: unknown) {
                if (this.isMalformedSuggestionsResponse(error)) {
                // resposta sem sugestões em formato esperado: não adianta tentar de novo
                console.warn(`Sugestões indisponíveis para '${term}': resposta inválida do Google Play.`);
                this.consecutiveFailures = 0;
                await Config.pause();
                return [];
            }
                console.warn(`Falha em '${term}' (tentativa ${attempt}/${this.maxRetries}):`, error);
                if (attempt < this.maxRetries) await sleep(this.retryBackoffMs * 2 ** (attempt - 1));
            }
        }

        this.consecutiveFailures += 1;
        console.error(`Desistindo de '${term}' depois de ${this.maxRetries} tentativas.`);
        if (this.consecutiveFailures >= this.maxConsecutiveFailures) {
            throw new Error(
                `${this.consecutiveFailures} termos seguidos falharam: possível bloqueio. Interrompendo a coleta.`,
            );
        }
        return [];
    }

    private isMalformedSuggestionsResponse(error: unknown): boolean {
        return (
        error instanceof TypeError &&
        error.message.includes("Cannot read properties of null (reading 'map')")
        );
    }

    // Chave de deduplicação: sem acentos, minúsculas, espaços colapsados
    private normalize(term: string): string {
        return term
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .toLowerCase()
        .replace(/\s+/g, " ")
        .trim();
    }
}