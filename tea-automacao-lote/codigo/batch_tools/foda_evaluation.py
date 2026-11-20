"""Sampling and reference-based evaluation for the LLM-assisted FODA pipeline."""
from __future__ import annotations

import csv
import json
import math
import random
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


REFERENCE_FIELDS = [
    "appId", "stratum", "population_n", "sample_n", "sample_weight", "title", "description",
    "technical_complete", "extraction_status", "reviewer1_features_json", "reviewer2_features_json",
    "adjudicated_features_json", "adjudicated_complete", "reviewer1_id", "reviewer2_id",
    "adjudicator_id", "notes",
]

ANNOTATION_PROTOCOL = """PROTOCOLO DE ANOTAÇÃO (mesmo critério do prompt de extração)

Liste somente capacidades que o aplicativo permite executar AGORA e que foram projetadas para uma
necessidade neurodivergente (comunicação, regulação sensorial ou emocional, atenção, rotina e funções
executivas, interação social, aprendizagem adaptada, apoio a terapeutas ou cuidadores ligado a essa necessidade).

NÃO liste: funcionalidades genéricas que qualquer aplicativo teria (login, conta, assinatura, pagamento,
anúncios, configurações, modo escuro, offline, sincronização, compartilhamento, acompanhamento de progresso
genérico), a menos que a descrição as ligue explicitamente a uma necessidade neurodivergente.
NÃO liste benefícios esperados, público-alvo, elogios, eficácia clínica, depoimentos, outros apps ou planos futuros.

Vocabulário: use os nomes do arquivo *-vocabulario.csv. Só crie um nome novo se nenhum nome da lista
descrever a capacidade; nesse caso, escreva um nome curto de ação em português.

Formato: em reviewer1_features_json e reviewer2_features_json, um array JSON de nomes (pode ser vazio: []).
Os dois revisores anotam de forma independente; a adjudicação vai em adjudicated_features_json e
adjudicated_complete=true.
"""


