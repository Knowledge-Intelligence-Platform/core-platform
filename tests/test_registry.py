"""The registry is the authoritative mapping; nothing may be inferred."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.registry import ComponentRegistry, load_registry

REGISTRY = Path("tests/fixtures-registry/components")


@pytest.fixture(scope="module")
def registry() -> ComponentRegistry:
    return ComponentRegistry(REGISTRY)


def test_blank_component_files_are_skipped(registry: ComponentRegistry) -> None:
    # integration.yaml is an empty placeholder and must not become a component.
    assert all(component.id for component in registry.components)
    assert "integration" not in {component.id for component in registry.components}


def test_repository_names_are_fully_qualified(registry: ComponentRegistry) -> None:
    for _component, name, _branch in registry.repositories():
        assert "/" in name, f"{name} is not owner/repository"


def test_documents_describe_each_component(registry: ComponentRegistry) -> None:
    documents = registry.as_documents()
    assert len(documents) == len(registry.components)
    assert all(document.blocks for document in documents)


def test_confluence_prefix_maps_to_one_component(registry: ComponentRegistry) -> None:
    component = registry.component_for_s3_key("raw/confluence/kip-service/page.pdf")
    assert component is not None
    assert component.id == "kip-service"


def test_unmapped_source_is_not_guessed(registry: ComponentRegistry) -> None:
    assert registry.component_for_s3_key("raw/confluence/unknown/page.pdf") is None


def test_missing_registry_directory_is_rejected() -> None:
    with pytest.raises(ValueError, match="Component registry not found"):
        ComponentRegistry(Path("registry/does-not-exist"))


def write(directory: Path, name: str, body: str) -> None:
    (directory / f"{name}.yaml").write_text(body, encoding="utf-8")


BASE = """
id: {id}
name: {name}
description: A component.
"""


def test_an_empty_registry_file_is_a_hard_error(tmp_path: Path) -> None:
    write(tmp_path, "good", BASE.format(id="good", name="Good"))
    (tmp_path / "empty.yaml").write_text("   \n", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        ComponentRegistry(tmp_path)


def test_a_relationship_to_an_unknown_component_is_rejected(tmp_path: Path) -> None:
    write(
        tmp_path,
        "hub",
        BASE.format(id="hub", name="Hub")
        + "related:\n  - id: missing\n    relationship: Includes\n",
    )

    with pytest.raises(ValueError, match="unknown component"):
        ComponentRegistry(tmp_path)


def test_a_component_cannot_relate_to_itself(tmp_path: Path) -> None:
    write(
        tmp_path,
        "hub",
        BASE.format(id="hub", name="Hub")
        + "related:\n  - id: hub\n    relationship: Includes\n",
    )

    with pytest.raises(ValueError, match="related to itself"):
        ComponentRegistry(tmp_path)


def test_relationships_are_indexed_as_sentences(tmp_path: Path) -> None:
    write(tmp_path, "leaf", BASE.format(id="leaf", name="Leaf Service") + "part_of: hub\n")
    write(
        tmp_path,
        "hub",
        BASE.format(id="hub", name="Hub")
        + "related:\n  - id: leaf\n    relationship: Includes\n",
    )
    registry = ComponentRegistry(tmp_path)

    document = next(d for d in registry.as_documents() if d.component_id == "hub")
    assert "Hub includes Leaf Service." in document.blocks[0].text


def test_a_contact_is_never_indexed(tmp_path: Path) -> None:
    write(
        tmp_path,
        "hub",
        BASE.format(id="hub", name="Hub")
        + 'contact:\n  name: Platform Engineering\n  slack: "#kip-support"\n',
    )
    registry = ComponentRegistry(tmp_path)

    document = registry.as_documents()[0]
    assert "kip-support" not in document.blocks[0].text
    assert "Platform Engineering" not in document.blocks[0].text


def test_a_component_can_be_found_by_id(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    registry = ComponentRegistry(tmp_path)

    assert registry.component_by_id("hub") is not None
    assert registry.component_by_id("nope") is None


def test_a_component_that_forgets_its_parent_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    write(tmp_path, "orphan", BASE.format(id="orphan", name="Orphan"))

    with pytest.raises(ValueError, match="Exactly one component must be the root"):
        ComponentRegistry(tmp_path)


def test_a_parent_that_does_not_exist_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    write(tmp_path, "leaf", BASE.format(id="leaf", name="Leaf") + "part_of: missing\n")

    with pytest.raises(ValueError, match="part of an unknown component"):
        ComponentRegistry(tmp_path)


def test_a_hierarchy_cycle_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    write(tmp_path, "a", BASE.format(id="a", name="A") + "part_of: b\n")
    write(tmp_path, "b", BASE.format(id="b", name="B") + "part_of: a\n")

    with pytest.raises(ValueError, match="cycle"):
        ComponentRegistry(tmp_path)


def test_membership_is_stated_from_both_sides(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    write(tmp_path, "leaf", BASE.format(id="leaf", name="Leaf Service") + "part_of: hub\n")
    registry = ComponentRegistry(tmp_path)

    documents = {d.component_id: d.blocks[0].text for d in registry.as_documents()}
    assert "Leaf Service is part of Hub." in documents["leaf"]
    assert "Hub includes Leaf Service." in documents["hub"]


def test_a_new_component_joins_the_hierarchy_without_editing_the_hub(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    write(tmp_path, "first", BASE.format(id="first", name="First") + "part_of: hub\n")
    write(tmp_path, "second", BASE.format(id="second", name="Second") + "part_of: hub\n")
    registry = ComponentRegistry(tmp_path)

    assert {c.id for c in registry.children_of("hub")} == {"first", "second"}
    hub = next(d for d in registry.as_documents() if d.component_id == "hub")
    assert "Hub includes First." in hub.blocks[0].text
    assert "Hub includes Second." in hub.blocks[0].text


def test_the_shipped_registry_has_a_single_root() -> None:
    registry = ComponentRegistry(Path("tests/fixtures-registry/components"))

    roots = [c.id for c in registry.components if c.part_of is None]
    assert roots == ["kip-platform"]
    assert len(registry.children_of("kip-platform")) == len(registry.components) - 1


def test_the_shipped_registry_still_loads() -> None:
    registry = ComponentRegistry(Path("tests/fixtures-registry/components"))

    assert {component.id for component in registry.components} >= {
        "kip-service",
        "knowledge-source",
        "operations",
        "kip-platform",
    }


def test_a_nested_component_can_be_four_levels_deep(tmp_path: Path) -> None:
    write(tmp_path, "kip", BASE.format(id="kip", name="KIP"))
    write(
        tmp_path,
        "kip-service",
        BASE.format(id="kip-service", name="KIP Service") + "part_of: kip\n",
    )
    write(tmp_path, "found", BASE.format(id="found", name="Foundation") + "part_of: kip-service\n")
    write(tmp_path, "pools", BASE.format(id="pools", name="Node Pools") + "part_of: found\n")
    registry = ComponentRegistry(tmp_path)

    documents = {d.component_id: d.blocks[0].text for d in registry.as_documents()}
    assert "Foundation is part of KIP Service." in documents["found"]
    assert "Foundation includes Node Pools." in documents["found"]


def test_a_nested_component_claims_documents_inside_its_parents_prefix(tmp_path: Path) -> None:
    write(tmp_path, "kip", BASE.format(id="kip", name="KIP"))
    write(
        tmp_path,
        "kip-service",
        BASE.format(id="kip-service", name="KIP Service")
        + "part_of: kip\ndocumentation_prefixes:\n  - raw/confluence/kip-service\n",
    )
    write(
        tmp_path,
        "oidc",
        BASE.format(id="oidc", name="KIP Service OIDC")
        + "part_of: kip-service\ndocumentation_prefixes:\n  - raw/confluence/kip-service/oidc\n",
    )
    registry = ComponentRegistry(tmp_path)

    nested = registry.component_for_s3_key("raw/confluence/kip-service/oidc/doc.pdf")
    parent = registry.component_for_s3_key("raw/confluence/kip-service/other.pdf")
    assert nested is not None and nested.id == "oidc"
    assert parent is not None and parent.id == "kip-service"


NOTE = """notes:
  - note: Windows images follow the RHEL build process.
    recorded: 2026-08-22
    source: Platform sync with Jane
