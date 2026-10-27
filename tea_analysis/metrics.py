"""Núcleo da análise: funções puras que recebem tabelas e devolvem tabelas (sem I/O)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LABEL_RELEVANT = "relevante"
LABEL_NOISE = "nao_relevante"
LABEL_UNSURE = "incerto"
VALID_LABELS = {LABEL_RELEVANT, LABEL_NOISE, LABEL_UNSURE}

N_TERMS_LABELS = ["1", "2-3", "4+"]
RANK_LABELS = ["1-10", "11-30", "31+"]
BY_COLUMNS = ["genre_top", "n_terms_band", "rank_band"]


# --- Funil --------------------------------------------------------------------
def funnel(pairs: pd.DataFrame, apps: pd.DataFrame, terms_summary: list[dict]) -> tuple[dict, pd.DataFrame]:
    """Contagens do funil e tabela por grupo."""
    result: dict = {}
    if terms_summary:
        counts = [t["result_count"] for t in terms_summary if t.get("result_count") is not None]
        result["terms_searched"] = len(terms_summary)
        result["results_returned"] = int(sum(counts))
        result["details_failed"] = int(sum(len(t.get("failed_app_ids") or []) for t in terms_summary))
    pairs_with_details = len(pairs[["term", "appId"]].drop_duplicates())
    unique_apps = int(apps["appId"].nunique())
    result["pairs_with_details"] = pairs_with_details
    result["unique_apps"] = unique_apps
    result["mean_appearances_per_app"] = round(pairs_with_details / unique_apps, 2) if unique_apps else 0.0
    result["apps_in_multiple_groups"] = int((apps["n_groups"] > 1).sum())
    result["apps_with_single_term"] = int((apps["n_terms"] == 1).sum())

    per_group = pairs.groupby("group").agg(
        terms=("term", "nunique"),
        pairs=("appId", "size"),
        unique_apps=("appId", "nunique"),
    )
    only_in = apps[apps["n_groups"] == 1].groupby("groups").size()
    per_group["exclusive_apps"] = only_in.reindex(per_group.index).fillna(0).astype(int)
    per_group = per_group.sort_values("unique_apps", ascending=False).reset_index()
    return result, per_group


# --- Termos por app e gêneros ------------------------------------------------------
def terms_per_app(apps: pd.DataFrame) -> pd.DataFrame:
    """Distribuição do número de termos distintos que encontraram cada app."""
    dist = apps["n_terms"].value_counts().sort_index().rename_axis("n_terms").reset_index(name="n_apps")
    dist["share"] = dist["n_apps"] / dist["n_apps"].sum()
    dist["cumulative_share"] = dist["share"].cumsum()
    return dist


def genre_table(apps: pd.DataFrame) -> pd.DataFrame:
    """Contagem por genreId, com sinais de ruído (apps achados por um único termo)."""
    def mode_or_empty(s: pd.Series) -> str:
        m = s.mode()
        return str(m.iat[0]) if not m.empty else ""

    table = apps.groupby("genreId").agg(
        genre=("genre", mode_or_empty),
        n_apps=("appId", "size"),
        mean_n_terms=("n_terms", "mean"),
        share_single_term=("n_terms", lambda s: float((s == 1).mean())),
        mean_n_groups=("n_groups", "mean"),
    )
    table["share"] = table["n_apps"] / table["n_apps"].sum()
    return table.sort_values("n_apps", ascending=False).reset_index()


# --- Saturação ----------------------------------------------------------------------
def _cumulative_unique(app_codes: np.ndarray, term_rank: np.ndarray, n_apps: int, n_terms: int) -> np.ndarray:
    """Apps únicos acumulados após k termos, dado o posto (ordem) de cada termo."""
    first = np.full(n_apps, n_terms, dtype=np.int64)
    np.minimum.at(first, app_codes, term_rank)
    counts = np.bincount(first[first < n_terms], minlength=n_terms)
    return np.cumsum(counts)


def saturation(pairs: pd.DataFrame, n_perm: int = 200, seed: int = 42) -> tuple[pd.DataFrame, dict]:
    """Curva de acumulação de apps únicos por número de termos.

    Devolve a curva na ordem da coleta e a média/faixa de 90% sobre permutações aleatórias da
    ordem dos termos, mais o ganho do último 10% dos termos (fração dos apps achada só neles).
    """
    data = pairs[["term", "appId", "collect_time"]].drop_duplicates(["term", "appId"])
    term_codes, terms = pd.factorize(data["term"])
    app_codes, app_ids = pd.factorize(data["appId"])
    n_terms, n_apps = len(terms), len(app_ids)

    first_time = data.groupby("term")["collect_time"].min().sort_values(kind="stable")
    rank_by_term = pd.Series(np.arange(n_terms), index=first_time.index)
    collection_rank = rank_by_term.reindex(terms).to_numpy()
    collection_curve = _cumulative_unique(app_codes, collection_rank[term_codes], n_apps, n_terms)

    rng = np.random.default_rng(seed)
    curves = np.empty((n_perm, n_terms))
    for i in range(n_perm):
        term_rank = rng.permutation(n_terms)  # term_rank[j] = posição do termo j nesta permutação
        curves[i] = _cumulative_unique(app_codes, term_rank[term_codes], n_apps, n_terms)

    curve = pd.DataFrame({
        "n_terms": np.arange(1, n_terms + 1),
        "collection_order": collection_curve,
        "mean": curves.mean(axis=0),
        "p05": np.percentile(curves, 5, axis=0),
        "p95": np.percentile(curves, 95, axis=0),
    })

    cut = max(1, math.ceil(0.9 * n_terms))  # k termos = 90% dos termos
    if cut >= n_terms:
        tail = np.zeros(n_perm)
        tail_collection = 0.0
    else:
        tail = (curves[:, -1] - curves[:, cut - 1]) / curves[:, -1]
        tail_collection = float((collection_curve[-1] - collection_curve[cut - 1]) / collection_curve[-1])
    stats = {
        "n_terms": int(n_terms),
        "n_apps": int(n_apps),
        "n_permutations": int(n_perm),
        "tail_gain_mean": float(tail.mean()),
        "tail_gain_p05": float(np.percentile(tail, 5)),
        "tail_gain_p95": float(np.percentile(tail, 95)),
        "tail_gain_collection_order": tail_collection,
    }
    return curve, stats


# --- Amostra estratificada para rotulagem manual ------------------------------------------
def add_strata(apps: pd.DataFrame, top_genres: int = 10) -> pd.DataFrame:
    """Acrescenta genre_top, n_terms_band, rank_band e stratum (a combinação das três)."""
    out = apps.copy()
    top = out["genreId"].value_counts().head(top_genres).index
    out["genre_top"] = np.where(out["genreId"].isin(top), out["genreId"], "OTHER")
    out["n_terms_band"] = pd.cut(out["n_terms"], [0, 1, 3, np.inf], labels=N_TERMS_LABELS).astype(str)
    out["rank_band"] = pd.cut(
        out["best_rank"].fillna(999), [0, 10, 30, np.inf], labels=RANK_LABELS
    ).astype(str)
    out["stratum"] = out["genre_top"] + "|" + out["n_terms_band"] + "|" + out["rank_band"]
    return out


def allocate(sizes: pd.Series, n: int, min_per_stratum: int) -> pd.Series:
    """Quantos sortear em cada estrato: mínimo garantido + restante proporcional (maior resto)."""
    base = sizes.clip(upper=min_per_stratum)
    rest = n - int(base.sum())
    if rest < 0:
        raise ValueError(
            f"n={n} é pequeno demais para o mínimo de {min_per_stratum} por estrato "
            f"({len(sizes)} estratos, mínimo total {int(base.sum())}). Aumente --n ou reduza --min-per-stratum."
        )
    room = sizes - base
    rest = min(rest, int(room.sum()))
    alloc = base.copy()
    if rest > 0:
        share = room / room.sum() * rest
        extra = np.floor(share).astype(int)
        leftover = rest - int(extra.sum())
        for stratum in (share - extra).sort_values(ascending=False, kind="stable").index[:leftover]:
            extra[stratum] += 1
        alloc = alloc + extra
    return alloc.astype(int)


def draw_sample(apps: pd.DataFrame, n: int, min_per_stratum: int, top_genres: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sorteia a amostra e devolve (amostra embaralhada, tabela de alocação por estrato)."""
    data = add_strata(apps, top_genres).sort_values("appId").reset_index(drop=True)
    sizes = data.groupby("stratum").size()
    alloc = allocate(sizes, n, min_per_stratum)

    rng = np.random.default_rng(seed)
    picked: list[int] = []
    for stratum in sorted(alloc.index):
        k = int(alloc[stratum])
        if k > 0:
            members = data.index[data["stratum"] == stratum].to_numpy()
            picked.extend(rng.choice(members, size=k, replace=False).tolist())

    sample = data.loc[picked].copy()
    sample["stratum_size"] = sample["stratum"].map(sizes).astype(int)
    sample["sampled_n"] = sample["stratum"].map(alloc).astype(int)
    sample["url"] = "https://play.google.com/store/apps/details?id=" + sample["appId"] + "&hl=pt_BR&gl=BR"
    sample["description_snippet"] = (
        sample["description"].fillna("").str.replace(r"\s+", " ", regex=True).str.slice(0, 400)
    )
    sample = sample.sample(frac=1, random_state=seed).reset_index(drop=True)  # ordem de rotulagem embaralhada
    sample.insert(0, "sample_id", np.arange(1, len(sample) + 1))
    for column in ("label", "reason", "label2"):
        sample[column] = ""

    columns = [
        "sample_id", "appId", "title", "genreId", "genre_top", "n_terms", "n_terms_band", "best_rank",
        "rank_band", "groups", "installs", "stratum", "stratum_size", "sampled_n", "url",
        "description_snippet", "label", "reason", "label2",
    ]
    allocation = pd.DataFrame({"stratum_size": sizes, "sampled": alloc}).reset_index()
    return sample[columns], allocation


