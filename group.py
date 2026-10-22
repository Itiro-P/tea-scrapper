import json
from sys import argv, exit
import pathlib


def _slugify_group(name: str) -> str:
    return (
        name.strip()
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _group_name_from_file(file_name: str) -> str:
    if "__" in file_name:
        return file_name.split("__", 1)[0]
    return file_name.rsplit(".json", 1)[0]


def unite_groups(path: pathlib.Path):
    groups: dict[str, dict[str, dict]] = {}

    for file in sorted(path.iterdir()):
        if file.is_dir() or not file.name.endswith(".json") or file.name == "0-terms.json":
            continue

        try:
            with file.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Ignorando {file.name}: {exc}")
            continue

        if not isinstance(payload, dict):
            continue

        meta = payload.get("meta", {})
        group_name = str(meta.get("group") or _group_name_from_file(file.name)).strip()
        if not group_name:
            continue

        for app in payload.get("apps", []):
            if not isinstance(app, dict):
                continue

            app_id = app.get("appId")
            if not isinstance(app_id, str) or not app_id.strip():
                continue

            app_entry = groups.setdefault(group_name, {}).setdefault(app_id, {
                "app": app.copy(),
                "sources": [],
            })

            term = str(meta.get("term") or "").strip()

            source = {
                "term": term,
                "file": file.name,
                "depth": meta.get("depth"),
                "parent": meta.get("parent"),
                "rank": app.get("rank"),
            }
            if source not in app_entry["sources"]:
                app_entry["sources"].append(source)

            if not app_entry["app"].get("description") and app.get("description"):
                app_entry["app"] = app.copy()

    output_dir = path / "grouped"
    output_dir.mkdir(exist_ok=True)

    for group_name, apps_by_id in sorted(groups.items()):
        apps = []
        for app_id, data in sorted(apps_by_id.items(), key=lambda item: item[0].lower()):
            app = data["app"].copy()
            app.pop("rank", None)
            app["sources"] = sorted(
                data["sources"],
                key=lambda item: (
                    item.get("depth") is not None,
                    item.get("depth") if item.get("depth") is not None else 999,
                    str(item.get("term") or ""),
                    str(item.get("file") or ""),
                ),
            )
            apps.append(app)

        result = {
            "group": group_name,
            "app_count": len(apps),
            "apps": apps,
        }

        filename = f"{_slugify_group(group_name)}.json"
        with (output_dir / filename).open("w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    print(f"Agrupados {sum(len(apps) for apps in (group.values() for group in groups.values()))} appIds em {len(groups)} grupos.")


def main():
    argc = len(argv)
    if argc <= 1:
        print(f"Uso: {argv[0]} <pasta_com_jsons>")
        exit(1)

    result_path = pathlib.Path(argv[1])
    if not result_path.exists():
        print(f"Diretório {argv[1]} não existe")
        exit(1)
    if not result_path.is_dir():
        print(f"Diretório {argv[1]} não é um diretório")
        exit(1)

    unite_groups(result_path)


if __name__ == "__main__":
    main()