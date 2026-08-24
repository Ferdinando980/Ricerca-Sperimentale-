"""Minimal subset of the §G data model needed for MVP-0+1. Deliberately not the
full schema from the design review (no ResourceGraphEdge, no CompetenceProfile
statistics yet) -- those come in later MVP steps once there's evidence these two
components (Librarian, procedural memory) actually help."""

from dataclasses import dataclass, field


@dataclass
class Book:
    id: str
    version: int
    title: str
    domain: str
    problem_tags: list[str]
    capability_tags: list[str]
    resource_tags: list[str]
    procedure_text: str
    pattern_id: str
    canonical_problem_id: str
    status: str
    confidence: float
    verification_count: int
    verification_types: list[str]
    # Genealogy (Phase 4 of the library evolution plan, 2026-08-18). All
    # optional/defaulted -- existing YAML files predate these fields, and
    # library/loader.py reads them with .get(key, default) rather than
    # data[key] specifically so old files keep loading unchanged.
    derived_from: str | None = None       # id of the Book this was compressed/derived from
    duplicate_of: str | None = None       # id of another Book judged DUPLICATE (Similarity Checker)
    related_skills: list[str] = field(default_factory=list)  # ids judged RELATED
    parent_skills: list[str] = field(default_factory=list)   # ids combined to create this one (future Skill Generator)
    supersedes: str | None = None
    superseded_by: str | None = None
    generation_method: str = "manual"  # manual | compression | skill_generator


@dataclass
class Task:
    task_id: str
    pattern_id: str
    problem_id: str
    fn_name: str
    buggy_source: str
    test_source: str
    split: str  # KNOWN | VARIANT | NOVEL
    problem_tags: list[str]
    capability_tags: list[str]


@dataclass
class SkillPackage:
    books: list[Book] = field(default_factory=list)
    coverage: str = "NONE"  # FULL | PARTIAL | NONE

    def as_prompt_context(self) -> str:
        if not self.books:
            return ""
        sections = []
        for book in self.books:
            sections.append(f"### {book.title}\n{book.procedure_text.strip()}")
        return "\n\n".join(sections)
