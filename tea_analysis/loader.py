"""Carrega os JSON agrupados em duas tabelas: pares (grupo, termo, app) e apps únicos."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .group import TERMS_SUMMARY

APP_COLUMNS = ["title", "genreId", "genre", "installs", "minInstalls", "score", "ratings", "developer", "free"]


def load_grouped(grouped_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Devolve (pairs, apps, terms_summary).

    pairs: uma linha por (grupo, termo, app) com depth, parent, rank e collect_time.
    apps: uma linha por appId (global, deduplicado entre grupos), com n_terms, n_groups e best_rank.
    """
    if not grouped_dir.is_dir():
        raise FileNotFoundError(f"{grouped_dir} não existe. Rode antes: group")
    files = sorted(p for p in grouped_dir.glob("*.json") if not p.name.startswith("_"))
    if not files:
        raise FileNotFoundError(f"Nenhum JSON de grupo em {grouped_dir}. Rode antes: group")

    pair_rows: list[dict] = []
    app_versions: dict[str, dict] = {}
    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"{file.name}: JSON inválido ({exc})") from exc
        if not isinstance(payload, dict) or "group" not in payload or "apps" not in payload:
            raise ValueError(f"{file.name}: formato inesperado (esperado: chaves 'group' e 'apps')")

        group = str(payload["group"])
        for app in payload["apps"]:
            app_id = app["appId"]
            for source in app.get("sources") or []:
                pair_rows.append({
                    "group": group,
                    "appId": app_id,
                    "term": source.get("term") or "",
                    "file": source.get("file"),
                    "depth": source.get("depth"),
                    "parent": source.get("parent"),
                    "rank": source.get("rank"),
                    "collect_time": source.get("collect_time") or "",
                })
            current = app_versions.get(app_id)
            if current is None or (not current.get("description") and app.get("description")):
                app_versions[app_id] = app

    pairs = pd.DataFrame(pair_rows, columns=["group", "appId", "term", "file", "depth", "parent", "rank", "collect_time"])
    pairs["rank"] = pd.to_numeric(pairs["rank"], errors="coerce")
    pairs["depth"] = pd.to_numeric(pairs["depth"], errors="coerce")
    pairs = (
        pairs.sort_values("collect_time", kind="stable")
        .drop_duplicates(["group", "term", "appId"])
        .reset_index(drop=True)
    )

    app_records = []
    for app_id, app in app_versions.items():
        record = {"appId": app_id}
        for column in APP_COLUMNS:
            record[column] = app.get(column)
        description = app.get("description") or ""
        record["description"] = description
        record["description_chars"] = len(description)
        app_records.append(record)
    apps = pd.DataFrame(app_records).sort_values("appId").reset_index(drop=True)
    apps["genreId"] = apps["genreId"].fillna("UNKNOWN")
    apps["genre"] = apps["genre"].fillna("")
    apps["title"] = apps["title"].fillna("")

    agg = pairs.groupby("appId").agg(
        n_terms=("term", "nunique"),
        n_groups=("group", "nunique"),
        groups=("group", lambda s: "|".join(sorted(set(s)))),
        best_rank=("rank", "min"),
    )
    apps = apps.merge(agg, on="appId", how="left")
    apps["n_terms"] = apps["n_terms"].fillna(0).astype(int)
    apps["n_groups"] = apps["n_groups"].fillna(0).astype(int)
    apps["groups"] = apps["groups"].fillna("")

    summary_path = grouped_dir / TERMS_SUMMARY
    terms_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else []
    return pairs, apps, terms_summary
