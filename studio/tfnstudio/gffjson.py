"""Typed-field helpers and a byte-exact reader/writer for nwn_gff-style JSON.

TFN's source tree stores GFF resources as the JSON that `nwn_gff -p` emits
(`nasher` unpack).  To keep git diffs minimal we must re-serialize files exactly
the way that tool does: 2-space indent, UTF-8 (no ASCII escaping), and floats
printed with `%.16g` falling back to `%.17g` when that does not round-trip.
Python's stock `json.dumps` differs only in float text, hence this writer.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

INDENT = 2


def fmt_float(x: float) -> str:
    """Format a float like nwn_gff does (%.16g, else %.17g, always float-looking)."""
    if math.isnan(x) or math.isinf(x):  # not representable in JSON; never expected
        raise ValueError(f"cannot serialize non-finite float {x!r}")
    s = "%.16g" % x
    if float(s) != x:
        s = "%.17g" % x
    if "." not in s and "e" not in s and "E" not in s:
        s += ".0"
    return s


def _write(obj: Any, level: int, out: list[str]) -> None:
    if isinstance(obj, dict):
        if not obj:
            out.append("{}")
            return
        pad = " " * (INDENT * (level + 1))
        out.append("{\n")
        first = True
        for key, val in obj.items():
            if not first:
                out.append(",\n")
            first = False
            out.append(pad)
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(": ")
            _write(val, level + 1, out)
        out.append("\n" + " " * (INDENT * level) + "}")
    elif isinstance(obj, (list, tuple)):
        if not obj:
            out.append("[]")
            return
        pad = " " * (INDENT * (level + 1))
        out.append("[\n")
        first = True
        for val in obj:
            if not first:
                out.append(",\n")
            first = False
            out.append(pad)
            _write(val, level + 1, out)
        out.append("\n" + " " * (INDENT * level) + "]")
    elif isinstance(obj, str):
        out.append(json.dumps(obj, ensure_ascii=False))
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif obj is None:
        out.append("null")
    elif isinstance(obj, int):
        out.append(str(obj))
    elif isinstance(obj, float):
        out.append(fmt_float(obj))
    else:
        raise TypeError(f"unsupported JSON type {type(obj).__name__}")


def dumps(obj: Any) -> str:
    """Serialize exactly like `nwn_gff -p` (trailing newline included)."""
    out: list[str] = []
    _write(obj, 0, out)
    return "".join(out) + "\n"


def loads(text: str) -> Any:
    return json.loads(text)


def read(path: str | Path) -> Any:
    return loads(Path(path).read_text(encoding="utf-8"))


def write(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dumps(obj), encoding="utf-8")


def clone(obj: Any) -> Any:
    """Deep copy of plain JSON data (faster than copy.deepcopy)."""
    return json.loads(json.dumps(obj))


# ---------------------------------------------------------------------------
# Typed field constructors  ({"type": ..., "value": ...})
# ---------------------------------------------------------------------------

def _f(type_: str, value: Any) -> dict:
    return {"type": type_, "value": value}


def byte(v: int) -> dict: return _f("byte", int(v))
def char(v: int) -> dict: return _f("char", int(v))
def word(v: int) -> dict: return _f("word", int(v))
def short(v: int) -> dict: return _f("short", int(v))
def dword(v: int) -> dict: return _f("dword", int(v))
def int_(v: int) -> dict: return _f("int", int(v))
def float_(v: float) -> dict: return _f("float", float(v))
def cexostring(v: str) -> dict: return _f("cexostring", str(v))
def resref(v: str) -> dict: return _f("resref", str(v))


def locstring(text: str, strref: int | None = None) -> dict:
    """CExoLocString with the single English/default entry TFN uses ("0")."""
    d = {"type": "cexolocstring", "value": {"0": text}}
    if strref is not None:
        d["id"] = strref
    return d


def list_(items: Iterable[dict] | None = None) -> dict:
    return _f("list", list(items or []))


def struct(struct_id: int, **fields: dict) -> dict:
    """A list element / top-level struct: `__struct_id` first, then fields in call order."""
    d: dict = {"__struct_id": struct_id}
    d.update(fields)
    return d


# ---------------------------------------------------------------------------
# Field access
# ---------------------------------------------------------------------------

def get(obj: dict, key: str, default: Any = None) -> Any:
    """Value of a typed field, or `default` when the field is absent."""
    f = obj.get(key)
    if f is None:
        return default
    return f.get("value", default) if isinstance(f, dict) else default


def get_text(obj: dict, key: str, default: str = "") -> str:
    """Text of a CExoLocString field (default-language entry)."""
    v = get(obj, key)
    if isinstance(v, dict):
        if "0" in v:
            return v["0"]
        # other language entries are text; a bare TLK reference ({"id": N}) has no text of its own
        return next((x for k, x in v.items() if k != "id" and isinstance(x, str)), default)
    return default if v is None else str(v)


def set_field(obj: dict, key: str, type_: str, value: Any) -> None:
    """Set (or replace) a typed field, keeping position when it already exists."""
    obj[key] = _f(type_, value)


# ---------------------------------------------------------------------------
# VarTable helpers  (Type: 1=int 2=float 3=string 4=object 5=location)
# ---------------------------------------------------------------------------

VAR_INT, VAR_FLOAT, VAR_STRING, VAR_OBJECT, VAR_LOCATION = 1, 2, 3, 4, 5


def var_entry(name: str, value: int | float | str) -> dict:
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return struct(0, Name=cexostring(name), Type=dword(VAR_INT), Value=int_(value))
    if isinstance(value, float):
        return struct(0, Name=cexostring(name), Type=dword(VAR_FLOAT), Value=float_(value))
    if isinstance(value, str):
        return struct(0, Name=cexostring(name), Type=dword(VAR_STRING), Value=cexostring(value))
    raise TypeError(f"unsupported variable value {value!r}")


def vars_of(owner: dict) -> dict[str, Any]:
    """{name: value} for an object's VarTable (empty when it has none)."""
    out: dict[str, Any] = {}
    for e in (owner.get("VarTable") or {}).get("value", []):
        out[get(e, "Name", "")] = get(e, "Value")
    return out


def get_var(owner: dict, name: str, default: Any = None) -> Any:
    return vars_of(owner).get(name, default)


def set_var(owner: dict, name: str, value: int | float | str) -> None:
    """Add or replace a local variable on a GFF object, creating VarTable if needed."""
    vt = owner.get("VarTable")
    if vt is None:
        vt = list_()
        owner["VarTable"] = vt
    entries = vt["value"]
    new = var_entry(name, value)
    for i, e in enumerate(entries):
        if get(e, "Name") == name:
            entries[i] = new
            return
    entries.append(new)


def del_var(owner: dict, name: str) -> bool:
    vt = owner.get("VarTable")
    if not vt:
        return False
    before = len(vt["value"])
    vt["value"] = [e for e in vt["value"] if get(e, "Name") != name]
    return len(vt["value"]) != before


def del_vars_with_prefix(owner: dict, prefix: str) -> int:
    vt = owner.get("VarTable")
    if not vt:
        return 0
    before = len(vt["value"])
    vt["value"] = [e for e in vt["value"] if not str(get(e, "Name", "")).startswith(prefix)]
    return before - len(vt["value"])