# --- Estatísticas dos rótulos --------------------------------------------------------------
def normalize_labels(series: pd.Series) -> pd.Series:
    """Padroniza (minúsculas, sem espaços), transforma vazio em NaN e valida os valores."""
    cleaned = series.fillna("").astype(str).str.strip().str.lower().replace({"": np.nan})
    invalid = sorted(set(cleaned.dropna()) - VALID_LABELS)
    if invalid:
        raise ValueError(f"Rótulos inválidos: {invalid}. Valores aceitos: {sorted(VALID_LABELS)}")
    return cleaned


def _stratified_rate(per_stratum: pd.DataFrame) -> dict:
    """Taxa de ruído estimada (estimador estratificado, com correção de população finita)."""
    total = per_stratum["N"].sum()
    weight = per_stratum["N"] / total
    p = per_stratum["k"] / per_stratum["n"]
    rate = float((weight * p).sum())
    variance = float((weight**2 * p * (1 - p) / per_stratum["n"] * (1 - per_stratum["n"] / per_stratum["N"])).sum())
    half = 1.96 * math.sqrt(variance)
    return {
        "noise_rate": rate,
        "ci_low": max(0.0, rate - half),
        "ci_high": min(1.0, rate + half),
        "n_labeled": int(per_stratum["n"].sum()),
        "population": int(total),
        "strata": int(len(per_stratum)),
        "strata_with_n_lt_2": int((per_stratum["n"] < 2).sum()),
    }


