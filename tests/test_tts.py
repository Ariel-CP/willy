from unittest.mock import patch

from app.tts import TTSEngine


def _common_shutil_which_windows(name: str) -> str | None:
    if name in {"powershell", "pwsh"}:
        return "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    return None


def _common_shutil_which_linux(name: str) -> str | None:
    mapping = {
        "pw-play": "/usr/bin/pw-play",
        "espeak": "/usr/bin/espeak",
    }
    return mapping.get(name)


def test_tts_windows_auto_prefers_sapi_when_available() -> None:
    with patch("app.tts.platform.system", return_value="Windows"), patch(
        "app.tts.shutil.which", side_effect=_common_shutil_which_windows
    ):
        tts = TTSEngine(lang="es", config={"tts_engine": "auto"})
        assert tts.is_available() is True
        assert tts._resolve_engine() == "sapi"


def test_tts_windows_respects_sapi_preference() -> None:
    with patch("app.tts.platform.system", return_value="Windows"), patch(
        "app.tts.shutil.which", side_effect=_common_shutil_which_windows
    ):
        tts = TTSEngine(lang="es", config={"tts_engine": "sapi"})
        assert tts._resolve_engine() == "sapi"


def test_tts_linux_auto_prefers_espeak_without_piper() -> None:
    with patch("app.tts.platform.system", return_value="Linux"), patch(
        "app.tts.shutil.which", side_effect=_common_shutil_which_linux
    ), patch("app.tts.os.path.isfile", return_value=False):
        tts = TTSEngine(lang="es", config={"tts_engine": "auto", "piper_model": ""})
        assert tts.is_available() is True
        assert tts._resolve_engine() == "espeak"