def _norm(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _prf(tp: float, fp: float, fn: float) -> tuple[float, float, float]:
    """One convention everywhere: nothing predicted and nothing expected counts as perfect."""
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if fp == 0 else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


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


def _allocation(strata: dict[str, list[dict]], requested: int, min_per_stratum: int = 2) -> dict[str, int]:
    """Square-root allocation with a minimum floor per stratum to prevent high weights on rare domains."""
    strata = {k: v for k, v in strata.items() if v}
    population = sum(len(items) for items in strata.values())

    if population == 0:
        raise ValueError("População total nos estratos é zero.")
    if requested < 1:
        raise ValueError("sample-size deve ser positivo.")
    if requested > population:
        raise ValueError(f"sample-size ({requested}) excede os {population} apps disponíveis.")

    # Piso efetivo por estrato (respeita o tamanho máximo se o estrato tiver menos itens que min_per_stratum)
    floors = {key: min(len(items), min_per_stratum) for key, items in strata.items()}
    min_required = sum(floors.values())

    if requested < min_required:
        raise ValueError(
            f"sample-size ({requested}) é menor que o mínimo necessário ({min_required}) "
            f"para cobrir os {len(strata)} estratos com piso de {min_per_stratum}."
        )

    # Pesos pela raiz quadrada do tamanho de cada estrato
    sqrt_weights = {key: math.sqrt(len(items)) for key, items in strata.items()}
    total_sqrt = sum(sqrt_weights.values())

    allocated: dict[str, int] = {}
    for key, items in strata.items():
        raw_val = requested * (sqrt_weights[key] / total_sqrt)
        val = max(floors[key], min(len(items), int(round(raw_val))))
        allocated[key] = val

    # Ajuste fino para garantir que sum(allocated.values()) == requested
    diff = requested - sum(allocated.values())
    while diff != 0:
        changed = False
        if diff > 0:
            # Adiciona nos estratos que ainda possuem elementos disponíveis
            candidates = sorted(
                strata,
                key=lambda k: (len(strata[k]) - allocated[k], -allocated[k]),
                reverse=True,
            )
            for key in candidates:
                if allocated[key] < len(strata[key]):
                    allocated[key] += 1
                    diff -= 1
                    changed = True
                    if diff == 0:
                        break
        else:
            # Remove dos maiores estratos que estão acima do seu piso mínimo
            candidates = sorted(
                strata,
                key=lambda k: allocated[k] - floors[k],
                reverse=True,
            )
            for key in candidates:
                if allocated[key] > floors[key]:
                    allocated[key] -= 1
                    diff += 1
                    changed = True
                    if diff == 0:
                        break
        if not changed:
            raise ValueError("Não foi possível equilibrar a alocação da amostra aos estratos.")

    return allocated


def _vocabulary_rows(matrix_path: Path) -> list[dict[str, Any]]:
    """Canonical names present in the exported matrix, with how many apps use each."""
    apps_by_feature: dict[tuple[str, str], set[str]] = {}
    with matrix_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            apps_by_feature.setdefault((row["feature"], row["category"]), set()).add(row["appId"])
    return [
        {"feature": feature, "category": category, "apps": len(ids)}
        for (feature, category), ids in sorted(apps_by_feature.items(), key=lambda kv: (kv[0][1], kv[0][0].casefold()))
    ]


def create_sample(out: Path, sample_size: int, seed: int = 42,
                  output: Path | None = None, scope: str = "complete",
                  min_stratum_size: int = 1, min_per_stratum: int = 2) -> dict:
    out = out.resolve()
    checkpoint = out / "foda-checkpoint.sqlite3"
    matrix_path = out / "app-feature-matrix.csv"
    if not checkpoint.is_file():
        raise ValueError(f"Checkpoint FODA não encontrado em {out}; rode prepare primeiro.")
    if not matrix_path.is_file():
        raise ValueError("app-feature-matrix.csv ausente; rode export antes (o vocabulário sai dele).")
    if seed < 0:
        raise ValueError("seed deve ser não negativo.")
    if scope not in {"complete", "all"}:
        raise ValueError("scope deve ser 'complete' ou 'all'.")
    path = (output or out / "desmet-reference-template.csv").resolve()
    protocol_path = path.with_name(path.stem + "-protocolo.txt")
    vocabulary_path = path.with_name(path.stem + "-vocabulario.csv")
    for target in (path, protocol_path, vocabulary_path):
        if target.exists():
            raise FileExistsError(f"Arquivo já existe; não será sobrescrito: {target}")
    with sqlite3.connect(checkpoint) as db:
        db.row_factory = sqlite3.Row
        manifest_row = db.execute("SELECT value FROM meta WHERE key='input_manifest'").fetchone()
        if not manifest_row:
            raise ValueError("Checkpoint FODA sem manifesto de entrada.")
        manifest = json.loads(manifest_row["value"])
        where = "WHERE a.technical_complete=1" if scope == "complete" else ""
        apps = db.execute(
            f"SELECT a.* FROM apps a {where} ORDER BY a.app_id"
        ).fetchall()
    if not apps:
        raise ValueError("Nenhum app na população escolhida (scope=%s)." % scope)
    corpus_path = Path(manifest["input_dir"]) / "corpus.jsonl"
    if not corpus_path.is_file():
        raise FileNotFoundError(f"Corpus original não encontrado: {corpus_path}")
    from batch_core import file_sha as source_file_sha
    if source_file_sha(corpus_path) != manifest["input_hashes"]["corpus.jsonl"]:
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

    # Stratum = the rarest group of the app, with fallback if domain has too few elements.
    group_counts = Counter(g for app in apps for g in json.loads(app["groups_json"]))
    strata: dict[str, list[dict]] = {}
    for app in apps:
        app_id = app["app_id"]
        record = corpus.get(app_id)
        if record is None:
            raise ValueError(f"App ausente do corpus: {app_id}.")
        groups = json.loads(app["groups_json"])
        sorted_groups = sorted(groups, key=lambda g: (group_counts[g], g)) if groups else ["UNKNOWN"]

        chosen_stratum = "UNKNOWN"
        for g in sorted_groups:
            if group_counts[g] >= min_stratum_size or g == sorted_groups[-1]:
                chosen_stratum = g
                break

        strata.setdefault(chosen_stratum, []).append({
            "appId": app_id,
            "stratum": chosen_stratum,
            "title": app["title"],
            "description": str(record.get("description") or ""),
            "technical_complete": bool(app["technical_complete"]),
            "extraction_status": app["extraction_status"],
        })

    strata = {k: v for k, v in strata.items() if v}

    allocated = _allocation(strata, sample_size, min_per_stratum=min_per_stratum)
    rng = random.Random(seed)
    rows = []
    for stratum in sorted(strata):
        population_n = len(strata[stratum])
        sample_n_stratum = allocated.get(stratum, 0)
        if sample_n_stratum <= 0:
            continue
        selected = rng.sample(strata[stratum], sample_n_stratum)
        weight = population_n / sample_n_stratum
        for item in selected:
            rows.append({
                **item,
                "population_n": population_n,
                "sample_n": sample_n_stratum,
                "sample_weight": f"{weight:.8f}",
                "reviewer1_features_json": "", "reviewer2_features_json": "",
                "adjudicated_features_json": "", "adjudicated_complete": "",
                "reviewer1_id": "", "reviewer2_id": "", "adjudicator_id": "", "notes": "",
            })
    rows.sort(key=lambda row: (row["stratum"], row["appId"]))
    _write_csv(path, REFERENCE_FIELDS, rows)
    _write_csv(vocabulary_path, ["feature", "category", "apps"], _vocabulary_rows(matrix_path))
    protocol_path.write_text(ANNOTATION_PROTOCOL, encoding="utf-8")
    return {
        "output": str(path),
        "protocol": str(protocol_path),
        "vocabulary": str(vocabulary_path),
        "scope": scope,
        "population_apps": len(apps),
        "sample_apps": len(rows),
        "strata": len(strata),
        "seed": seed,
        "review_instruction": (
            "Dois revisores anotam independentemente, seguindo o protocolo e o vocabulário; "
            "adjudicar em adjudicated_features_json e marcar adjudicated_complete=true."
        ),
    }


def _feature_set(value: str, field: str, app_id: str) -> set[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} inválido para {app_id}: use JSON array de nomes (pode ser []).") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item.strip() for item in parsed):
        raise ValueError(f"{field} inválido para {app_id}: esperado array de strings não vazias (o array pode ser vazio).")
    normalized = {_norm(item) for item in parsed}
    if "" in normalized:
        raise ValueError(f"{field} contém funcionalidade vazia para {app_id}.")
    return normalized


def evaluate(out: Path, reference: Path, report: Path | None = None, scope: str = "complete") -> dict:
    out = out.resolve()
    reference = reference.resolve()
    checkpoint = out / "foda-checkpoint.sqlite3"
    matrix_path = out / "app-feature-matrix.csv"
    if scope not in {"complete", "all"}:
        raise ValueError("scope deve ser 'complete' ou 'all'.")
    if not checkpoint.is_file() or not matrix_path.is_file():
        raise ValueError("Checkpoint ou app-feature-matrix.csv ausente; conclua run e export primeiro.")
    with sqlite3.connect(checkpoint) as db:
        db.row_factory = sqlite3.Row
        incomplete = db.execute("SELECT COUNT(*) FROM batches WHERE state!='complete'").fetchone()[0]
        if incomplete:
            raise ValueError(f"Há {incomplete} lotes FODA não concluídos; avaliação requer a execução completa.")
        population_ids = {row[0] for row in db.execute("SELECT app_id FROM apps")}
        complete_ids = {row[0] for row in db.execute("SELECT app_id FROM apps WHERE technical_complete=1")}
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
        if scope == "complete" and app_id not in complete_ids:
            raise ValueError(f"App {app_id} não é technical_complete; use scope='all' ou refaça a amostra.")
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
    vocabulary: set[str] = set()
    with matrix_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            name = _norm(row["feature"])
            vocabulary.add(name)
            if row["appId"] in reference_ids:
                predictions.setdefault(row["appId"], set()).add(name)

    strata_meta: dict[str, tuple[int, int]] = {}
    evaluated = []
    out_of_vocabulary: Counter[str] = Counter()
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
        out_of_vocabulary.update(gold - vocabulary)
        evaluated.append({
            "appId": app_id,
            "stratum": stratum,
            "weight": population_n / sample_n,
            "gold": gold,
            "predicted": predictions.get(app_id, set()),
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
        app_scores.append(_prf(tp, fp, fn))
        stratum = per_stratum.setdefault(item["stratum"], {
            "population_n": 0.0, "sample_n": 0.0, "tp": 0.0, "fp": 0.0, "fn": 0.0,
        })
        stratum["population_n"] = item["weight"] * actual_sample_counts[item["stratum"]]
        stratum["sample_n"] += 1
        stratum["tp"] += tp
        stratum["fp"] += fp
        stratum["fn"] += fn

    precision, recall, f1 = _prf(weighted_tp, weighted_fp, weighted_fn)
    reviewer_jaccards = []
    reviewer_exact_matches = 0
    for reviewer1, reviewer2 in reviewer_pairs:
        union = reviewer1 | reviewer2
        reviewer_jaccards.append(len(reviewer1 & reviewer2) / len(union) if union else 1.0)
        reviewer_exact_matches += reviewer1 == reviewer2
    stratum_reports = {}
    for key, values in sorted(per_stratum.items()):
        p, r, f = _prf(values["tp"], values["fp"], values["fn"])
        stratum_reports[key] = {**values, "precision": p, "recall": r, "f1": f}
    result = {
        "protocol": "DESMET case study; human-adjudicated reference; app-level set match after accent/case normalization",
        "scope": scope,
        "reference_file": str(reference),
        "sample_apps": len(evaluated),
        "population_estimate": sum(meta[0] for meta in strata_meta.values()),
        "weighted_micro": {
            "tp": weighted_tp, "fp": weighted_fp, "fn": weighted_fn,
            "precision": precision, "recall": recall, "f1": f1,
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
        "gold_out_of_vocabulary": {
            "distinct_labels": len(out_of_vocabulary),
            "occurrences": sum(out_of_vocabulary.values()),
            "top_labels": out_of_vocabulary.most_common(50),
            "note": "Rótulos adjudicados que não existem no vocabulário do pipeline. Podem ser falhas reais de "
                    "extração ou só diferença de redação; revise antes de interpretar o recall.",
        },
        "per_stratum": stratum_reports,
        "limitations": [
            "Acurácia é relativa à descrição e à referência humana, não ao comportamento do app instalado.",
            "Com scope='complete', mede só a extração sobre apps já classificados como relevantes; "
            "a acurácia do classificador de relevância precisa de avaliação própria.",
            "Equivalência semântica é pontuada por rótulo após normalização de acento/caixa; "
            "o vocabulário compartilhado reduz, mas não elimina, diferenças de redação.",
            "A amostra e seus pesos precisam representar o universo definido; a estimativa não cobre apps excluídos da população.",
            "DESMET avalia o processo e a evidência; métricas não tornam o modelo FODA semanticamente completo por si sós.",
        ],
    }
    output = (report or out / "desmet-report.json").resolve()
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