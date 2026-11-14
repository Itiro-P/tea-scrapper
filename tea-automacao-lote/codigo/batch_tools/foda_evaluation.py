"""Sampling and reference-based evaluation for the LLM-assisted FODA pipeline."""
from __future__ import annotations

import csv
import json
import random
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


REFERENCE_FIELDS = [
    "appId",
    "stratum",
    "population_n",
    "sample_n",
    "sample_weight",
    "title",
    "description",
    "technical_complete",
    "extraction_status",
    "reviewer1_features_json",
    "reviewer2_features_json",
    "adjudicated_features_json",
    "adjudicated_complete",
    "reviewer1_id",
    "reviewer2_id",
    "adjudicator_id",
    "notes",
]


def _norm(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"Arquivo já existe; não será sobrescrito: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def _allocation(strata: dict[str, list[dict]], requested: int) -> dict[str, int]:
    population = sum(len(items) for items in strata.values())
    if requested < 1:
        raise ValueError("sample-size deve ser positivo.")
    if requested > population:
        raise ValueError(f"sample-size ({requested}) excede os {population} apps disponíveis.")
    if requested < len(strata):
        raise ValueError(
            f"sample-size precisa ser pelo menos {len(strata)} para incluir todos os estratos."
        )
    exact = {key: requested * len(items) / population for key, items in strata.items()}
    allocated = {key: min(len(strata[key]), int(value)) for key, value in exact.items()}
    remaining = requested - sum(allocated.values())
    order = sorted(strata, key=lambda key: (-(exact[key] - int(exact[key])), key))
    while remaining:
        changed = False
        for key in order:
            if allocated[key] < len(strata[key]):
                allocated[key] += 1
                remaining -= 1
                changed = True
                if remaining == 0:
                    break
        if not changed:
            raise ValueError("Não foi possível alocar a amostra aos estratos.")
    return allocated


def create_sample(out: Path, sample_size: int, seed: int = 42,
                  output: Path | None = None) -> dict:
    out = out.resolve()
    checkpoint = out / "foda-checkpoint.sqlite3"
    if not checkpoint.is_file():
        raise ValueError(f"Checkpoint FODA não encontrado em {out}; rode prepare primeiro.")
    if seed < 0:
        raise ValueError("seed deve ser não negativo.")
    with sqlite3.connect(checkpoint) as db:
        db.row_factory = sqlite3.Row
        manifest_row = db.execute("SELECT value FROM meta WHERE key='input_manifest'").fetchone()
        if not manifest_row:
            raise ValueError("Checkpoint FODA sem manifesto de entrada.")
        manifest = json.loads(manifest_row["value"])
        apps = db.execute(
            """SELECT a.*, EXISTS(SELECT 1 FROM source_rows r WHERE r.app_id=a.app_id) AS has_features
            FROM apps a ORDER BY a.app_id"""
        ).fetchall()
    corpus_path = Path(manifest["input_dir"]) / "corpus.jsonl"
    if not corpus_path.is_file():
        raise FileNotFoundError(f"Corpus original não encontrado: {corpus_path}")
    from batch_core import file_sha as source_file_sha
    expected_hash = manifest["input_hashes"]["corpus.jsonl"]
    if source_file_sha(corpus_path) != expected_hash:
        raise ValueError("corpus.jsonl mudou desde prepare; não é seguro criar uma amostra.")
    corpus: dict[str, dict] = {}
    with corpus_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"corpus.jsonl:{line_number}: JSON inválido ({exc}).") from exc
            app_id = record.get("appId") if isinstance(record, dict) else None
            if not isinstance(app_id, str) or app_id in corpus:
                raise ValueError(f"corpus.jsonl:{line_number}: appId inválido ou duplicado.")
            corpus[app_id] = record

    strata: dict[str, list[dict]] = {}
    for app in apps:
        app_id = app["app_id"]
        record = corpus.get(app_id)
        if record is None:
            raise ValueError(f"App ausente do corpus: {app_id}.")
        groups = json.loads(app["groups_json"])
        primary_group = sorted(groups)[0] if groups else "UNKNOWN"
        stratum = primary_group
        strata.setdefault(stratum, []).append({
            "appId": app_id,
            "stratum": stratum,
            "title": app["title"],
            "description": str(record.get("description") or ""),
            "technical_complete": bool(app["technical_complete"]),
            "extraction_status": app["extraction_status"],
        })

    allocated = _allocation(strata, sample_size)
    rng = random.Random(seed)
    rows = []
    for stratum in sorted(strata):
        population_n = len(strata[stratum])
        selected = rng.sample(strata[stratum], allocated[stratum])
        weight = population_n / allocated[stratum] if allocated[stratum] else 0
        for item in selected:
            rows.append({
                **item,
                "population_n": population_n,
                "sample_n": allocated[stratum],
                "sample_weight": f"{weight:.8f}",
                "reviewer1_features_json": "",
                "reviewer2_features_json": "",
                "adjudicated_features_json": "",
                "adjudicated_complete": "",
                "reviewer1_id": "",
                "reviewer2_id": "",
                "adjudicator_id": "",
                "notes": "",
            })
    rows.sort(key=lambda row: (row["stratum"], row["appId"]))
    path = (output or out / "desmet-reference-template.csv").resolve()
    _write_csv(path, REFERENCE_FIELDS, rows)
    return {
        "output": str(path),
        "population_apps": len(apps),
        "sample_apps": len(rows),
        "strata": len(strata),
        "seed": seed,
        "review_instruction": (
            "Dois revisores anotam independentemente listas JSON de funcionalidades; "
            "adjudicar em adjudicated_features_json e marcar adjudicated_complete=true."
        ),
    }