def cohen_kappa(a: pd.Series, b: pd.Series) -> dict:
    """Concordância entre dois avaliadores (kappa de Cohen) nas linhas rotuladas por ambos."""
    both = pd.DataFrame({"a": a, "b": b}).dropna()
    n = len(both)
    if n == 0:
        return {"n": 0, "agreement": float("nan"), "kappa": float("nan")}
    observed = float((both["a"] == both["b"]).mean())
    expected = sum(
        float((both["a"] == cat).mean() * (both["b"] == cat).mean()) for cat in set(both["a"]) | set(both["b"])
    )
    kappa = (observed - expected) / (1 - expected) if expected < 1 else float("nan")
    return {"n": int(n), "agreement": observed, "kappa": float(kappa)}


def label_stats(sample: pd.DataFrame, by: str) -> dict:
    """Taxa de ruído geral e por dimensão (genre_top, n_terms_band, rank_band) + kappa se houver label2."""
    if by not in BY_COLUMNS:
        raise ValueError(f"--by deve ser um de {BY_COLUMNS}")
    df = sample.copy()
    df["label"] = normalize_labels(df["label"])
    has_second = "label2" in df.columns and df["label2"].fillna("").astype(str).str.strip().ne("").any()
    if has_second:
        df["label2"] = normalize_labels(df["label2"])

    decided = df[df["label"].isin([LABEL_RELEVANT, LABEL_NOISE])].copy()
    if decided.empty:
        raise ValueError("Nenhuma linha com rótulo 'relevante' ou 'nao_relevante'.")
    decided["is_noise"] = (decided["label"] == LABEL_NOISE).astype(int)

    per = decided.groupby("stratum").agg(
        n=("is_noise", "size"),
        k=("is_noise", "sum"),
        N=("stratum_size", "first"),
        value=(by, "first"),
    )
    overall = _stratified_rate(per)
    overall["est_noisy_apps"] = round(overall["noise_rate"] * overall["population"])

    rows = []
    for value, sub in per.groupby("value"):
        rows.append({by: value, **_stratified_rate(sub)})
    by_table = pd.DataFrame(rows).sort_values("noise_rate", ascending=False).reset_index(drop=True)

    counts = {
        "rows": int(len(df)),
        "unlabeled": int(df["label"].isna().sum()),
        "relevant": int((df["label"] == LABEL_RELEVANT).sum()),
        "noise": int((df["label"] == LABEL_NOISE).sum()),
        "unsure": int((df["label"] == LABEL_UNSURE).sum()),
    }
    result = {"overall": overall, "by": by_table, "counts": counts}
    if has_second:
        result["kappa"] = cohen_kappa(df["label"], df["label2"])
    return result
