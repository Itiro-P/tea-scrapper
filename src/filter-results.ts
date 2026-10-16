import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { BLOCKLISTED_GENRES, OMIT_KEYS } from "./config.js";

type JsonObject = Record<string, unknown>;

interface GroupAggregate {
  meta: {
    group: string;
    term: string;
    sources: string[];
    count?: number;
  };
  apps: Map<string, JsonObject>;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function readResult(filePath: string): Promise<JsonObject | undefined> {
  const contents = await readFile(filePath, "utf8");
  try {
    const result: unknown = JSON.parse(contents);
    return isObject(result) ? result : undefined;
  } catch (error: unknown) {
    if (error instanceof SyntaxError) {
      console.error(`Erro ao decodificar o JSON do arquivo: ${filePath}`);
      return undefined;
    }
    throw error;
  }
}

async function main(): Promise<void> {
  const inputArgument = process.argv[2];
  if (!inputArgument) {
    console.error("Uso: npm run filter -- <diretorio_dos_jsons>");
    process.exitCode = 1;
    return;
  }

  const resultDir = resolve(inputArgument);
  const outputDir = resolve("dedup");
  const searchGroups = new Map<string, GroupAggregate>();
  const seenAppIds = new Set<string>();
  const files = (await readdir(resultDir))
    .filter((fileName) => fileName.endsWith(".json"))
    .sort();

  for (const fileName of files) {
    const filePath = join(resultDir, fileName);
    const result = await readResult(filePath);
    if (!result) {
      continue;
    }

    const meta = isObject(result.meta) ? result.meta : {};
    const group = meta.group;
    const term = meta.term;
    if (typeof group !== "string" || !group || typeof term !== "string" || !term) {
      continue;
    }
    if (!/^[A-Za-z0-9_-]+$/.test(group)) {
      throw new Error(`Nome de grupo inválido para criar arquivo: ${group}`);
    }

    let groupData = searchGroups.get(group);
    if (!groupData) {
      groupData = {
        meta: { group, term, sources: [] },
        apps: new Map(),
      };
      searchGroups.set(group, groupData);
    }
    if (!groupData.meta.sources.includes(fileName)) {
      groupData.meta.sources.push(fileName);
    }

    const apps = Array.isArray(result.apps) ? result.apps : [];
    for (const appValue of apps) {
      if (!isObject(appValue)) {
        continue;
      }
      const appId = appValue.appId;
      const genreId = appValue.genreId;
      if (typeof appId !== "string" || !appId || seenAppIds.has(appId)) {
        continue;
      }
      if (typeof genreId === "string" && BLOCKLISTED_GENRES.has(genreId)) {
        continue;
      }

      seenAppIds.add(appId);
      const app = Object.fromEntries(
        Object.entries(appValue).filter(([key]) => !OMIT_KEYS.has(key)),
      );
      app.term = term;
      groupData.apps.set(appId, app);
    }
  }

  await mkdir(outputDir, { recursive: true });
  console.log(`\nSalvando arquivos na pasta '${outputDir}':`);

  let totalApps = 0;
  for (const [group, groupData] of searchGroups) {
    const apps = [...groupData.apps.values()];
    groupData.meta.count = apps.length;
    await writeFile(
      join(outputDir, `${group}.json`),
      `${JSON.stringify({ meta: groupData.meta, apps }, null, 2)}\n`,
      "utf8",
    );
    totalApps += apps.length;
    console.log(` -> Salvo: ${group}.json com ${apps.length} aplicativos únicos.`);
  }

  console.log(`\nProcesso concluído! Total geral de apps únicos salvos: ${totalApps}`);
}

void main().catch((error: unknown) => {
  console.error(`Falha ao filtrar resultados: ${errorMessage(error)}`);
  process.exitCode = 1;
});
