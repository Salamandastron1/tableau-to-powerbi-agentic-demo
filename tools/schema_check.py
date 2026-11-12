"""Offline schema checks for generated PBIP documents, using pinned Microsoft schemas.

Implements the draft-07 keywords exercised here, not a general JSON Schema library.
"""
import json
import re
from functools import lru_cache
from urllib.parse import unquote, urldefrag, urljoin

try:
    from .fetch_schemas import cache_path
except ImportError:
    from fetch_schemas import cache_path


class SchemaError(ValueError):
    pass


@lru_cache(maxsize=None)
def load(url):
    return json.loads(cache_path(url).read_text(encoding="utf-8-sig"))


def check(value, schema, base, location="$"):
    def fail(message):
        raise SchemaError(f"{location}: {message}")

    if schema is True:
        return
    if schema is False:
        fail("value disallowed by schema")
    if "$ref" in schema:
        url, pointer = urldefrag(urljoin(base, schema["$ref"]))
        target = load(url)
        if pointer:
            for part in unquote(pointer).lstrip("/").split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        check(value, target, url, location)
        return
    kinds = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
    }
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(kinds[t] for t in types):
            fail(f"expected {types}, got {type(value).__name__}")
    if "const" in schema and value != schema["const"]:
        fail(f"expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        fail(f"not in {schema['enum']}")
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        successes, messages = 0, []
        for option in schema[keyword]:
            try:
                check(value, option, base, location)
                successes += 1
            except SchemaError as exc:
                messages.append(str(exc))
        valid = successes == len(schema[keyword]) if keyword == "allOf" else (
            successes >= 1 if keyword == "anyOf" else successes == 1)
        if not valid:
            fail(f"{keyword} failed ({successes} matches): {'; '.join(messages[:2])}")
    if "not" in schema:
        try:
            check(value, schema["not"], base, location)
        except SchemaError:
            pass
        else:
            fail("matched prohibited schema")
    if "if" in schema:
        try:
            check(value, schema["if"], base, location)
            branch = "then"
        except SchemaError:
            branch = "else"
        if branch in schema:
            check(value, schema[branch], base, location)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                fail(f"missing required property {key}")
        props, patterns = schema.get("properties", {}), schema.get("patternProperties", {})
        for key, item in value.items():
            matched = False
            if key in props:
                check(item, props[key], base, f"{location}.{key}")
                matched = True
            for pattern, subschema in patterns.items():
                if re.search(pattern, key):
                    check(item, subschema, base, f"{location}.{key}")
                    matched = True
            if not matched:
                check(item, schema.get("additionalProperties", True), base, f"{location}.{key}")
        for key, dep in schema.get("dependencies", {}).items():
            if key in value:
                if isinstance(dep, list):
                    if any(d not in value for d in dep):
                        fail(f"missing dependency of {key}")
                else:
                    check(value, dep, base, location)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            fail("too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            fail("too many items")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            fail("duplicate items")
        for i, item in enumerate(value):
            items = schema.get("items", True)
            target = items[i] if isinstance(items, list) and i < len(items) else (
                schema.get("additionalItems", True) if isinstance(items, list) else items)
            check(item, target, base, f"{location}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            fail("string length outside allowed range")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            fail(f"does not match {schema['pattern']}")
    if kinds["number"]:
        for key, invalid in (("minimum", lambda n: value < n), ("maximum", lambda n: value > n),
                             ("exclusiveMinimum", lambda n: value <= n), ("exclusiveMaximum", lambda n: value >= n)):
            if key in schema and invalid(schema[key]):
                fail(f"violates {key}: {schema[key]}")


def check_document(document):
    url = document.get("$schema")
    if not url:
        raise SchemaError("Missing $schema")
    check(document, load(url), url)
