import { mkdir, writeFile } from "node:fs/promises";
import { Config } from "./Config.js";
import SuggestionSnowball from "./SuggestionSnowball.js";
import { join } from "node:path";
import AppSearch from "./AppSearch.js";

function localDate(): string {
	const date = new Date();
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
  	const day = String(date.getDate()).padStart(2, "0");
	return `${year}-${month}-${day}`;
}

async function main(): Promise<void> {
	const outputDir = join("output", `results_${localDate()}`);
  	await mkdir(outputDir, { recursive: true });

  	const snowball = new SuggestionSnowball(Config.INITIAL_SEARCH_TERMS);
  	const terms = await snowball.snowball(Config.DEPTH);
  	await writeFile(join(outputDir, "0-terms.json"), JSON.stringify([...terms.entries()], null, 2));

	const appSearch = new AppSearch({ outputDir: outputDir });

	const apps = await appSearch.search(terms);
}

main().catch((error) => {
	console.error(error);
  	process.exit(1);
});