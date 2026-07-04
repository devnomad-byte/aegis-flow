from collections.abc import MutableMapping
from typing import Literal

AlembicIncludeNameType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
]
AlembicParentNames = MutableMapping[
    Literal["schema_name", "table_name", "schema_qualified_table_name"],
    str | None,
]

LANGGRAPH_CHECKPOINT_TABLES = frozenset(
    {
        "checkpoint_blobs",
        "checkpoint_migrations",
        "checkpoint_writes",
        "checkpoints",
    }
)


def include_name(
    name: str | None,
    type_: AlembicIncludeNameType,
    parent_names: AlembicParentNames,
) -> bool:
    return not (type_ == "table" and name in LANGGRAPH_CHECKPOINT_TABLES)