"""


def test_a_note_is_indexed_as_knowledge(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub") + NOTE)
    registry = ComponentRegistry(tmp_path)

    document = registry.as_documents()[0]
    assert "Windows images follow the RHEL build process." in document.blocks[0].text


def test_note_provenance_is_never_indexed(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub") + NOTE)
    registry = ComponentRegistry(tmp_path)

    text = registry.as_documents()[0].blocks[0].text
    assert "Jane" not in text
    assert "Platform sync" not in text
    assert "2026-08-22" not in text


def test_a_note_must_be_dated(tmp_path: Path) -> None:
    write(
        tmp_path,
        "hub",
        BASE.format(id="hub", name="Hub") + "notes:\n  - note: Undated knowledge.\n",
    )

    with pytest.raises(ValidationError):
        ComponentRegistry(tmp_path)


def test_an_empty_note_is_rejected(tmp_path: Path) -> None:
    write(
        tmp_path,
        "hub",
        BASE.format(id="hub", name="Hub") + 'notes:\n  - note: ""\n    recorded: 2026-08-22\n',
    )

    with pytest.raises(ValidationError):
        ComponentRegistry(tmp_path)


def test_a_component_may_carry_several_notes(tmp_path: Path) -> None:
    body = (
        BASE.format(id="hub", name="Hub")
        + "notes:\n"
        + "  - note: First fact.\n    recorded: 2026-08-01\n"
        + "  - note: Second fact.\n    recorded: 2026-08-22\n"
    )
    write(tmp_path, "hub", body)
    registry = ComponentRegistry(tmp_path)

    text = registry.as_documents()[0].blocks[0].text
    assert "First fact." in text and "Second fact." in text
    assert len(registry.components[0].notes) == 2


def test_the_shipped_windows_note_is_recorded() -> None:
    registry = ComponentRegistry(Path("tests/fixtures-registry/components"))
    knowledge_source = registry.component_by_id("knowledge-source")

    assert knowledge_source is not None
    assert any("Windows" in note.note for note in knowledge_source.notes)
    assert all(note.recorded for note in knowledge_source.notes)


def shipped() -> ComponentRegistry:
    return ComponentRegistry(Path("tests/fixtures-registry/components"))


def test_a_directory_round_trips_through_a_document() -> None:
    registry = shipped()
    rebuilt = ComponentRegistry.from_document(registry.as_document())

    assert [c.id for c in rebuilt.components] == [c.id for c in registry.components]
    assert rebuilt.component_by_id("knowledge-source").notes == registry.component_by_id(
        "knowledge-source"
    ).notes  # type: ignore[union-attr]
    assert [d.blocks[0].text for d in rebuilt.as_documents()] == [
        d.blocks[0].text for d in registry.as_documents()
    ]


def test_a_document_is_validated_like_a_directory() -> None:
    document = """
