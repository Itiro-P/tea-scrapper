"""Sampling and reference-based evaluation for the LLM-assisted FODA pipeline."""
from __future__ import annotations

import csv
import json
import math
import random
import re
import sqlite3
import unicodedata
from collections import defaultdict
import csv
from pathlib import Path
from typing import Dict, Set, DefaultDict, Any

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

_STOP = {"de", "da", "do", "das", "dos", "para", "com", "e", "em", "a", "o", "as", "os", "por",
         "ao", "aos", "na", "no", "nas", "nos", "um", "uma", "ou", "que", "se", "pelo", "pela"}


def _stems(text: str) -> frozenset[str]:
    """Radicais de 5 letras das palavras de conteúdo (o texto já vem sem acento e em minúsculas)."""
    return frozenset(w[:5] for w in re.findall(r"[a-z0-9]+", text) if w not in _STOP and len(w) > 2)


def _align(reference: set[str], other: set[str], threshold: float):
    """Pareamento guloso um-para-um por Jaccard de radicais. Devolve (pares, fp, fn)."""
    stems = {text: _stems(text) for text in (*reference, *other)}
    scored = []
    for ref in reference:
        for oth in other:
            union = stems[ref] | stems[oth]
            score = len(stems[ref] & stems[oth]) / len(union) if union else 0.0
            if score >= threshold:
                scored.append((score, ref, oth))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_ref, used_oth, pairs = set(), set(), []
    for score, ref, oth in scored:
        if ref in used_ref or oth in used_oth:
            continue
        used_ref.add(ref)
        used_oth.add(oth)
        pairs.append((ref, oth, score))
    return pairs, len(other) - len(pairs), len(reference) - len(pairs)


def _aligned_score(rows, threshold: float) -> dict:
    """rows: lista de (peso, referência, outro)."""
    tp = fp = fn = 0.0
    for weight, reference, other in rows:
        pairs, extra, missing = _align(reference, other, threshold)
        tp += len(pairs) * weight
        fp += extra * weight
        fn += missing * weight
    precision, recall, f1 = _prf(tp, fp, fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}

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


