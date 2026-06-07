"""CLI (Typer). SPEC 9."""
from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(
    help="Tabula Rasa — персональная когнитивная память",
    no_args_is_help=True,
)


@app.command()
def add(
    text: str = typer.Argument(..., help="Текст для записи в память"),
    namespace: str = typer.Option("personal", "--ns", help="Namespace"),
    session: Optional[str] = typer.Option(None, "--session", help="session_id"),
):
    """Записать текст в память (ingest → факты → граф)."""
    from tabula.ingest import ingest_turn
    from tabula.models import RawTurn

    turn = RawTurn(text=text, namespace=namespace)
    if session:
        turn.session_id = session

    typer.echo(f"⏳ Записываю в namespace={namespace}...")
    ingest_turn(turn)
    typer.echo("✅ Записано.")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Вопрос к памяти"),
    namespace: str = typer.Option("personal", "--ns"),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="ISO дата для temporal"),
    mode: str = typer.Option("activation", "--mode", help="fts5 | activation"),
):
    """Спросить память."""
    from tabula.retrieval import query

    typer.echo(f"🔍 [{mode}] {question}")
    result = query(question, namespace=namespace, as_of=as_of, mode=mode)

    if result.abstained:
        typer.echo("🤷 Информации об этом нет.")
    else:
        typer.echo(f"\n💬 {result.answer}")
        typer.echo(f"\n📊 confidence={result.confidence:.2f}  "
                   f"nodes={len(result.activated_nodes)}  sources={len(result.sources)}")


@app.command()
def sync(namespace: str = typer.Option("personal", "--ns")):
    """Пересобрать граф + markdown wiki из SQLite."""
    from tabula.graph import load_graph
    from tabula.projection import rebuild_wiki
    G = load_graph(namespace)
    typer.echo(f"🔗 Граф: {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер.")
    rebuild_wiki(namespace)
    typer.echo("✅ Sync завершён — wiki обновлена.")


@app.command()
def status(namespace: str = typer.Option("personal", "--ns")):
    """Показать статус памяти: концепты, факты, граф."""
    from tabula.graph import load_graph
    from tabula.store import collect_facts, get_all_concepts

    concepts = get_all_concepts(namespace)
    facts = collect_facts([c["name"] for c in concepts], namespace)
    G = load_graph(namespace)

    typer.echo(f"\n📦 Namespace: {namespace}")
    typer.echo(f"  Концептов : {len(concepts)}")
    typer.echo(f"  Фактов    : {len(facts)}")
    typer.echo(f"  Граф      : {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер")

    if concepts:
        typer.echo("\n  Топ концептов:")
        for c in concepts[:10]:
            typer.echo(f"    · {c['name']}")


@app.command("connect")
def connect_command(
    client: str = typer.Argument(
        ...,
        help="cursor | claude | codex | all",
    ),
    global_cursor: bool = typer.Option(
        False, "--global", help="Cursor: писать в ~/.cursor/mcp.json вместо проекта",
    ),
):
    """Подключить MCP-сервер к Cursor / Claude Code / Codex."""
    from tabula.connect import connect, connect_all, restart_hint

    client = client.lower().strip()
    if client == "all":
        paths = connect_all(global_cursor=global_cursor)
        typer.echo("✅ MCP tabula-rasa подключён:\n")
        for name, path in paths.items():
            typer.echo(f"  · {name}: {path}")
            typer.echo(f"    → {restart_hint(name)}")  # type: ignore[arg-type]
        return

    if client not in ("cursor", "claude", "codex"):
        typer.echo(f"❌ Неизвестный клиент: {client}. Используй: cursor, claude, codex, all")
        raise typer.Exit(code=1)

    path = connect(client, global_cursor=global_cursor)  # type: ignore[arg-type]
    typer.echo(f"✅ MCP записан: {path}")
    typer.echo(f"→ {restart_hint(client)}")  # type: ignore[arg-type]


@app.command()
def doctor(
    skip_embed: bool = typer.Option(False, "--skip-embed", help="Не грузить embed-модель (~470MB)"),
):
    """Проверить установку перед connect."""
    from tabula.doctor import format_report, run_doctor

    report = run_doctor(skip_embed=skip_embed)
    typer.echo(format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def bench(
    dataset: str = typer.Option("longmemeval-s", "--dataset", help="longmemeval-s | locomo"),
    mode: str = typer.Option("activation", "--mode", help="fts5 | activation"),
    judge: str = typer.Option("claude", "--judge", help="claude | gpt-4o"),
    sample: Optional[int] = typer.Option(None, "--sample", help="Число вопросов (50 для dev)"),
    compare: Optional[str] = typer.Option(None, "--compare",
                                           help="Сравнить режимы: fts5,activation"),
    dataset_path: Optional[str] = typer.Option(None, "--path", help="Путь к файлу датасета"),
):
    """Прогнать бенчмарк или сравнить режимы."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from bench.runner import run, compare as do_compare

    if compare:
        modes = [m.strip() for m in compare.split(",")]
        do_compare(dataset=dataset, dataset_path=dataset_path,
                   modes=modes, sample=sample)
    else:
        run(dataset=dataset, dataset_path=dataset_path,
            mode=mode, judge_name=judge, sample=sample)


if __name__ == "__main__":
    app()
