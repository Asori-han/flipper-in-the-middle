"""Load localized text used in generated figures and animations."""

from functools import lru_cache
import json
from pathlib import Path


DEFAULT_LABELS = Path(__file__).resolve().parents[2] / "docs" / "plot-labels.es.json"


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def plot_label(key: str, *, labels_path: Path = DEFAULT_LABELS, **values) -> str:
    """Return one formatted plot label selected by its dotted key."""
    selected = _load(str(labels_path.resolve()))
    for component in key.split("."):
        selected = selected[component]
    if not isinstance(selected, str):
        raise TypeError(f"plot label {key!r} is not a string")
    return selected.format(**values)
