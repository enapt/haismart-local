"""`scripts/check-translations.py` catches English that moved under its translations (item 69).

Checked against known answers in a copy of the component, so the real files are never touched.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

# The suite's autouse fixtures patch modules of the integration, so it must be importable.
import custom_components.haismart.coordinator  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
COMPONENT = REPO / "packages/ha-haismart/custom_components/haismart"
KEY = ("config", "step", "user", "menu_options", "login")


@pytest.fixture
def checker(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_translations",
                                                  REPO / "scripts/check-translations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    component = tmp_path / "haismart"
    shutil.copytree(COMPONENT / "translations", component / "translations")
    shutil.copy(COMPONENT / "strings.json", component / "strings.json")
    monkeypatch.setattr(module, "COMPONENT", component)
    monkeypatch.setattr(module, "SOURCES", tmp_path / "translation-sources.json")
    module.record(module.flatten(json.loads((component / "strings.json").read_text("utf-8"))))
    return module, component


def _edit(path: Path, value: str) -> None:
    data = json.loads(path.read_text("utf-8"))
    node = data
    for part in KEY[:-1]:
        node = node[part]
    node[KEY[-1]] = value
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _problems(module, component) -> list[str]:
    reference = module.flatten(json.loads((component / "strings.json").read_text("utf-8")))
    return module.check_values(reference)


def test_the_shipped_translations_match_their_record() -> None:
    spec = importlib.util.spec_from_file_location("check_translations",
                                                  REPO / "scripts/check-translations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reference = module.flatten(json.loads((COMPONENT / "strings.json").read_text("utf-8")))
    assert module.check_values(reference) == []


def test_reworded_english_names_every_language_still_on_the_old_text(checker) -> None:
    module, component = checker
    assert _problems(module, component) == []
    _edit(component / "strings.json", "Sign in with a Haier account")
    [problem] = _problems(module, component)
    assert "30 language(s)" in problem and "zh-Hans" in problem

    _edit(component / "translations" / "de.json", "Mit einem Haier-Konto anmelden")
    [problem] = _problems(module, component)
    assert "29 language(s)" in problem and "de," not in problem and " de" not in problem


def test_every_language_updated_still_asks_for_a_new_record(checker) -> None:
    """Otherwise the NEXT English change would be compared against the wrong translations."""
    module, component = checker
    _edit(component / "strings.json", "Sign in with a Haier account")
    for path in (component / "translations").glob("*.json"):
        _edit(path, f"translated again: {path.stem}")
    [problem] = _problems(module, component)
    assert "every language changed" in problem