components:
  - id: hub
    name: Hub
    description: A component.
  - id: leaf
    name: Leaf
    description: A component.
    part_of: missing
"""
    with pytest.raises(ValueError, match="part of an unknown component"):
        ComponentRegistry.from_document(document)


def test_a_document_cannot_smuggle_a_second_root() -> None:
    document = """
components:
  - id: one
    name: One
    description: A component.
  - id: two
    name: Two
    description: A component.
"""
    with pytest.raises(ValueError, match="Exactly one component must be the root"):
        ComponentRegistry.from_document(document)


def test_an_empty_document_is_rejected() -> None:
    with pytest.raises(ValueError, match="contains no components"):
        ComponentRegistry.from_document("components: []")

    with pytest.raises(ValueError, match="contains no components"):
        ComponentRegistry.from_document("{}")


def test_a_document_that_is_not_a_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        ComponentRegistry.from_document("- just\n- a\n- list\n")


def test_components_can_be_supplied_directly() -> None:
    registry = ComponentRegistry.from_components(shipped().components)

    assert len(registry.components) == 5
    assert registry.component_by_id("kip-platform") is not None


def test_two_components_claiming_one_prefix_fail_at_load(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    for name in ("one", "two"):
        write(
            tmp_path,
            name,
            BASE.format(id=name, name=name.title())
            + "part_of: hub\ndocumentation_prefixes:\n  - raw/confluence/shared\n",
        )

    with pytest.raises(ValueError, match="both claim the prefix"):
        ComponentRegistry(tmp_path)


def test_a_nested_prefix_is_still_allowed(tmp_path: Path) -> None:
    write(tmp_path, "hub", BASE.format(id="hub", name="Hub"))
    write(
        tmp_path,
        "parent",
        BASE.format(id="parent", name="Parent")
        + "part_of: hub\ndocumentation_prefixes:\n  - raw/confluence/kip-service\n",
    )
    write(
        tmp_path,
        "child",
        BASE.format(id="child", name="Child")
        + "part_of: parent\ndocumentation_prefixes:\n  - raw/confluence/kip-service/oidc\n",
    )

    registry = ComponentRegistry(tmp_path)
    match = registry.component_for_s3_key("raw/confluence/kip-service/oidc/doc.pdf")
    assert match is not None and match.id == "child"


def document_of(directory: Path) -> str:
    return ComponentRegistry(directory).as_document()


def test_without_a_document_key_the_directory_is_used() -> None:
    registry = load_registry(directory=Path("tests/fixtures-registry/components"))

    assert len(registry.components) == 5


def test_a_published_document_wins_and_is_cached(tmp_path: Path) -> None:
    cache = tmp_path / "cache.yaml"
    published = document_of(Path("tests/fixtures-registry/components"))

    registry = load_registry(
        directory=Path("tests/fixtures-registry/components"),
        document_key="registry/registry.yaml",
        cache_path=cache,
        sources=(("published", lambda key: published),),
    )

    assert len(registry.components) == 5
    assert cache.read_text(encoding="utf-8") == published


def test_a_fetch_failure_serves_the_last_known_good(tmp_path: Path) -> None:
    cache = tmp_path / "cache.yaml"
    cache.write_text(document_of(Path("tests/fixtures-registry/components")), encoding="utf-8")

    def explode(key: str) -> str:
        raise RuntimeError("S3 is unavailable")

    registry = load_registry(
        directory=Path("tests/fixtures-registry/components"),
        document_key="registry/registry.yaml",
        cache_path=cache,
        sources=(("published", explode),),
    )

    assert len(registry.components) == 5


def test_an_invalid_published_document_never_stops_startup(tmp_path: Path) -> None:
    cache = tmp_path / "cache.yaml"
    cache.write_text(document_of(Path("tests/fixtures-registry/components")), encoding="utf-8")

    registry = load_registry(
        directory=Path("tests/fixtures-registry/components"),
        document_key="registry/registry.yaml",
        cache_path=cache,
        sources=(("published", lambda key: "components:\n  - id: BROKEN ID\n"),),
    )

    assert len(registry.components) == 5
    assert cache.read_text(encoding="utf-8").startswith("components:")


def test_without_a_cache_it_refuses_to_start(tmp_path: Path) -> None:
    """A tenant must never come up serving whatever was bundled in the image."""
    def explode(key: str) -> str:
        raise RuntimeError("S3 is unavailable")

    with pytest.raises(RuntimeError, match="No component registry"):
        load_registry(
            directory=Path("tests/fixtures-registry/components"),
            document_key="registry/registry.yaml",
            cache_path=tmp_path / "missing.yaml",
            sources=(("published", explode),),
        )


def test_a_failing_source_falls_through_to_the_next(tmp_path: Path) -> None:
    published = document_of(Path("tests/fixtures-registry/components"))
    tried: list[str] = []

    def explode(key: str) -> str:
        tried.append("appconfig")
        raise RuntimeError("AppConfig is unavailable")

    def from_s3(key: str) -> str:
        tried.append("s3")
        return published

    registry = load_registry(
        directory=Path("tests/fixtures-registry/components"),
        document_key="registry/registry.yaml",
        cache_path=tmp_path / "cache.yaml",
        sources=(("appconfig", explode), ("s3", from_s3)),
    )

    assert len(registry.components) == 5
    assert tried == ["appconfig", "s3"]


def test_a_reader_that_ignores_the_key_still_publishes(tmp_path: Path) -> None:
    published = document_of(Path("tests/fixtures-registry/components"))
    seen: list[str] = []

    def appconfig_style(key: str) -> str:
        seen.append(key)
        return published

    registry = load_registry(
        directory=Path("tests/fixtures-registry/components"),
        cache_path=tmp_path / "cache.yaml",
        sources=(("appconfig", appconfig_style),),
    )

    assert len(registry.components) == 5
    assert seen == [""]
    assert (tmp_path / "cache.yaml").is_file()
