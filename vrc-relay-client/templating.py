from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _current_theme() -> str:
    from db.models import get_config
    from state import CONFIG_KEY_THEME

    return get_config(CONFIG_KEY_THEME, "system") or "system"


templates.env.globals["current_theme"] = _current_theme
