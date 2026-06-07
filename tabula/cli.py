"""CLI (Typer). SPEC 9."""
from __future__ import annotations

import typer

app = typer.Typer(help="Tabula Rasa — персональная когнитивная память")


@app.command()
def add(text: str, namespace: str = "personal"):
    """Записать в память."""
    raise NotImplementedError


@app.command()
def ask(question: str, namespace: str = "personal",
        as_of: str = typer.Option(None), mode: str = "activation"):
    """Спросить память."""
    raise NotImplementedError


@app.command()
def sync(namespace: str = "personal"):
    """Пересобрать граф + wiki из SQLite."""
    raise NotImplementedError


@app.command()
def status(namespace: str = "personal"):
    """Концепты, факты, размер графа."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
