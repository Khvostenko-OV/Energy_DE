from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BoundariesReport:
    """Result of the boundary reference-data load."""

    loaded: bool = False
    rows_by_level: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"  Loaded           : {'yes' if self.loaded else 'no (already present or error)'}",
            "  Rows by level    : " + (", ".join(f"{k}={v}" for k, v in sorted(self.rows_by_level.items())) or "-"),
            f"  Status           : {'PASS' if self.passed else 'FAIL'}",
        ]
        if self.errors:
            for e in self.errors:
                lines.append(f"  ERROR: {e}")
        return "\n".join(lines)


@dataclass
class ExtractionReport:
    """Result of one unit source extract: counts, version and verification outcome."""

    source: str = ""
    source_row_count: int = 0
    rows_loaded: int = 0
    duplicates_dropped: int = 0
    attributes_empty: int = 0
    loaded_to: str | None = None
    skipped: bool = False
    errors: list[str] = field(default_factory=list)
    total_time: float = 0.0

    @property
    def passed(self) -> bool:
        """True if the extract completed without errors (a skip is also a pass)."""
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"  Source file rows : {self.source_row_count}",
            f"  Rows loaded      : {self.rows_loaded}",
            f"  Duplicates dropped: {self.duplicates_dropped}",
            f"  Empty attributes  : {self.attributes_empty}",
            f"  Loaded to        : {self.loaded_to or '-'}",
            f"  Status           : {'SKIPPED (already loaded)' if self.skipped else ('PASS' if self.passed else 'FAIL')}",
            f"  Total time       : {self.total_time:.3f}s",
        ]
        if self.errors:
            for e in self.errors:
                lines.append(f"  ERROR: {e}")
        return "\n".join(lines)


@dataclass
class TransformReport:
    """Result of one source's transform into its staging tables."""

    source: str = ""
    raw_table: str | None = None
    rows_read: int = 0
    rows_written: int = 0
    join_unmapped: dict[str, int] = field(default_factory=dict)
    bad_quality: int = 0
    quality_reasons: dict[str, int] = field(default_factory=dict)
    properties_count: int = 0
    links_count: int = 0
    errors: list[str] = field(default_factory=list)
    total_time: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"  Raw table        : {self.raw_table or '-'}",
            f"  Rows read        : {self.rows_read}",
            f"  Rows written     : {self.rows_written}",
            "  Join unmapped    : "
            + (", ".join(f"{k}={v}" for k, v in self.join_unmapped.items()) or "-"),
            f"  Bad quality      : {self.bad_quality}",
            "  Quality reasons  : "
            + (", ".join(f"{k}={v}" for k, v in self.quality_reasons.items()) or "-"),
            f"  Properties       : {self.properties_count}",
            f"  Links            : {self.links_count}",
            f"  Status           : {'PASS' if self.passed else 'FAIL'}",
            f"  Total time       : {self.total_time:.3f}s",
        ]
        if self.errors:
            for e in self.errors:
                lines.append(f"  ERROR: {e}")
        return "\n".join(lines)