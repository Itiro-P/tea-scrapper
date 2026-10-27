"""CLI (Click): uma etapa da análise por subcomando. A lógica fica em group.py e metrics.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd

from . import metrics
from .group import GROUPED_DIRNAME, unite_groups
from .loader import load_grouped

CSV_ENCODING = "utf-8-sig"  # o Excel abre acentos corretamente


def _write_meta(obj: dict, name: str, params: dict, extra: dict | None = None) -> None:
    """Metadados da execução, gravados ao lado da saída (reprodutibilidade)."""
    meta = {
        "command": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": obj["seed"],
        "results_dir": str(obj["results"]),
        "params": params,
        **(extra or {}),
    }
    (obj["out"] / f"{name}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load(obj: dict):
    try:
        return load_grouped(obj["results"] / GROUPED_DIRNAME)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def _save_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding=CSV_ENCODING)


@click.group()
@click.option(
    "--results", "results_dir", default="results", show_default=True,
    type=click.Path(file_okay=False, path_type=Path), help="Pasta com os JSON da coleta (um por termo).",
)
@click.option(
    "--out", "out_dir", default="analysis", show_default=True,
    type=click.Path(file_okay=False, path_type=Path), help="Pasta das saídas da análise.",
)
@click.option("--seed", default=42, type=int, show_default=True, help="Semente de toda aleatoriedade.")
@click.pass_context
def cli(ctx: click.Context, results_dir: Path, out_dir: Path, seed: int) -> None:
    """Análise da coleta de apps: funil, saturação e amostra para rotulagem."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.obj = {"results": results_dir, "out": out_dir, "seed": seed}


@cli.command("group")
@click.pass_obj
def group_cmd(obj: dict) -> None:
    """Une os JSON por termo (RESULTS) em um JSON por grupo, em RESULTS/grouped."""
    if not obj["results"].is_dir():
        raise click.ClickException(f"{obj['results']} não existe.")
    try:
        summary = unite_groups(obj["results"])
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    for line in summary.files_ignored:
        click.echo(f"Ignorado: {line}", err=True)
    click.echo(
        f"Arquivos lidos: {summary.files_read} | ignorados: {len(summary.files_ignored)} | "
        f"grupos: {summary.groups} | pares (grupo, app): {summary.pairs} | apps únicos: {summary.unique_apps}"
    )
    _write_meta(obj, "group", {}, {"files_ignored": summary.files_ignored, "unique_apps": summary.unique_apps})


@cli.command("export")
@click.pass_obj
def export_cmd(obj: dict) -> None:
    """Exporta a tabela de pares (pairs.csv) e a de apps (apps.csv, sem a descrição) para explorar à parte."""
    pairs, apps, _ = _load(obj)
    _save_csv(pairs, obj["out"] / "pairs.csv")
    _save_csv(apps.drop(columns=["description"]), obj["out"] / "apps.csv")
    click.echo(f"{len(pairs)} pares e {len(apps)} apps em {obj['out']}")
    _write_meta(obj, "export", {}, {"pairs": len(pairs), "apps": len(apps)})


