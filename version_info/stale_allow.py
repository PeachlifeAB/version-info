from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from difflib import get_close_matches
from importlib.resources import files
from pathlib import Path
from tempfile import NamedTemporaryFile

from jsonschema import Draft202012Validator, ValidationError

from .model import Section

ALLOW_FILE = ".stale-versions-allow"
_VALIDATOR = Draft202012Validator(
    json.loads(
        files("version_info").joinpath("data/stale-allow.schema.json").read_text(encoding="utf-8")
    )
)


@dataclass(frozen=True)
class StaleAllowance:
    dependency: str
    version: str
    reason: str


def _validate(records: object) -> None:
    try:
        _VALIDATOR.validate(records)
    except ValidationError as error:
        description = (
            error.schema.get("description", error.message)
            if isinstance(error.schema, dict)
            else error.message
        )
        raise ValueError(f"{ALLOW_FILE}: {error.json_path}: {description}") from error


def validate_allowance(allowance: StaleAllowance) -> None:
    _validate([asdict(allowance)])


def load_allowances(root: Path) -> list[StaleAllowance]:
    path = root / ALLOW_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        records: list[dict[str, str]] = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{ALLOW_FILE}: {error}") from error
    _validate(records)
    return [StaleAllowance(**record) for record in records]


def save_allowance(
    root: Path,
    allowances: list[StaleAllowance],
    requested: StaleAllowance,
    sections: list[Section],
) -> None:
    validate_allowance(requested)
    installed = sorted({
        f"{row.name} {row.current.value}"
        for section in sections
        for row in section.rows
        if row.current.value
    })
    target = f"{requested.dependency} {requested.version}"
    if target not in installed:
        closest = get_close_matches(target, installed, n=1, cutoff=0)
        suggestion = f", did you mean {closest[0]}?" if closest else "."
        raise ValueError(f"No matches found{suggestion}")
    updated = [
        allowance
        for allowance in allowances
        if allowance.dependency != requested.dependency or allowance.version != requested.version
    ]
    updated.append(requested)
    report = json.dumps([asdict(allowance) for allowance in updated], indent=2) + "\n"
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=root, prefix=f"{ALLOW_FILE}.", delete=False
    ) as temporary:
        try:
            temporary.write(report)
            temporary.close()
            Path(temporary.name).replace(root / ALLOW_FILE)
        finally:
            Path(temporary.name).unlink(missing_ok=True)


def exclude_allowances(sections: list[Section], allowances: list[StaleAllowance]) -> list[Section]:
    return [
        Section(
            title=section.title,
            rows=[
                row
                for row in section.rows
                if not any(
                    allowance.dependency == row.name and allowance.version == row.current.value
                    for allowance in allowances
                )
            ],
        )
        for section in sections
    ]
