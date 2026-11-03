import pytest

from application_crew.render.typst import pdf_to_text, render, typst_available

pytestmark = pytest.mark.skipif(not typst_available(), reason="typst not installed")


def test_smoke_template_renders_and_text_is_extractable(tmp_path):
    out = tmp_path / "smoke.pdf"
    result = render(
        "smoke", {"title": "Hello & Co. #1", "body": "Größe 100% _ok_", "lang": "de"}, out
    )
    assert result.ok, result.error
    text = pdf_to_text(out)
    assert "Hello & Co. #1" in text
    assert "Größe 100%" in text
