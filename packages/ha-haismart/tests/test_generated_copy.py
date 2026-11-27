"""The installed copy keeps its two helper libraries to itself.

Every install a user makes — the Marketplace, HACS, the manual copy — is the GENERATED tree at the
repository root (`custom_components/haismart/`, written by `scripts/build-hacs.sh`), with
`haismart_hrdp` and `haismart_extractor` bundled under `vendor/`. The rest of this suite imports the
`packages/` copy, so these tests are the ones that look at what is shipped.

The property: the bundled libraries are reached as `custom_components.haismart.vendor.*` and never
as top-level modules, and nothing is added to `sys.path`. A top-level `haismart_hrdp` would be
shared with the whole Home Assistant process — another copy installed there would shadow ours, and
ours would shadow it.

Each test names the build change that would make it fail.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATED = REPO_ROOT / "custom_components" / "haismart"
LIBS = ("haismart_hrdp", "haismart_extractor")


def _generated_python_files() -> list[Path]:
    files = sorted(p for p in GENERATED.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"no generated copy at {GENERATED} - run scripts/build-hacs.sh"
    return files


def test_no_file_in_the_generated_copy_imports_a_library_by_its_top_level_name():
    """Fails if the build stops rewriting `from haismart_hrdp ...` in the integration's modules, or
    if a library grows an absolute import of itself (it works from `packages/` and breaks once
    bundled). Read from the syntax tree, so an import inside a function counts and one quoted in a
    docstring does not."""
    found = []
    for path in _generated_python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in LIBS:
                    found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}")
    assert not found, "absolute imports of a bundled library:\n" + "\n".join(found)


def test_the_generated_copy_does_not_touch_sys_path():
    """Fails if the build puts a `sys.path` shim back into the integration's modules."""
    found = []
    for path in _generated_python_files():
        if "vendor" in path.relative_to(GENERATED).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "path"
                and isinstance(node.value, ast.Name)
                and node.value.id in ("sys", "_sys")
            ):
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not found, "sys.path is used in the integration's own modules:\n" + "\n".join(found)


# Run in a fresh interpreter: this suite's own process has the `packages/` copies of both libraries
# on its path. The child gets no PYTHONPATH, and the finder below refuses any top-level import of
# the two libraries however they could be found, so the generated copy must stand on its own. (Not
# `-I`: that also drops the user site, where some machines keep Home Assistant's own dependencies.)
_PROBE = textwrap.dedent(
    """
    import ast, importlib, importlib.abc, json, pkgutil, sys
    from pathlib import Path

    root, libs = sys.argv[1], tuple(sys.argv[2].split(","))

    class RefuseTopLevel(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in libs:
                raise ImportError(f"top-level import of {name}")
            return None

    sys.meta_path.insert(0, RefuseTopLevel())
    sys.path.insert(0, root)
    path_before = list(sys.path)

    import custom_components.haismart as pkg

    modules = sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name != "vendor")
    for name in modules:
        importlib.import_module(f"custom_components.haismart.{name}")

    # Every `from . import ...` / `from .x import ...` in the integration's modules, including the
    # ones inside functions that importing alone never runs, must name something that exists.
    unresolved = []
    for name in modules:
        path = Path(pkg.__path__[0]) / f"{name}.py"
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.level):
                continue
            base = "custom_components.haismart" + (f".{node.module}" if node.module else "")
            try:
                target = importlib.import_module(base)
            except ImportError as err:
                unresolved.append(f"{name}.py:{node.lineno}: {base} ({err})")
                continue
            for alias in node.names:
                if alias.name == "*" or hasattr(target, alias.name):
                    continue
                try:
                    importlib.import_module(f"{base}.{alias.name}")
                except ImportError:
                    unresolved.append(f"{name}.py:{node.lineno}: {base}.{alias.name}")

    print(json.dumps({
        "package_dir": str(Path(pkg.__path__[0]).resolve()),
        "modules": modules,
        "top_level": sorted(n for n in sys.modules if n.split(".")[0] in libs),
        "vendored": sorted(
            n for n in sys.modules if n.startswith("custom_components.haismart.vendor.")
        ),
        "path_added": [p for p in sys.path if p not in path_before],
        "unresolved": unresolved,
    }))
    """
)


@pytest.fixture(scope="module")
def probe() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT), ",".join(LIBS)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, (
        "importing the generated copy with no top-level haismart_hrdp / haismart_extractor "
        f"failed:\n{result.stderr[-3000:]}"
    )
    found = json.loads(result.stdout.strip().splitlines()[-1])
    # The probe is about the shipped tree, so it must have loaded that one, not the source copy.
    assert found["package_dir"] == str(GENERATED.resolve())
    return found


def test_every_module_of_the_generated_copy_imports_without_a_top_level_library(probe):
    """Fails if any module still reaches a library by its top-level name (the probe refuses it), or
    if the build stops producing a module the source has."""
    source = sorted(
        p.stem
        for p in (REPO_ROOT / "packages/ha-haismart/custom_components/haismart").glob("*.py")
        if p.stem != "__init__"
    )
    assert [m for m in source if m not in probe["modules"]] == []
    assert probe["top_level"] == []


def test_the_bundled_libraries_load_under_the_integration(probe):
    """Fails if the integration stops reaching the bundled copies at all (for instance if an import
    were rewritten to something that happens to resolve elsewhere)."""
    assert "custom_components.haismart.vendor.haismart_hrdp" in probe["vendored"]
    assert "custom_components.haismart.vendor.haismart_extractor" in probe["vendored"]


def test_importing_the_generated_copy_adds_nothing_to_sys_path(probe):
    """Fails if a shim that extends `sys.path` at import time comes back, in any form."""
    assert probe["path_added"] == []


def test_every_relative_import_in_the_generated_copy_resolves(probe):
    """Fails if the rewrite produces a target that does not exist, including in an import that only
    runs inside a function."""
    assert probe["unresolved"] == []
