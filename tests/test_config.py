from application_crew.config import DEFAULT_CONFIG_PATH, load_settings


def test_step_overrides_inherit_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = load_settings(DEFAULT_CONFIG_PATH)

    assert settings.data_dir == tmp_path
    author = settings.llm_for("author_cv")
    assert author.model == settings.llm_default.model
    assert author.effort == "medium"
    assert settings.llm_for("parse_listing").model == "claude-haiku-5-5"
    assert settings.llm_for("recruiter").model == "claude-sonnet-5-5"
    assert settings.llm_for("claims_check").model == "claude-opus-5-5"
    assert author.max_tokens == settings.llm_default.max_tokens == 16000
    assert settings.llm_for("unknown_step") == settings.llm_default
    assert settings.review.max_iterations == 4
