"""Validate the public data and package static files for a project Pages URL."""
import json
import re
import shutil
from datetime import datetime

from scripts.common import ROOT, cycle_year, load, now_iso
from scripts.update import apply_overrides
from scripts.parser import trusted_url


def validate(sources, exams):
    assert len(sources) == 32, "Expected national exam and 31 mainland provincial regions"
    registry = {source["id"]: source for source in sources}
    assert len(registry) == 32
    ids = set()
    for source in sources:
        assert trusted_url(source["portal"], source["domains"]), source["id"]
        for template in source["urls"] + source.get("seeds", []):
            assert trusted_url(template.format(year=cycle_year()), source["domains"]), template
    for exam in exams:
        assert exam["id"] not in ids, f'Duplicate exam {exam["id"]}'
        ids.add(exam["id"])
        source = registry[exam["region_id"]]
        assert 2020 <= exam["year"] <= cycle_year() + 1
        assert trusted_url(exam["announcement_url"], source["domains"]), exam["announcement_url"]
        for key, event in exam["events"].items():
            assert key in ("registration", "payment", "admission", "exam")
            assert trusted_url(event["source_url"], source["domains"])
            assert event.get("verification") in ("manual", "auto")
            assert event.get("evidence"), f'{exam["id"]}/{key}: missing evidence'
            for field in ("start", "end"):
                value = event.get(field)
                if value:
                    parsed = datetime.fromisoformat(value)
                    assert exam["year"] - 1 <= parsed.year <= exam["year"] + 1
                    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00", value)
            if event.get("end"):
                assert event["start"] <= event["end"], f'{exam["id"]}/{key}: reversed interval'


def main():
    sources = load("sources.json", [])
    exams = apply_overrides(load("exams.json", []), load("overrides.json", []))
    validate(sources, exams)
    output = ROOT / "_site"
    output.mkdir(exist_ok=True)
    for path in (ROOT / "site").rglob("*"):
        if path.is_file():
            target = output / path.relative_to(ROOT / "site")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    data_dir = output / "data"
    data_dir.mkdir(exist_ok=True)
    public_sources = [{key: source[key] for key in ("id", "name", "group", "portal")} for source in sources]
    catalog = {"schema_version": 1, "built_at": now_iso(), "cycle_year": cycle_year(), "regions": public_sources,
               "exams": exams, "notices": load("notices.json", []), "status": load("status.json", {})}
    (data_dir / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f'Built {output}: {len(sources)} regions, {len(exams)} exam records')


if __name__ == "__main__":
    main()
