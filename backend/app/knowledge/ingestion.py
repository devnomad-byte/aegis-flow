import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

ContentFormat = Literal["text", "markdown"]
ChunkKind = Literal["parent", "child"]

_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\sA-Za-z0-9_\u4e00-\u9fff]")
_MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class ChunkPipelineConfig:
    parent_target_tokens: int = 1600
    child_target_tokens: int = 450
    child_overlap_tokens: int = 80
    text_preview_chars: int = 500

    def __post_init__(self) -> None:
        if self.parent_target_tokens < 40:
            raise ValueError("parent_target_tokens must be at least 40")
        if self.child_target_tokens < 16:
            raise ValueError("child_target_tokens must be at least 16")
        if self.child_overlap_tokens < 0:
            raise ValueError("child_overlap_tokens must be non-negative")
        if self.child_overlap_tokens >= self.child_target_tokens:
            raise ValueError("child_overlap_tokens must be smaller than child_target_tokens")


@dataclass(frozen=True)
class ChunkDraft:
    chunk_ref: str
    kind: ChunkKind
    ordinal: int
    text: str
    token_count: int
    content_hash: str
    parent_ref: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionPipelineResult:
    normalized_text: str
    source_hash: str
    content_hash: str
    chunks: tuple[ChunkDraft, ...]


@dataclass(frozen=True)
class _Section:
    text: str
    heading_path: str


class KnowledgeIngestionPipeline:
    def __init__(self, config: ChunkPipelineConfig | None = None) -> None:
        self._config = config or ChunkPipelineConfig()

    def build_chunks(
        self,
        content: str,
        *,
        content_format: ContentFormat,
    ) -> IngestionPipelineResult:
        normalized_text = normalize_document_text(content)
        if not normalized_text:
            raise ValueError("document content cannot be empty")
        sections = (
            _extract_markdown_sections(normalized_text) if content_format == "markdown" else []
        )
        if not sections:
            sections = [_Section(text=normalized_text, heading_path="")]

        parent_chunks = self._build_parent_chunks(sections)
        chunks: list[ChunkDraft] = list(parent_chunks)
        child_ordinal = len(chunks) + 1
        for parent in parent_chunks:
            child_texts = _split_text_by_token_limit(
                parent.text,
                target_tokens=self._config.child_target_tokens,
                overlap_tokens=self._config.child_overlap_tokens,
            )
            for index, child_text in enumerate(child_texts, start=1):
                chunks.append(
                    ChunkDraft(
                        chunk_ref=f"child-{parent.ordinal:04d}-{index:04d}",
                        kind="child",
                        ordinal=child_ordinal,
                        text=child_text,
                        token_count=estimate_token_count(child_text),
                        content_hash=compute_content_hash(child_text),
                        parent_ref=parent.chunk_ref,
                        metadata=parent.metadata,
                    )
                )
                child_ordinal += 1

        return IngestionPipelineResult(
            normalized_text=normalized_text,
            source_hash=compute_content_hash(content),
            content_hash=compute_content_hash(normalized_text),
            chunks=tuple(chunks),
        )

    def _build_parent_chunks(self, sections: list[_Section]) -> list[ChunkDraft]:
        parents: list[ChunkDraft] = []
        current_texts: list[str] = []
        current_heading_paths: list[str] = []
        current_tokens = 0

        def flush() -> None:
            nonlocal current_texts, current_heading_paths, current_tokens
            if not current_texts:
                return
            text = "\n\n".join(current_texts).strip()
            heading_path = _merge_heading_paths(current_heading_paths)
            parents.append(
                ChunkDraft(
                    chunk_ref=f"parent-{len(parents) + 1:04d}",
                    kind="parent",
                    ordinal=len(parents) + 1,
                    text=text,
                    token_count=estimate_token_count(text),
                    content_hash=compute_content_hash(text),
                    parent_ref=None,
                    metadata={"heading_path": heading_path},
                )
            )
            current_texts = []
            current_heading_paths = []
            current_tokens = 0

        for section in sections:
            section_tokens = estimate_token_count(section.text)
            if section_tokens > self._config.parent_target_tokens:
                flush()
                for parent_text in _split_text_by_token_limit(
                    section.text,
                    target_tokens=self._config.parent_target_tokens,
                    overlap_tokens=0,
                ):
                    parents.append(
                        ChunkDraft(
                            chunk_ref=f"parent-{len(parents) + 1:04d}",
                            kind="parent",
                            ordinal=len(parents) + 1,
                            text=parent_text,
                            token_count=estimate_token_count(parent_text),
                            content_hash=compute_content_hash(parent_text),
                            parent_ref=None,
                            metadata={"heading_path": section.heading_path},
                        )
                    )
                continue

            if (
                current_texts
                and current_tokens + section_tokens > self._config.parent_target_tokens
            ):
                flush()
            current_texts.append(section.text)
            if section.heading_path:
                current_heading_paths.append(section.heading_path)
            current_tokens += section_tokens

        flush()
        return parents


def normalize_document_text(content: str) -> str:
    text = content.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def estimate_token_count(content: str) -> int:
    return len(_TOKEN_PATTERN.findall(content))


def _extract_markdown_sections(text: str) -> list[_Section]:
    sections: list[_Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_heading_path = ""

    def flush() -> None:
        nonlocal current_lines
        section_text = "\n".join(current_lines).strip()
        if section_text:
            sections.append(_Section(text=section_text, heading_path=current_heading_path))
        current_lines = []

    for line in text.split("\n"):
        match = _MARKDOWN_HEADING_PATTERN.match(line)
        if match is not None:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack[:] = [
                (item_level, item_title)
                for item_level, item_title in heading_stack
                if item_level < level
            ]
            heading_stack.append((level, title))
            current_heading_path = " / ".join(item_title for _, item_title in heading_stack)
        current_lines.append(line)

    flush()
    return sections


def _split_text_by_token_limit(
    text: str,
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    matches = list(_TOKEN_PATTERN.finditer(text))
    if not matches:
        stripped = text.strip()
        return [stripped] if stripped else []
    if len(matches) <= target_tokens:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(matches):
        end = min(start + target_tokens, len(matches))
        chunk = text[matches[start].start() : matches[end - 1].end()].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(matches):
            break
        start = max(end - overlap_tokens, start + 1)
    return chunks


def _merge_heading_paths(heading_paths: list[str]) -> str:
    unique_paths: list[str] = []
    for path in heading_paths:
        if path and path not in unique_paths:
            unique_paths.append(path)
    return " | ".join(unique_paths)
