from __future__ import annotations

from .model import DepRow, Section


def merge_sections(sections: list[Section]) -> list[Section]:
    """Merge sections with the same title, combining their rows.

    Deduplicates by (ecosystem, name):
    - If current.value is identical across all instances: merge into one row with
      accumulated SOURCE (shows "path +1" format indicating additional sources).
    - If different exact versions or non-comparable: keep all rows.
    - Precedence for non-identical values: exact pin > range > unpinned.
    This ensures version drift between sources is never hidden.
    """
    by_title: dict[str, list[DepRow]] = {}
    for section in sections:
        if not section.rows:
            continue
        by_title.setdefault(section.title, []).extend(section.rows)

    merged_sections: list[Section] = []
    for title, rows in by_title.items():
        if len(rows) <= 1:
            merged_sections.append(Section(title=title, rows=rows))
            continue

        groups: dict[tuple[str, str], list[DepRow]] = {}
        for row in rows:
            key = (row.ecosystem, row.name.lower())
            groups.setdefault(key, []).append(row)

        deduped: list[DepRow] = []
        for (_ecosystem, _name), group in groups.items():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            current_vals = {r.current.value for r in group}
            if len(current_vals) == 1:
                all_sources = "; ".join(r.source for r in group if r.source)
                row0 = group[0]
                extra_count = len(group) - 1
                display_source = f"{all_sources} +{extra_count}" if extra_count else all_sources
                deduped.append(
                    DepRow(
                        ecosystem=row0.ecosystem,
                        name=row0.name,
                        current=row0.current,
                        latest=row0.latest,
                        state=row0.state,
                        source=display_source,
                        source_class=row0.source_class,
                        freshness=row0.freshness,
                        note=row0.note,
                    )
                )
            else:
                exact_rows = [r for r in group if r.current.note not in ("range", "unpinned")]
                unpinned_rows = [r for r in group if r.current.note == "unpinned"]
                range_rows = [r for r in group if r.current.note == "range"]

                if len(exact_rows) >= 1:
                    deduped.extend(exact_rows)
                if range_rows:
                    deduped.extend(range_rows)
                if unpinned_rows:
                    deduped.extend(unpinned_rows)

        merged_sections.append(Section(title=title, rows=deduped))

    return merged_sections
