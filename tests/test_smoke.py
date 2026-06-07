"""Smoke-тесты. Расширять по мере реализации модулей."""

def test_import():
    import tabula
    import tabula.config
    import tabula.models
    assert tabula.__version__
