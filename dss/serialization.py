"""Versioned, strict JSON scenario boundary and CSV pack import."""

import csv
from dataclasses import fields, is_dataclass
import hashlib
import io
import json
from collections.abc import Mapping

from .domain import PathwaySpec, ResourceSpec
from .planning import BatteryRecord, OptionValue, PlanningScenario


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def canonical(value):
    return json.dumps(plain(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def scenario_json(scenario):
    return json.dumps({"schema_version": 1, "scenario": plain(scenario)}, indent=2, allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(text):
    def invalid(value):
        raise ValueError(f"non-finite JSON value: {value}")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=invalid)


def scenario_from_json(text):
    try:
        payload = load_json(text)
        if set(payload) != {"schema_version", "scenario"} or payload["schema_version"] != 1:
            raise ValueError("expected scenario schema_version 1")
        data = dict(payload["scenario"])
        for name, cls in (("batteries", BatteryRecord), ("destinations", PathwaySpec),
                          ("resources", ResourceSpec), ("values", OptionValue)):
            data[name] = tuple(cls(**item) for item in data.get(name, []))
        return PlanningScenario(**data)
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError(f"invalid scenario structure: {error}") from error


def batteries_from_csv(content: bytes):
    """Blank observations remain unknown. Column names match the existing pack dataset."""
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        expected = set(BatteryRecord.__dataclass_fields__)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or set(reader.fieldnames) != expected:
            raise ValueError(f"CSV must have exactly these columns: {sorted(expected)}")
        records = []
        for row in reader:
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("wrong number of fields")
                values = {k: (v.strip() or None) for k, v in row.items()}
                for name in ("soh", "nameplate_kwh", "mass_kg"):
                    if values[name] is not None:
                        values[name] = float(values[name])
                for name in ("safety_class", "periods_held"):
                    if values[name] is not None:
                        number = float(values[name])
                        if not number.is_integer():
                            raise ValueError(f"{name} must be an integer")
                        values[name] = int(number)
                records.append(BatteryRecord(**values))
            except (ValueError, TypeError, OverflowError) as error:
                raise ValueError(f"CSV line {reader.line_num}: {error}") from error
        if not records or len({r.asset_id for r in records}) != len(records):
            raise ValueError("CSV needs at least one pack and unique identifiers")
        return tuple(records)
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"invalid UTF-8 CSV: {error}") from error
