import { access, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { Config } from "./Config.js";
import gplay from "./PlayStore.js";
import type { TermEntry } from "./SuggestionSnowball.js";

export interface AppSearchOptions {
    outputDir?: string;
    maxRetries?: number; // tentativas por requisição
    retryBackoffMs?: number; // espera base entre tentativas (dobra a cada nova tentativa)
    maxConsecutiveFailures?: number; // aborta se tantas requisições seguidas falharem (possível bloqueio)
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const errorMessage = (error: unknown): string => (error instanceof Error ? error.message : String(error));
const exists = (path: string) => access(path).then(() => true, () => false);

// 'Déficit de Atenção' -> 'deficit_de_atencao' (seguro para nome de arquivo)
function slugify(text: string): string {
    return text
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
}

export default class AppSearch {
    private readonly outputDir: string;
    private readonly maxRetries: number;
    private readonly retryBackoffMs: number;
    private readonly maxConsecutiveFailures: number;
    private readonly appCache = new Map<string, Record<string, unknown>>(); // appId -> detalhes (cada app é baixado uma vez)
    private consecutiveFailures = 0;

    public constructor(options: AppSearchOptions = {}) {
        this.outputDir = options.outputDir ?? "results";
        this.maxRetries = options.maxRetries ?? 3;
        this.retryBackoffMs = options.retryBackoffMs ?? 30_000;
        this.maxConsecutiveFailures = options.maxConsecutiveFailures ?? 5;
    }

    public async search(terms: ReadonlyMap<string, TermEntry>): Promise<void> {
        await mkdir(this.outputDir, { recursive: true });

        for (const [key, entry] of terms) {
        const path = join(this.outputDir, `${slugify(entry.group)}__${slugify(key)}.json`);
        if (await exists(path)) continue; // coleta retomável: pula termos já salvos

        const collectTime = new Date().toISOString();
        const results = await this.attempt(`busca '${entry.term}'`, async () => {
            const found = await gplay.search({
                term: entry.term,
                lang: Config.LANGUAGE,
                country: Config.COUNTRY,
                throttle: Config.THROTTLE,
                num: Config.SEARCH_RESULTS_PER_TERM,
            });
            await Config.pause();
            return found;
        });
        if (results === null) continue; // sem arquivo: o termo será tentado de novo na próxima execução

        const appIds = [...new Set(results.map((result) => result.appId))];
        const apps: Record<string, unknown>[] = [];
        const failedAppIds: string[] = [];
        const omittedAppIds: string[] = [];

        console.log(`\n== [${entry.group}] ${entry.term} (${appIds.length} apps)`);
        for (const [index, appId] of appIds.entries()) {
            const details = await this.getApp(appId);
            if (details === null) {
            failedAppIds.push(appId);
            continue;
            }
            const genreId = details.genreId;
            if (typeof genreId === "string" && Config.OMITTED_CATEGORIES.has(genreId)) {
            omittedAppIds.push(appId);
            continue;
            }
            // cópia, porque o objeto do cache é compartilhado entre termos; rank = posição na busca
            apps.push({ ...details, rank: index + 1 });
            console.log(details.appId, "|", details.title, "|", details.genre, "|", details.installs);
        }

        const payload = {
            meta: {
            collect_time: collectTime,
            lang: Config.LANGUAGE,
            country: Config.COUNTRY,
            group: entry.group,
            term: entry.term,
            key,
            depth: entry.depth,
            parent: entry.parent,
            result_count: appIds.length,
            failed_app_ids: failedAppIds,
            omitted_app_ids: omittedAppIds,
            },
            apps,
        };
        
        await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
        }
    }

    // Detalhes de um app, com cache e sem as chaves omitidas
    private async getApp(appId: string): Promise<Record<string, unknown> | null> {
        const cached = this.appCache.get(appId);
        if (cached) return cached;

        const details = await this.attempt(`app '${appId}'`, async () => {
            const found = await gplay.app({
                appId,
                lang: Config.LANGUAGE,
                country: Config.COUNTRY,
                throttle: Config.THROTTLE,
            });
            await Config.pause();
            return found;
        });
        if (details === null) return null;

        const filtered = Object.fromEntries(
        Object.entries(details).filter(([field]) => !Config.OMITTED_KEYS.has(field)));
        this.appCache.set(appId, filtered);
        return filtered;
    }

    // Executa uma requisição com novas tentativas. Devolve null se desistir.
    private async attempt<T>(label: string, run: () => Promise<T>): Promise<T | null> {
        for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
            try {
                const value = await run();
                this.consecutiveFailures = 0;
                return value;
            } catch (error: unknown) {
                const message = errorMessage(error);
                if (message.includes("404")) {
                // app indisponível nesta loja: não adianta tentar de novo nem conta como falha de rede
                console.warn(`${label}: não encontrado (404).`);
                return null;
                }
                console.warn(`Falha em ${label} (tentativa ${attempt}/${this.maxRetries}): ${message}`);
                if (attempt < this.maxRetries) await sleep(this.retryBackoffMs * 2 ** (attempt - 1));
            }
        }

        this.consecutiveFailures += 1;
        console.error(`Desistindo de ${label}.`);
        if (this.consecutiveFailures >= this.maxConsecutiveFailures) {
            throw new Error(
                `${this.consecutiveFailures} requisições seguidas falharam: possível bloqueio. Interrompendo a coleta.`,
            );
        }
        return null;
    }
}