"""Load the authoritative component-to-source mappings."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from urllib.parse import urlparse

import yaml

from app.models import Component, ContentBlock, ParsedDocument, SourceType

LOGGER = logging.getLogger(__name__)
DEFAULT_GITHUB_ORGANIZATION = "example-org"


def load_registry(
    *,
    directory: Path,
    document_key: str = "",
    cache_path: Path | None = None,
    sources: Sequence[tuple[str, Callable[[str], str]]] = (),
) -> ComponentRegistry:
    """Load the registry this deployment should use.

    Without sources this is the local directory, which is what tests and
    development use. With them each is tried in order, the first document that
    loads cleanly wins, and the last document this task loaded is the final
    fallback. Every source belongs to one tenant, and nothing bundled in the
    image is ever reached: coming up with another tenant's mappings would be
    worse than not coming up at all.
    """
    if not sources:
        return ComponentRegistry(directory)
    for name, fetch in sources:
        try:
            document = fetch(document_key)
            registry = ComponentRegistry.from_document(document)
        except Exception:
            LOGGER.exception(
                "Component registry source unavailable; trying the next.",
                extra={
                    "operation": "load_registry",
                    "component": "registry",
                    "registry_source": name,
                },
            )
            continue
        _remember(document, cache_path)
        return registry
    return _last_known_good(cache_path)


def _remember(document: str, cache_path: Path | None) -> None:
    if cache_path is None:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(document, encoding="utf-8")
    except OSError:
        LOGGER.warning(
            "Component registry cache could not be written.",
            extra={"operation": "load_registry", "component": "registry"},
        )


def _last_known_good(cache_path: Path | None) -> ComponentRegistry:
    if cache_path is not None and cache_path.is_file():
        try:
            registry = ComponentRegistry.from_document(cache_path)
            LOGGER.warning(
                "Serving the last known-good component registry.",
                extra={"operation": "load_registry", "component": "registry"},
            )
            return registry
        except Exception:
            LOGGER.exception(
                "Cached component registry is unusable.",
                extra={"operation": "load_registry", "component": "registry"},
            )
    raise RuntimeError(
        "No component registry could be loaded from any configured source."
    )


class ComponentRegistry:
    """The authoritative component mappings, however they were stored.

    A directory of one file per component is what maintainers edit; a single
    merged document is what gets deployed. Both go through the same validation,
    so a document can never carry rules a directory would have rejected.
    """

    def __init__(self, directory: Path) -> None:
        self.components = self._validated(self._load(directory))

    @classmethod
    def from_components(cls, components: Iterable[Component]) -> ComponentRegistry:
        registry = cls.__new__(cls)
        registry.components = cls._validated(tuple(components))
        return registry

    @classmethod
    def from_document(cls, source: Path | str) -> ComponentRegistry:
        """Load the merged document that CI publishes and the app deploys."""
        raw = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
        document = yaml.safe_load(raw) or {}
        if not isinstance(document, dict):
            raise ValueError("Registry document must be a mapping with a components key.")
        entries = document.get("components")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Registry document contains no components.")
        return cls.from_components(
            Component.model_validate(entry) for entry in entries
        )

    def as_document(self) -> str:
        """Render the registry as the single document a deployment consumes."""
        return yaml.safe_dump(
            {
                "components": [
                    component.model_dump(mode="json", exclude_defaults=True)
                    for component in self.components
                ]
            },
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    @staticmethod
    def _load(directory: Path) -> tuple[Component, ...]:
        if not directory.is_dir():
            raise ValueError(f"Component registry not found: {directory}")
        components: list[Component] = []
        for path in sorted(directory.glob("*.yaml")):
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                raise ValueError(f"Component registry file is empty: {path}")
            components.append(Component.model_validate(yaml.safe_load(raw)))
        if not components:
            raise ValueError(f"Component registry contains no components: {directory}")
        return tuple(components)

    @staticmethod
    def _validated(components: tuple[Component, ...]) -> tuple[Component, ...]:
        if not components:
            raise ValueError("Component registry contains no components.")
        ids = [component.id for component in components]
        if len(ids) != len(set(ids)):
            raise ValueError("Component registry contains duplicate component IDs.")
        known = set(ids)
        for component in components:
            for related in component.related:
                if related.id not in known:
                    raise ValueError(
                        f"{component.id} is related to an unknown component: {related.id}"
                    )
                if related.id == component.id:
                    raise ValueError(f"{component.id} is related to itself.")
        claimed: dict[str, str] = {}
        for component in components:
            for prefix in component.documentation_prefixes:
                owner = claimed.get(prefix)
                if owner is not None:
                    raise ValueError(
                        f"{component.id} and {owner} both claim the prefix: {prefix}"
                    )
                claimed[prefix] = component.id
        ComponentRegistry._validate_hierarchy(tuple(components), known)
        return tuple(components)


    @staticmethod
    def _validate_hierarchy(components: tuple[Component, ...], known: set[str]) -> None:
        roots = [component.id for component in components if component.part_of is None]
        if len(roots) != 1:
            raise ValueError(
                "Exactly one component must be the root; "
                f"every other needs part_of. Found roots: {sorted(roots)}"
            )
        parents = {component.id: component.part_of for component in components}
        for component in components:
            if component.part_of is None:
                continue
            if component.part_of not in known:
                raise ValueError(
                    f"{component.id} is part of an unknown component: {component.part_of}"
                )
            seen = {component.id}
            current: str | None = component.part_of
            while current is not None:
                if current in seen:
                    raise ValueError(f"Component hierarchy has a cycle at {current}.")
                seen.add(current)
                current = parents[current]

    @property
    def root(self) -> Component:
        """The component every other is part of: the platform itself."""
        for component in self.components:
            if component.part_of is None:
                return component
        raise ValueError("The registry has no root component.")

    def children_of(self, component_id: str) -> tuple[Component, ...]:
        return tuple(
            component
            for component in self.components
            if component.part_of == component_id
        )

    def component_by_id(self, component_id: str) -> Component | None:
        for component in self.components:
            if component.id == component_id:
                return component
        return None

    def component_for_s3_key(self, key: str) -> Component | None:
        """The component whose prefix matches most specifically.

        A nested component may claim a prefix inside its parent's, so the longest
        match wins. Two components claiming a prefix of the same length is a real
        ambiguity and stays an error.
        """
        matches: list[tuple[int, Component]] = []
        for component in self.components:
            lengths = [
                len(prefix)
                for prefix in component.documentation_prefixes
                if key.startswith(prefix)
            ]
            if lengths:
                matches.append((max(lengths), component))
        if not matches:
            return None
        best = max(length for length, _ in matches)
        winners = [component for length, component in matches if length == best]
        if len(winners) > 1:
            raise ValueError(f"Multiple components map the Confluence object: {key}")
        return winners[0]

    def repositories(self) -> tuple[tuple[Component, str, str | None], ...]:
        return tuple(
            (component, name, branch)
            for component in self.components
            for name, branch in self._component_repositories(component)
        )

    def as_documents(self) -> tuple[ParsedDocument, ...]:
        documents: list[ParsedDocument] = []
        for component in self.components:
            repositories = ", ".join(
                name for name, _ in self._component_repositories(component)
            )
            prefixes = ", ".join(component.documentation_prefixes)
            text = "\n".join(
                value
                for value in (
                    f"Component: {component.name}",
                    f"Aliases: {', '.join(component.aliases)}"
                    if component.aliases
                    else "",
                    component.description.strip(),
                    f"Repositories: {repositories}" if repositories else "",
                    f"Confluence prefixes: {prefixes}" if prefixes else "",
                    f"Owner: {component.owner}" if component.owner else "",
                    self._related_sentences(component),
                    "\n".join(note.note.strip() for note in component.notes),
                )
                if value
            )
            documents.append(
                ParsedDocument(
                    document_id=hashlib.sha256(
                        f"registry:{component.id}".encode()
                    ).hexdigest(),
                    title=f"{component.name} component registry",
                    source_type=SourceType.REGISTRY,
                    source_location=f"tenant-provided registry data/{component.id}.yaml",
                    component_id=component.id,
                    blocks=(ContentBlock(text=text),),
                )
            )
        return tuple(documents)

    def _related_sentences(self, component: Component) -> str:
        names = {item.id: item.name for item in self.components}
        sentences = []
        if component.part_of:
            sentences.append(
                f"{component.name} is part of {names.get(component.part_of, component.part_of)}."
            )
        sentences.extend(
            f"{component.name} includes {child.name}."
            for child in self.children_of(component.id)
        )
        sentences.extend(
            f"{component.name} {related.relationship.rstrip('.').lower()} "
            f"{names.get(related.id, related.id)}."
            for related in component.related
        )
        return "\n".join(sentences)

    def _component_repositories(
        self, component: Component
    ) -> tuple[tuple[str, str | None], ...]:
        return tuple(
            (self._repository_name(repository.name, repository.url), repository.branch)
            for repository in component.repositories
        )

    @staticmethod
    def _repository_name(name: str, url: str | None) -> str:
        if url:
            parsed = urlparse(url)
            parts = tuple(part for part in parsed.path.split("/") if part)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "github.com"
                or len(parts) != 2
            ):
                raise ValueError(
                    "Repository URL must be https://github.com/<owner>/<repository>."
                )
            return "/".join(parts)
        return name if "/" in name else f"{DEFAULT_GITHUB_ORGANIZATION}/{name}"
