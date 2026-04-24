import importlib

import pytest


@pytest.mark.asyncio
async def test_settings_loads_dotenv_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "THINGS_EMAIL=dotenv@example.com\nTHINGS_PASSWORD=dotenv-pass\nAPI_KEY=" + "a" * 32 + "\n"
    )

    import things_api.config as config_mod
    importlib.reload(config_mod)

    s = config_mod.Settings()
    assert s.things_email == "dotenv@example.com"
    assert s.things_password == "dotenv-pass"


def test_validate_api_key_rejects_short_next_key():
    from things_api.config import Settings

    s = Settings(api_key="a" * 32, api_key_next="short")
    with pytest.raises(ValueError, match="API_KEY_NEXT must be at least 32 characters"):
        s.validate_api_key()
