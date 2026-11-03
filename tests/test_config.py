from application_crew.config import DEFAULT_CONFIG_PATH, load_settings


def test_step_overrides_inherit_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = load_settings(DEFAULT_CONFIG_PATH)

    assert settings.data_dir == tmp_path
    author = settings.llm_for("author")
    assert author.model == settings.llm_default.model
    assert author.effort == "high"
    assert author.max_tokens == 32000
    assert settings.llm_for("unknown_step") == settings.llm_default
    assert settings.review.max_iterations == 4
