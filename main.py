import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from src import AppSearch, SearchTerms

OUTPUT_DIR = Path("output") / f"results_{datetime.today().date()}"

app_search = AppSearch.AppSearch(number_reviews=10)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for group, group_terms in SearchTerms.terms.items():
    for term in group_terms:
        # horário de início da coleta deste termo
        collect_time = datetime.now(timezone.utc).isoformat()

        try:
            apps = app_search.search([term])
        except Exception as e:
            print(f"\n== [{group}] '{term}': ERRO -> {e}")
            continue

        print(f"\n== [{group}] {term} ({len(apps)} apps)")
        for a in apps:
            # amostra de reviews embutida em app(); descartada para não misturar com a coleta de reviews
            a.pop("comments", None)
            print(a["appId"], "|", a["title"], "|", a["genre"], "|", a["installs"])

        meta = {
            "collect_time": collect_time,
            "lib_version": version("google-play-scraper"),
            "lang": app_search._lang,
            "country": app_search._country,
            "group": group,
            "term": term,
            "result_count": len(apps),
        }
 
        path = OUTPUT_DIR / f"{SearchTerms.slugify(group)}__{SearchTerms.slugify(term)}.json"
        path.write_text(
            json.dumps({"meta": meta, "apps": apps}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )