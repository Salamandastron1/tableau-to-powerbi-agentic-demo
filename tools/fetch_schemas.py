"""Refresh the pinned Microsoft JSON schemas and their references (network needed)."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://developer.microsoft.com/json-schemas/"
SCHEMAS = {
    "pbip": BASE + "fabric/pbip/pbipProperties/1.0.0/schema.json",
    "pbism": BASE + "fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
    "pbir": BASE + "fabric/item/report/definitionProperties/2.0.0/schema.json",
    "report": BASE + "fabric/item/report/definition/report/3.1.0/schema.json",
    "page": BASE + "fabric/item/report/definition/page/2.0.0/schema.json",
    "pages": BASE + "fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
    "version": BASE + "fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
    "visual": BASE + "fabric/item/report/definition/visualContainer/2.1.0/schema.json",
}


def cache_path(url: str) -> Path:
    if not url.startswith(BASE):
        raise ValueError(f"Schema reference outside Microsoft's schema host: {url}")
    parts = urlparse(url).path.removeprefix("/json-schemas/").split("/")
    if ".." in parts:
        raise ValueError(f"Unsafe schema path: {url}")
    return ROOT / "schemas" / Path(*parts)


def references(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for item in value.values():
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def main() -> None:
    pending = list(SCHEMAS.values())
    downloaded = {}
    while pending:
        url = urldefrag(pending.pop())[0]
        if url in downloaded:
            continue
        with urlopen(url, timeout=30) as response:
            content = response.read().replace(b"\r\n", b"\n")
        document = json.loads(content)
        path = cache_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        downloaded[url] = hashlib.sha256(content).hexdigest()
        for ref in references(document):
            target = urldefrag(urljoin(url, ref))[0]
            if target not in downloaded:
                pending.append(target)
        print(f"Fetched {url}")
    manifest = ROOT / "schemas" / "manifest.json"
    manifest.write_text(json.dumps({"roots": SCHEMAS, "sha256": dict(sorted(downloaded.items()))},
                                   indent=2) + "\n", encoding="utf-8")
    with urlopen("https://raw.githubusercontent.com/microsoft/json-schemas/main/LICENSE", timeout=30) as response:
        license_text = response.read().decode("utf-8").replace("\r\n", "\n")
    (ROOT / "schemas" / "LICENSE.txt").write_text(license_text, encoding="utf-8", newline="\n")
    print(f"Cached {len(downloaded)} official schemas; offline checks now available.")


if __name__ == "__main__":
    main()