def evaluate(out: Path, reference: Path, report: Path | None = None, scope: str = "complete", threshold: float = 0.5) -> dict:
    out = out.resolve()
    reference = reference.resolve()
    checkpoint = out / "foda-checkpoint.sqlite3"
    matrix_path = out / "app-feature-matrix.csv"
    if scope not in {"complete", "all"}:
        raise ValueError("scope deve ser 'complete' ou 'all'.")
    if not 0 < threshold <= 1:
        raise ValueError("threshold deve estar em (0, 1].")
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
    reviewer_sets: dict[str, tuple[set[str], set[str]]] = {}
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
        reviewer_sets[app_id] = (reviewer1, reviewer2)

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
            "r1": reviewer_sets[app_id][0],
            "r2": reviewer_sets[app_id][1],
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
    comparisons = {
        "pipeline_vs_adjudicated": ("gold", "predicted"),
        "reviewer1_vs_adjudicated": ("gold", "r1"),
        "reviewer2_vs_adjudicated": ("gold", "r2"),
        "reviewer1_vs_reviewer2": ("r1", "r2"),   # teto humano
    }

    def aligned_block(level: float) -> dict:
        return {name: _aligned_score([(i["weight"], i[a], i[b]) for i in evaluated], level)
                for name, (a, b) in comparisons.items()}

    scores = aligned_block(threshold)
    ceiling = scores["reviewer1_vs_reviewer2"]["f1"]
    aligned_by_stratum = {}
    for name in sorted({i["stratum"] for i in evaluated}):
        rows = [(i["weight"], i["gold"], i["predicted"]) for i in evaluated if i["stratum"] == name]
        entry = _aligned_score(rows, threshold)
        entry["sample_n"] = len(rows)
        entry["reportable"] = len(rows) >= 5
        aligned_by_stratum[name] = entry
    aligned = {
        "method": "Pareamento guloso um-para-um por Jaccard de radicais (5 letras, sem stopwords); aproximação automática.",
        "threshold": threshold,
        "scores": scores,
        "pipeline_f1_relative_to_inter_rater_f1": round(scores["pipeline_vs_adjudicated"]["f1"] / ceiling, 4) if ceiling else None,
        "sensitivity_f1": {str(level): {name: value["f1"] for name, value in aligned_block(level).items()}
                        for level in (0.3, 0.4, 0.5, 0.6)},
        "per_stratum_pipeline_vs_adjudicated": aligned_by_stratum,
    }
    pair_rows = []
    for item in evaluated:
        pairs, _, _ = _align(item["gold"], item["predicted"], threshold)
        pair_rows += [{"appId": item["appId"], "gold": g, "pipeline": p, "similarity": f"{s:.2f}",
                    "alignment_correct": ""} for g, p, s in pairs]
    result = {
        "protocol": "DESMET case study; human-adjudicated reference; app-level set match after accent/case normalization",
        "scope": scope,
        "reference_file": str(reference),
        "sample_apps": len(evaluated),
        "population_estimate": sum(meta[0] for meta in strata_meta.values()),
        "aligned": aligned,
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
    pairs_path = output.with_name(output.stem + "-pares.csv")
    if pairs_path.exists():
        raise FileExistsError(f"Arquivo já existe; não será sobrescrito: {pairs_path}")
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
    _write_csv(pairs_path, ["appId", "gold", "pipeline", "similarity", "alignment_correct"], pair_rows)
    result["aligned_pairs_file"] = str(pairs_path)
    result["report"] = str(output)
    return result

def desmet_matrix(out: Path) -> Dict[str, Any]:
    # 1. Carregar mapeamentos do structure-proposals.json
    proposals_data = None
    prop_path = out / "structure-proposals.json"
    if prop_path.exists():
        with prop_path.open(encoding="utf-8-sig") as stream:
            proposals_data = json.load(stream)

    id_to_proposal_feat = {}
    name_to_proposal_id = {}
    feature_categories = {}

    if proposals_data:
        for feat in proposals_data.get("features", []):
            feat_id = feat.get("id", "").strip()
            feat_name = feat.get("name", "").strip()
            category = feat.get("category", "Geral").strip()
            if feat_id and feat_name:
                id_to_proposal_feat[feat_id] = {
                    "name": feat_name,
                    "category": category if category else "Geral",
                }
                name_to_proposal_id[feat_name] = feat_id
            if feat_name:
                feature_categories[feat_name] = category if category else "Geral"
            if feat_id:
                feature_categories[feat_id] = category if category else "Geral"

    # Carregar contagens do foda-model.json (opcional)
    foda_path = out / "foda-model.json"
    foda_model_counts = {}
    if foda_path.exists():
        with foda_path.open(encoding="utf-8-sig") as stream:
            foda_data = json.load(stream)
            for cat_obj in foda_data.get("feature_model", []):
                cat_name = cat_obj.get("name", "Sem Categoria").strip()
                for feat in cat_obj.get("features", []):
                    feat_id = feat.get("id", "").strip()
                    feat_name = feat.get("name", "").strip()
                    model_count = feat.get("observed_apps_including_incomplete", 0)
                    if feat_id:
                        foda_model_counts[feat_id] = model_count
                        if cat_name and feat_id not in feature_categories:
                            feature_categories[feat_id] = cat_name
                    if feat_name:
                        foda_model_counts[feat_name] = model_count
                        if cat_name and feat_name not in feature_categories:
                            feature_categories[feat_name] = cat_name

    # 2. Ler app-feature-matrix.csv como fonte primária
    matrix_path = out / "app-feature-matrix.csv"
    if not matrix_path.exists() or matrix_path.stat().st_size == 0:
        print(f"Aviso: O arquivo '{matrix_path}' não existe ou está vazio.")
        return {
            "status": "error",
            "message": f"Arquivo de entrada {matrix_path.name} está vazio ou ausente.",
        }

    features_info: Dict[str, Dict[str, Any]] = {}
    app_features_map: DefaultDict[str, Set[str]] = defaultdict(set)
    feature_occurrences: DefaultDict[str, int] = defaultdict(int)

    # Estruturas para análise por Categoria (Domínio de Feature)
    domain_features_map: DefaultDict[str, Set[str]] = defaultdict(set)
    app_domain_features_map: DefaultDict[str, DefaultDict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

    # Estruturas para análise por Grupo de Neurodivergência (Domínio de Grupo)
    neuro_group_features_map: DefaultDict[str, Set[str]] = defaultdict(set)
    app_neuro_group_features_map: DefaultDict[str, DefaultDict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

    # Mapeamento de grupos de neurodivergência por feature (para multi-domínio/grupo)
    feature_neuro_groups: DefaultDict[str, Set[str]] = defaultdict(set)

    # Grupos de neurodivergência gerais
    neuro_total_apps: DefaultDict[str, Set[str]] = defaultdict(set)
    neuro_feature_occurrences: DefaultDict[str, DefaultDict[str, int]] = (
        defaultdict(lambda: defaultdict(int))
    )

    # Ocorrências de Categorias de Features
    category_occurrences: DefaultDict[str, int] = defaultdict(int)
    category_total_apps: DefaultDict[str, Set[str]] = defaultdict(set)

    row_count = 0
    with matrix_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            row_count += 1
            app_id = (row.get("appId") or "").strip()
            feat_id = (row.get("feature_id") or "").strip()
            raw_feat_name = (row.get("feature") or "").strip()
            cat_name = (row.get("category") or "").strip()
            groups_str = (row.get("groups") or "").strip()

            if not app_id:
                continue

            # Mapeia e normaliza nome/ID com base no structure-proposals.json
            canonical_name = raw_feat_name
            canonical_id = feat_id

            if feat_id in id_to_proposal_feat:
                canonical_name = id_to_proposal_feat[feat_id]["name"]
                if not canonical_id:
                    canonical_id = feat_id
            elif raw_feat_name in name_to_proposal_id:
                canonical_id = name_to_proposal_id[raw_feat_name]

            if not canonical_name:
                continue

            # Determinar a categoria da feature
            feat_cat = "Geral"
            if cat_name:
                feat_cat = cat_name.split("|")[0].strip()
            elif canonical_name in feature_categories:
                feat_cat = feature_categories[canonical_name]
            elif canonical_id in feature_categories:
                feat_cat = feature_categories[canonical_id]

            # Processar grupos de neurodivergência (coluna groups)
            groups_list = []
            if groups_str:
                for g in groups_str.split("|"):
                    g_clean = g.strip()
                    if g_clean:
                        groups_list.append(g_clean)
                        feature_neuro_groups[canonical_name].add(g_clean)
            if not groups_list:
                groups_list = ["Geral"]
                feature_neuro_groups[canonical_name].add("Geral")

            # Atualizar mapas gerais
            app_features_map[app_id].add(canonical_name)
            feature_occurrences[canonical_name] += 1

            # Mapeamentos por Categoria (Domínio 1)
            domain_features_map[feat_cat].add(canonical_name)
            app_domain_features_map[feat_cat][app_id].add(canonical_name)
            category_occurrences[feat_cat] += 1
            category_total_apps[feat_cat].add(app_id)

            # Mapeamentos por Grupo de Neurodivergência (Domínio 2)
            for group in groups_list:
                neuro_total_apps[group].add(app_id)
                neuro_feature_occurrences[group][canonical_name] += 1
                neuro_group_features_map[group].add(canonical_name)
                app_neuro_group_features_map[group][app_id].add(canonical_name)

            # Registrar metadados da feature
            if canonical_name not in features_info:
                features_info[canonical_name] = {
                    "id": canonical_id,
                    "category": feat_cat,
                    "model_count": foda_model_counts.get(
                        canonical_id, foda_model_counts.get(canonical_name, 0)
                    ),
                }

    if row_count == 0 or not feature_occurrences:
        return {
            "status": "error",
            "message": "Nenhum dado válido encontrado no CSV de entrada.",
        }

    # Criar a pasta dedicada 'desmet' dentro do diretório de saída
    desmet_dir = out / "desmet"
    desmet_dir.mkdir(parents=True, exist_ok=True)

    sorted_features = sorted(
        features_info.keys(), key=lambda f: (-feature_occurrences[f], f.lower())
    )
    sorted_apps = sorted(app_features_map.keys())
    total_apps = len(sorted_apps) if sorted_apps else 1

    # 3. Gerar a Matriz Cruzada Global no formato largo (App x Feature)
    desmet_matrix_path = desmet_dir / "desmet-app-feature-matrix.csv"
    with desmet_matrix_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["appId"] + sorted_features)
        writer.writerow(
            ["TOTAL_OCORRENCIAS"] + [feature_occurrences[f] for f in sorted_features]
        )
        for app_id in sorted_apps:
            app_feats = app_features_map[app_id]
            row = [app_id] + [
                "x" if feat in app_feats else "" for feat in sorted_features
            ]
            writer.writerow(row)

    # 4. Gerar o ranking geral de features
    ranking_path = desmet_dir / "desmet-features-ranking.csv"
    with ranking_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Rank",
            "Feature_ID",
            "Feature",
            "Categoria",
            "Ocorrencias",
            "Prevalencia_%",
        ])
        for idx, feat in enumerate(sorted_features, start=1):
            occ = feature_occurrences[feat]
            pct = round((occ / total_apps) * 100, 2)
            cat = features_info[feat].get("category", "Geral")
            fid = features_info[feat].get("id", "")
            writer.writerow([idx, fid, feat, cat, occ, f"{pct}%"])

    # 5. Gerar ranking detalhado por Grupo de Neurodivergência (coluna groups)
    neuro_ranking_path = desmet_dir / "desmet-neurodivergence-ranking.csv"
    with neuro_ranking_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Neurodivergencia_Grupo",
            "Rank_No_Grupo",
            "Feature_ID",
            "Feature",
            "Ocorrencias_Neste_Grupo",
            "Total_Apps_Neste_Grupo",
            "Prevalencia_No_Grupo_%",
        ])

        for neuro in sorted(neuro_feature_occurrences.keys()):
            feats_in_neuro = neuro_feature_occurrences[neuro]
            total_apps_neuro = len(neuro_total_apps[neuro]) or 1

            sorted_neuro_feats = sorted(
                feats_in_neuro.keys(),
                key=lambda f: (-feats_in_neuro[f], f.lower()),
            )

            for r_idx, feat in enumerate(sorted_neuro_feats, start=1):
                occ_neuro = feats_in_neuro[feat]
                pct_neuro = round((occ_neuro / total_apps_neuro) * 100, 2)
                fid = features_info[feat].get("id", "")

                writer.writerow([
                    neuro,
                    r_idx,
                    fid,
                    feat,
                    occ_neuro,
                    total_apps_neuro,
                    f"{pct_neuro}%",
                ])

    # 6. Gerar relatório de ocorrência das categorias de features nos aplicativos
    categories_ranking_path = desmet_dir / "desmet-categories-ranking.csv"
    sorted_categories = sorted(
        category_occurrences.keys(),
        key=lambda c: (-category_occurrences[c], c.lower()),
    )
    with categories_ranking_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Rank",
            "Categoria",
            "Total_Ocorrencias_Features",
            "Apps_Distintos_Com_Categoria",
            "Prevalencia_Apps_%",
        ])
        for idx, cat in enumerate(sorted_categories, start=1):
            occ_cat = category_occurrences[cat]
            apps_count = len(category_total_apps[cat])
            pct_apps = round((apps_count / total_apps) * 100, 2)
            writer.writerow([
                idx,
                cat,
                occ_cat,
                apps_count,
                f"{pct_apps}%",
            ])

    # 7. Gerar relatório de features que aparecem em mais de um domínio/grupo de neurodivergência
    multi_domain_path = desmet_dir / "desmet-multi-domain-features.csv"
    with multi_domain_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Feature_ID",
            "Feature",
            "Total_Grupos_Neurodivergencia",
            "Grupos_Neurodivergencia",
        ])

        for feat in sorted_features:
            groups = feature_neuro_groups[feat]
            if len(groups) > 1:
                fid = features_info[feat].get("id", "")
                writer.writerow([
                    fid,
                    feat,
                    len(groups),
                    " | ".join(sorted(groups)),
                ])

    # 8. Avaliação de Cobertura por Categoria de Features
    category_evaluation_path = desmet_dir / "desmet-category-evaluation-scores.csv"
    with category_evaluation_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Categoria",
            "appId",
            "Features_Presentes_Na_Categoria",
            "Total_Features_Da_Categoria",
            "Indice_Cobertura_Na_Categoria_%",
        ])

        for domain in sorted_categories:
            domain_feats = sorted(domain_features_map[domain], key=lambda f: f.lower())
            total_domain_feats = len(domain_feats) or 1
            apps_in_domain = sorted(app_domain_features_map[domain].keys())

            for app_id in apps_in_domain:
                app_domain_feats = app_domain_features_map[domain][app_id]
                matched_count = len(app_domain_feats)
                coverage_domain_pct = round((matched_count / total_domain_feats) * 100, 2)

                writer.writerow([
                    domain,
                    app_id,
                    matched_count,
                    total_domain_feats,
                    f"{coverage_domain_pct}%",
                ])

    # 9. Avaliação de Cobertura por Grupo de Neurodivergência
    neuro_evaluation_path = desmet_dir / "desmet-neurodivergence-evaluation-scores.csv"
    with neuro_evaluation_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Neurodivergencia_Grupo",
            app_id_header := "appId",
            "Features_Presentes_No_Grupo",
            "Total_Features_Do_Grupo",
            "Indice_Cobertura_No_Grupo_%",
        ])

        for neuro_group in sorted(neuro_group_features_map.keys()):
            group_feats = sorted(neuro_group_features_map[neuro_group], key=lambda f: f.lower())
            total_group_feats = len(group_feats) or 1
            apps_in_group = sorted(app_neuro_group_features_map[neuro_group].keys())

            for app_id in apps_in_group:
                app_group_feats = app_neuro_group_features_map[neuro_group][app_id]
                matched_count = len(app_group_feats)
                coverage_group_pct = round((matched_count / total_group_feats) * 100, 2)

                writer.writerow([
                    neuro_group,
                    app_id,
                    matched_count,
                    total_group_feats,
                    f"{coverage_group_pct}%",
                ])

    return {
        "status": "success",
        "output_dir": str(desmet_dir),
        "desmet_matrix_path": str(desmet_matrix_path),
        "ranking_path": str(ranking_path),
        "neuro_ranking_path": str(neuro_ranking_path),
        "categories_ranking_path": str(categories_ranking_path),
        "multi_domain_path": str(multi_domain_path),
        "category_evaluation_path": str(category_evaluation_path),
        "neuro_evaluation_path": str(neuro_evaluation_path),
    }