def _feature_set(value: str, field: str, app_id: str) -> set[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} inválido para {app_id}: use JSON array de nomes.") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item.strip() for item in parsed):
        raise ValueError(f"{field} inválido para {app_id}: esperado array não vazio de strings.")
    normalized = {_norm(item) for item in parsed}
    if "" in normalized:
        raise ValueError(f"{field} contém funcionalidade vazia para {app_id}.")
    return normalized


def evaluate(out: Path, reference: Path, report: Path | None = None) -> dict:
    out = out.resolve()
    reference = reference.resolve()
    checkpoint = out / "foda-checkpoint.sqlite3"
    matrix_path = out / "app-feature-matrix.csv"
    if not checkpoint.is_file() or not matrix_path.is_file():
        raise ValueError("Checkpoint ou app-feature-matrix.csv ausente; conclua run e export primeiro.")
    with sqlite3.connect(checkpoint) as db:
        db.row_factory = sqlite3.Row
        incomplete = db.execute("SELECT COUNT(*) FROM batches WHERE state!='complete'").fetchone()[0]
        if incomplete:
            raise ValueError(f"Há {incomplete} lotes FODA não concluídos; avaliação requer a execução completa.")
        population_ids = {row[0] for row in db.execute("SELECT app_id FROM apps")}
    with reference.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(REFERENCE_FIELDS).issubset(reader.fieldnames):
            raise ValueError("Referência precisa ser o template de DESMET completo.")
        ref_rows = list(reader)
    if not ref_rows:
        raise ValueError("Referência humana vazia.")
    reference_ids: set[str] = set()
    reviewer_pairs: list[tuple[set[str], set[str]]] = []
    actual_sample_counts: Counter[str] = Counter()
    for row in ref_rows:
        app_id = (row.get("appId") or "").strip()
        if not app_id or app_id in reference_ids:
            raise ValueError(f"appId ausente ou duplicado na referência: {app_id}.")
        reference_ids.add(app_id)
        if app_id not in population_ids:
            raise ValueError(f"App fora da população do checkpoint: {app_id}.")
        actual_sample_counts[row["stratum"]] += 1
        if (row.get("adjudicated_complete") or "").strip().casefold() not in {"true", "yes", "1"}:
            raise ValueError(f"Anotação adjudicada incompleta para {app_id}.")
        if not (row.get("reviewer1_id") or "").strip() or not (row.get("reviewer2_id") or "").strip():
            raise ValueError(f"Identificação dos dois revisores ausente para {app_id}.")
        if (row.get("reviewer1_id") or "").strip() == (row.get("reviewer2_id") or "").strip():
            raise ValueError(f"Os dois revisores devem ser pessoas distintas para {app_id}.")
        if not (row.get("adjudicator_id") or "").strip():
            raise ValueError(f"Identificação de adjudicação ausente para {app_id}.")
        reviewer1 = _feature_set(row.get("reviewer1_features_json") or "", "reviewer1_features_json", app_id)
        reviewer2 = _feature_set(row.get("reviewer2_features_json") or "", "reviewer2_features_json", app_id)
        _feature_set(row.get("adjudicated_features_json") or "", "adjudicated_features_json", app_id)
        reviewer_pairs.append((reviewer1, reviewer2))

    predictions: dict[str, set[str]] = {}
    with matrix_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            app_id = row["appId"]
            if app_id in reference_ids:
                predictions.setdefault(app_id, set()).add(_norm(row["feature"]))

    strata_meta: dict[str, tuple[int, int]] = {}
    evaluated = []
    for row in ref_rows:
        app_id = row["appId"].strip()
        stratum = row["stratum"]
        population_n = int(row["population_n"])
        sample_n = int(row["sample_n"])
        if population_n < sample_n or sample_n < 1:
            raise ValueError(f"Pesos de amostragem inválidos no estrato {stratum}.")
        old = strata_meta.setdefault(stratum, (population_n, sample_n))
        if old != (population_n, sample_n):
            raise ValueError(f"Metadados de amostragem inconsistentes no estrato {stratum}.")
        if actual_sample_counts[stratum] != sample_n:
            raise ValueError(
                f"A amostra do estrato {stratum} está incompleta: "
                f"{actual_sample_counts[stratum]} de {sample_n} apps."
            )
        gold = _feature_set(row["adjudicated_features_json"], "adjudicated_features_json", app_id)
        predicted = predictions.get(app_id, set())
        evaluated.append({
            "appId": app_id,
            "stratum": stratum,
            "weight": population_n / sample_n,
            "gold": gold,
            "predicted": predicted,
        })

    weighted_tp = weighted_fp = weighted_fn = 0.0
    app_scores = []
    per_stratum: dict[str, dict[str, float]] = {}
    for item in evaluated:
        gold, predicted, weight = item["gold"], item["predicted"], item["weight"]
        tp = len(gold & predicted)
        fp = len(predicted - gold)
        fn = len(gold - predicted)
        weighted_tp += tp * weight
        weighted_fp += fp * weight
        weighted_fn += fn * weight
        precision = tp / (tp + fp) if tp + fp else (1.0 if not gold else 0.0)
        recall = tp / (tp + fn) if tp + fn else (1.0 if not predicted else 0.0)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        app_scores.append((precision, recall, f1))
        stratum = per_stratum.setdefault(item["stratum"], {
            "population_n": 0.0,
            "sample_n": 0.0,
            "tp": 0.0,
            "fp": 0.0,
            "fn": 0.0,
        })
        stratum["population_n"] = item["weight"] * actual_sample_counts[item["stratum"]]
        stratum["sample_n"] += 1
        stratum["tp"] += tp
        stratum["fp"] += fp
        stratum["fn"] += fn

    precision = weighted_tp / (weighted_tp + weighted_fp) if weighted_tp + weighted_fp else 0.0
    recall = weighted_tp / (weighted_tp + weighted_fn) if weighted_tp + weighted_fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    reviewer_jaccards = []
    reviewer_exact_matches = 0
    for reviewer1, reviewer2 in reviewer_pairs:
        union = reviewer1 | reviewer2
        reviewer_jaccards.append(len(reviewer1 & reviewer2) / len(union) if union else 1.0)
        reviewer_exact_matches += reviewer1 == reviewer2
    stratum_reports = {}
    for key, values in sorted(per_stratum.items()):
        tp, fp, fn = values["tp"], values["fp"], values["fn"]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        stratum_reports[key] = {
            **values,
            "precision": p,
            "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0,
        }
    result = {
        "protocol": "DESMET case study; human-adjudicated reference; app-level set match after accent/case normalization",
        "reference_file": str(reference),
        "sample_apps": len(evaluated),
        "population_estimate": sum(meta[0] for meta in strata_meta.values()),
        "weighted_micro": {
            "tp": weighted_tp,
            "fp": weighted_fp,
            "fn": weighted_fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "unweighted_macro_app": {
            "precision": sum(score[0] for score in app_scores) / len(app_scores),
            "recall": sum(score[1] for score in app_scores) / len(app_scores),
            "f1": sum(score[2] for score in app_scores) / len(app_scores),
        },
        "exact_app_match": sum(item["gold"] == item["predicted"] for item in evaluated) / len(evaluated),
        "inter_rater_agreement": {
            "exact_set_match": reviewer_exact_matches / len(reviewer_pairs),
            "mean_jaccard": sum(reviewer_jaccards) / len(reviewer_jaccards),
            "apps": len(reviewer_pairs),
        },
        "per_stratum": stratum_reports,
        "limitations": [
            "Acurácia é relativa à descrição e à referência humana, não ao comportamento do app instalado.",
            "Equivalência semântica é pontuada por rótulo adjudicado após apenas normalização de acento/caixa; alinhe sinônimos no protocolo de anotação.",
            "A amostra e seus pesos precisam representar o universo definido; a estimativa não cobre apps excluídos da população de entrada.",
            "DESMET avalia o processo e a evidência; métricas não tornam o modelo FODA semanticamente completo por si sós.",
        ],
    }
    output = report or out / "desmet-report.json"
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Relatório já existe; não será sobrescrito: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temp.replace(output)
    finally:
        if temp.exists():
            temp.unlink()
    result["report"] = str(output)
    return result
