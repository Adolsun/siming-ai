"""Apply the narrow Phoenix 20.9.0 dataclass fix required on Python 3.11.

MappingProxyType gained hashing in Python 3.12. Phoenix's three empty mapping
defaults therefore fail Python 3.11's dataclass import guard. Use a factory with
the identical immutable value. This changes only the isolated tool environment.
"""

import importlib.metadata
import sys
from pathlib import Path


def main():
    distribution = importlib.metadata.distribution("arize-phoenix")
    if distribution.version != "20.9.0":
        raise RuntimeError(
            "This local compatibility fix is reviewed only for Phoenix 20.9.0"
        )
    target = Path(distribution.locate_file("phoenix/trace/dsl/filter.py"))
    source = target.read_text(encoding="utf-8")
    replacements = {
        "boolean_names: NameMap = MappingProxyType({})": "boolean_names: NameMap = __import__('dataclasses').field(default_factory=lambda: MappingProxyType({}))",
        'iterables: typing.Mapping[str, "_IterableGrammar"] = MappingProxyType({})': 'iterables: typing.Mapping[str, "_IterableGrammar"] = __import__("dataclasses").field(default_factory=lambda: MappingProxyType({}))',
        "annotation_accessor_errors: typing.Mapping[str, str] = MappingProxyType({})": "annotation_accessor_errors: typing.Mapping[str, str] = __import__('dataclasses').field(default_factory=lambda: MappingProxyType({}))",
    }
    for old, new in replacements.items() if sys.version_info < (3, 12) else []:
        if source.count(old) == 1:
            source = source.replace(old, new, 1)
        elif new not in source:
            raise RuntimeError(
                "Phoenix source differs from the reviewed compatibility fix"
            )
    target.write_text(source, encoding="utf-8")
    # Phoenix 20.9.0 binds gRPC to all interfaces even when PHOENIX_HOST is local.
    # This local-only setup uses HTTP OTLP; keep the gRPC listener local as well.
    target = Path(distribution.locate_file("phoenix/server/grpc_server.py"))
    source = target.read_text(encoding="utf-8")
    old, new = 'f"[::]:{self._port}"', 'f"127.0.0.1:{self._port}"'
    if source.count(old) == 2:
        source = source.replace(old, new)
    elif source.count(new) != 2:
        raise RuntimeError(
            "Phoenix gRPC binding differs from the reviewed local configuration"
        )
    target.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
