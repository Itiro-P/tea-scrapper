"""Une os JSON por termo (um por busca) em um JSON por grupo, com apps únicos por grupo."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SKIP_FILES = {"0-terms.json"}
GROUPED_DIRNAME = "grouped"
TERMS_SUMMARY = "_terms_summary.json"


def slugify(name: str) -> str:
    """'Déficit de Atenção' -> 'deficit_de_atencao' (seguro para nome de arquivo)."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _group_name_from_file(file_name: str) -> str:
    if "__" in file_name:
        return file_name.split("__", 1)[0]
    return file_name.rsplit(".json", 1)[0]


@dataclass
class UniteSummary:
    files_read: int = 0
    files_ignored: list[str] = field(default_factory=list)
    groups: int = 0
    pairs: int = 0  # pares (grupo, app); um app em dois grupos conta duas vezes
    unique_apps: int = 0  # appIds distintos entre todos os grupos
    output_dir: Path | None = None
    terms: list[dict] = field(default_factory=list)  # um registro por arquivo de termo


def unite_groups(results_dir: Path) -> UniteSummary:
    groups: dict[str, dict[str, dict]] = {}
    summary = UniteSummary()

    for file in sorted(results_dir.iterdir()):
        if file.is_dir() or not file.name.endswith(".json") or file.name in SKIP_FILES:
            continue

        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            summary.files_ignored.append(f"{file.name}: {exc}")
            continue
        if not isinstance(payload, dict):
            summary.files_ignored.append(f"{file.name}: o conteúdo não é um objeto JSON")
            continue

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        group_name = str(meta.get("group") or _group_name_from_file(file.name)).strip()
        if not group_name:
            summary.files_ignored.append(f"{file.name}: sem nome de grupo")
            continue
        term = str(meta.get("term") or "").strip()

        apps_in_file = 0
        for app in payload.get("apps") or []:
            if not isinstance(app, dict):
                continue
            app_id = app.get("appId")
            if not isinstance(app_id, str) or not app_id.strip():
                continue
            apps_in_file += 1

            entry = groups.setdefault(group_name, {}).setdefault(
                app_id, {"app": app.copy(), "sources": []}
            )
            source = {
                "term": term,
                "file": file.name,
                "depth": meta.get("depth"),
                "parent": meta.get("parent"),
                "rank": app.get("rank"),
                "collect_time": meta.get("collect_time"),
            }
            if source not in entry["sources"]:
                entry["sources"].append(source)
            # fica com a versão que tem descrição
            if not entry["app"].get("description") and app.get("description"):
                entry["app"] = app.copy()

        summary.files_read += 1
        summary.terms.append({
            "file": file.name,
            "group": group_name,
            "term": term,
            "depth": meta.get("depth"),
            "parent": meta.get("parent"),
            "collect_time": meta.get("collect_time"),
            "result_count": meta.get("result_count"),
            "apps_in_file": apps_in_file,
            "failed_app_ids": meta.get("failed_app_ids") or [],
        })

    # nomes de arquivo por grupo, checando colisões antes de apagar qualquer coisa
    slugs: dict[str, str] = {}
    for group_name in groups:
        slug = slugify(group_name)
        if not slug or slug in slugs:
            raise ValueError(
                f"Os grupos {slugs.get(slug)!r} e {group_name!r} geram o mesmo nome de arquivo ({slug!r})."
            )
        slugs[slug] = group_name

    output_dir = results_dir / GROUPED_DIRNAME
    output_dir.mkdir(exist_ok=True)
    for old in output_dir.glob("*.json"):  # pasta derivada: é regerada do zero
        old.unlink()

    for slug, group_name in sorted(slugs.items()):
        apps = []
        for app_id, data in sorted(groups[group_name].items(), key=lambda item: item[0].lower()):
            app = data["app"].copy()
            app.pop("rank", None)
            app["sources"] = sorted(
                data["sources"],
                key=lambda s: (
                    s.get("depth") is None,
                    s.get("depth") if s.get("depth") is not None else 0,
                    str(s.get("term") or ""),
                    str(s.get("file") or ""),
                ),
            )
            apps.append(app)

        result = {"group": group_name, "app_count": len(apps), "apps": apps}
        with (output_dir / f"{slug}.json").open("w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    with (output_dir / TERMS_SUMMARY).open("w", encoding="utf-8") as fh:
        json.dump(summary.terms, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    summary.groups = len(groups)
    summary.pairs = sum(len(apps_by_id) for apps_by_id in groups.values())
    summary.unique_apps = len({app_id for apps_by_id in groups.values() for app_id in apps_by_id})
    summary.output_dir = output_dir
    return summary