@cli.command()
@click.pass_obj
def funnel(obj: dict) -> None:
    """Funil da amostra: resultados brutos, pares com detalhes, apps únicos e por grupo."""
    pairs, apps, terms_summary = _load(obj)
    result, per_group = metrics.funnel(pairs, apps, terms_summary)
    labels = {
        "terms_searched": "termos pesquisados",
        "results_returned": "resultados devolvidos pelas buscas",
        "details_failed": "  sem detalhes (falha em app())",
        "pairs_with_details": "pares (termo, app) com detalhes",
        "unique_apps": "apps únicos",
        "mean_appearances_per_app": "aparições por app (média)",
        "apps_in_multiple_groups": "apps em mais de um grupo",
        "apps_with_single_term": "apps achados por um único termo",
    }
    for key, label in labels.items():
        if key in result:
            click.echo(f"{label}: {result[key]}")
    click.echo("\n" + per_group.to_string(index=False))
    (obj["out"] / "funnel.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _save_csv(per_group, obj["out"] / "funnel_by_group.csv")
    _write_meta(obj, "funnel", {})


@cli.command("terms-per-app")
@click.pass_obj
def terms_per_app_cmd(obj: dict) -> None:
    """Distribuição do número de termos que encontraram cada app."""
    _, apps, _ = _load(obj)
    dist = metrics.terms_per_app(apps)
    click.echo(dist.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    _save_csv(dist, obj["out"] / "terms_per_app.csv")
    _write_meta(obj, "terms-per-app", {})


@cli.command()
@click.option("--top", default=25, show_default=True, type=int, help="Quantos gêneros mostrar no terminal.")
@click.pass_obj
def genres(obj: dict, top: int) -> None:
    """Tabela por genreId (apps, termos por app, fração achada por um único termo)."""
    _, apps, _ = _load(obj)
    table = metrics.genre_table(apps)
    click.echo(table.head(top).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    _save_csv(table, obj["out"] / "genres.csv")
    _write_meta(obj, "genres", {"top": top})


@cli.command()
@click.option("--perms", default=200, show_default=True, type=int, help="Permutações aleatórias da ordem dos termos.")
@click.pass_obj
def saturation(obj: dict, perms: int) -> None:
    """Curva de acumulação de apps únicos por termo (ordem da coleta e permutações)."""
    if perms < 1:
        raise click.BadParameter("deve ser pelo menos 1", param_hint="--perms")
    pairs, _, _ = _load(obj)
    curve, stats = metrics.saturation(pairs, n_perm=perms, seed=obj["seed"])
    _save_csv(curve, obj["out"] / "saturation.csv")
    click.echo(f"termos: {stats['n_terms']} | apps únicos: {stats['n_apps']} | permutações: {stats['n_permutations']}")
    click.echo(
        "Fração dos apps achada só nos últimos 10% dos termos: "
        f"{stats['tail_gain_mean']:.1%} (faixa de 90%: {stats['tail_gain_p05']:.1%} a {stats['tail_gain_p95']:.1%}); "
        f"na ordem da coleta: {stats['tail_gain_collection_order']:.1%}"
    )
    _write_meta(obj, "saturation", {"perms": perms}, {"stats": stats})


@cli.command()
@click.option("--n", "n_sample", default=300, show_default=True, type=int, help="Tamanho da amostra.")
@click.option("--min-per-stratum", default=3, show_default=True, type=int, help="Mínimo de apps por estrato.")
@click.option("--top-genres", default=10, show_default=True, type=int, help="Gêneros mantidos; o resto vira OTHER.")
@click.pass_obj
def sample(obj: dict, n_sample: int, min_per_stratum: int, top_genres: int) -> None:
    """Sorteia a amostra estratificada para rotulagem manual (gênero x termos por app x posição)."""
    _, apps, _ = _load(obj)
    try:
        sample_df, allocation = metrics.draw_sample(apps, n_sample, min_per_stratum, top_genres, obj["seed"])
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _save_csv(sample_df, obj["out"] / "sample_for_labeling.csv")
    _save_csv(allocation, obj["out"] / "sample_strata.csv")
    click.echo(f"{len(sample_df)} apps em {allocation.shape[0]} estratos -> {obj['out'] / 'sample_for_labeling.csv'}")
    click.echo(f"Preencha 'label' com: {', '.join(sorted(metrics.VALID_LABELS))}")
    _write_meta(obj, "sample", {"n": n_sample, "min_per_stratum": min_per_stratum, "top_genres": top_genres})


@cli.command("label-stats")
@click.argument("labeled_csv", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--by", type=click.Choice(metrics.BY_COLUMNS), default="genre_top", show_default=True,
              help="Dimensão do detalhamento.")
@click.pass_obj
def label_stats_cmd(obj: dict, labeled_csv: Path, by: str) -> None:
    """Taxa de ruído (estimativa estratificada com IC de 95%) a partir da amostra rotulada."""
    sample_df = pd.read_csv(labeled_csv, encoding=CSV_ENCODING, dtype=str, keep_default_na=False)
    sample_df["stratum_size"] = pd.to_numeric(sample_df["stratum_size"])
    try:
        result = metrics.label_stats(sample_df, by)
    except (ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc

    c, o = result["counts"], result["overall"]
    click.echo(
        f"linhas: {c['rows']} | sem rótulo: {c['unlabeled']} | relevantes: {c['relevant']} | "
        f"ruído: {c['noise']} | incertos: {c['unsure']}"
    )
    click.echo(
        f"ruído estimado na população: {o['noise_rate']:.1%} (IC 95%: {o['ci_low']:.1%} a {o['ci_high']:.1%}), "
        f"~{o['est_noisy_apps']} de {o['population']} apps"
    )
    if o["strata_with_n_lt_2"]:
        click.echo(f"Atenção: {o['strata_with_n_lt_2']} estrato(s) com menos de 2 apps rotulados; o IC é otimista.", err=True)
    click.echo("\n" + result["by"].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    if "kappa" in result:
        k = result["kappa"]
        click.echo(f"\nconcordância entre avaliadores (n={k['n']}): {k['agreement']:.1%} | kappa = {k['kappa']:.3f}")

    _save_csv(result["by"], obj["out"] / f"label_stats_by_{by}.csv")
    summary = {"counts": c, "overall": o, **({"kappa": result["kappa"]} if "kappa" in result else {})}
    (obj["out"] / "label_stats.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_meta(obj, "label-stats", {"labeled_csv": str(labeled_csv), "by": by})


if __name__ == "__main__":
    cli()
