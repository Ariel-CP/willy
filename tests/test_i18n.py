import app.i18n as i18n


def test_set_language_ignores_unknown_language() -> None:
    i18n.set_language("es")
    before = i18n.get("settings_title")

    i18n.set_language("xx")
    after = i18n.get("settings_title")

    assert before == after == "Configuración"


def test_get_returns_key_when_missing() -> None:
    i18n.set_language("en")
    assert i18n.get("missing_key_for_test") == "missing_key_for_test"


def test_get_formats_kwargs() -> None:
    i18n.set_language("en")
    text = i18n.get("settings_api_hint_env", env_name="OPENAI_API_KEY", status="ok")

    assert "OPENAI_API_KEY" in text
    assert "ok" in text
