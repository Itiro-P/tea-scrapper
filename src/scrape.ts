import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import gplay from "google-play-scraper";
import {
  COUNTRY,
  LANGUAGE,
  OMIT_KEYS,
  SEARCH_RESULTS_PER_TERM,
  SEARCH_TERMS,
  SUGGESTION_MAX_DEPTH,
  slugify,
} from "./config.js";
import { pause } from "./rate-limit.js";
import { SuggestionSnowball } from "./suggestion-snowball.js";

function localDate(): string {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function main(): Promise<void> {
  const outputDir = join("output", `results_${localDate()}`);
  await mkdir(outputDir, { recursive: true });

  for (const [group, seeds] of Object.entries(SEARCH_TERMS)) {
    let terms = seeds;
    try {
      terms = await new SuggestionSnowball(seeds, {
        maxDepth: SUGGESTION_MAX_DEPTH,
      }).run();
      console.log(
        `\n== [${group}] Snowball: ${seeds.length} sementes -> ${terms.length} termos`,
      );
    } catch (error: unknown) {
      console.error(
        `\n== [${group}] ERRO ao expandir sugestões; usando sementes originais: ${errorMessage(error)}`,
      );
    }

    for (const term of terms) {
      const collectTime = new Date().toISOString();
      let apps: Record<string, unknown>[];
      let appSummaries: Array<{
        appId: string;
        title: string;
        genre: string;
        installs: string;
      }>;

      try {
        const results = await gplay.search({
          term,
          lang: LANGUAGE,
          country: COUNTRY,
          num: SEARCH_RESULTS_PER_TERM,
        });
        await pause();

        const appIds = [...new Set(results.map((result) => result.appId))];
        apps = [];
        appSummaries = [];
        for (const appId of appIds) {
          const details = await gplay.app({
            appId,
            lang: LANGUAGE,
            country: COUNTRY,
          });
          appSummaries.push({
            appId: details.appId,
            title: details.title,
            genre: details.genre,
            installs: details.installs,
          });
          const app = Object.fromEntries(
            Object.entries(details).filter(([key]) => !OMIT_KEYS.has(key)),
          );
          app.term = term;
          apps.push(app);
          await pause();
        }
      } catch (error: unknown) {
        console.error(`\n== [${group}] '${term}': ERRO -> ${errorMessage(error)}`);
        continue;
      }

      console.log(`\n== [${group}] ${term} (${apps.length} apps)`);
      for (const app of appSummaries) {
        console.log(
          app.appId,
          "|",
          app.title,
          "|",
          app.genre,
          "|",
          app.installs,
        );
      }

      const payload = {
        meta: {
          collect_time: collectTime,
          lang: LANGUAGE,
          country: COUNTRY,
          group,
          term,
          result_count: apps.length,
        },
        apps,
      };
      const fileName = `${slugify(group)}__${slugify(term)}.json`;
      await writeFile(
        join(outputDir, fileName),
        `${JSON.stringify(payload, null, 2)}\n`,
        "utf8",
      );
    }
  }
}

void main().catch((error: unknown) => {
  console.error(`Falha na coleta: ${errorMessage(error)}`);
  process.exitCode = 1;
});
