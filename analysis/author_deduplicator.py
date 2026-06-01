"""Author name deduplication for SBMA research database."""

import sys
import json
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from database.models import Article

logger = setup_logger("author_deduplicator")


class AuthorDeduplicator:
    """Groups variant author names and maps them to canonical forms."""

    def __init__(self, threshold: int = 85):
        self._threshold = threshold
        self._mapping: dict[str, str] | None = None
        self._db = DBManager()

    @property
    def mapping(self) -> dict[str, str]:
        if self._mapping is None:
            self._mapping = self.build_mapping()
        return self._mapping

    def canonicalize(self, name: str) -> str:
        return self.mapping.get(name, name)

    def build_mapping(self) -> dict[str, str]:
        all_names, coauthor_sets = self._collect_names()
        groups = self._cluster_names(all_names, coauthor_sets)
        mapping = {}
        for group in groups:
            canonical = max(group, key=len)
            for name in group:
                mapping[name] = canonical
        self._save_mapping(mapping)
        logger.info(
            f"Author dedup: {len(all_names)} names -> "
            f"{len(set(mapping.values()))} canonical"
        )
        return mapping

    def _collect_names(self) -> tuple[set[str], dict[str, set[str]]]:
        session = self._db.get_session()
        try:
            articles = session.query(Article.authors).all()
        finally:
            session.close()

        all_names: set[str] = set()
        coauthor_sets: dict[str, set[str]] = defaultdict(set)

        for (authors_json,) in articles:
            if not authors_json:
                continue
            names = []
            for a in authors_json:
                name = a.get("name", "") if isinstance(a, dict) else str(a)
                if name:
                    names.append(name)
                    all_names.add(name)
            for i, n1 in enumerate(names):
                for j, n2 in enumerate(names):
                    if i != j:
                        coauthor_sets[n1].add(n2)

        return all_names, coauthor_sets

    def _split_name(self, name: str) -> tuple[str, str]:
        parts = name.strip().split()
        if not parts:
            return ("", "")
        return (parts[0].lower(), " ".join(parts[1:]).lower())

    def _last_names_compatible(self, name_a: str, name_b: str) -> bool:
        last_a, _ = self._split_name(name_a)
        last_b, _ = self._split_name(name_b)
        return last_a == last_b

    def _initials_compatible(self, name_a: str, name_b: str) -> bool:
        _, first_a = self._split_name(name_a)
        _, first_b = self._split_name(name_b)
        if not first_a or not first_b:
            return True
        parts_a = first_a.split()
        parts_b = first_b.split()
        min_len = min(len(parts_a), len(parts_b))
        for i in range(min_len):
            a_tok = parts_a[i]
            b_tok = parts_b[i]
            if len(a_tok) == 1 or len(b_tok) == 1:
                if a_tok[0] != b_tok[0]:
                    return False
            elif a_tok != b_tok:
                return False
        return True

    def _coauthor_overlap(
        self, name_a: str, name_b: str, coauthor_sets: dict[str, set[str]]
    ) -> float:
        set_a = coauthor_sets.get(name_a, set())
        set_b = coauthor_sets.get(name_b, set())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        smaller = min(len(set_a), len(set_b))
        return len(intersection) / smaller if smaller else 0.0

    def _cluster_names(
        self, all_names: set[str], coauthor_sets: dict[str, set[str]]
    ) -> list[set[str]]:
        by_last: dict[str, list[str]] = defaultdict(list)
        for name in all_names:
            last, _ = self._split_name(name)
            by_last[last].append(name)

        groups: list[set[str]] = []

        for last_name, candidates in by_last.items():
            if len(candidates) == 1:
                groups.append({candidates[0]})
                continue

            assigned = [False] * len(candidates)
            local_groups: list[set[str]] = []

            for i in range(len(candidates)):
                if assigned[i]:
                    continue
                group = {candidates[i]}
                assigned[i] = True
                for j in range(i + 1, len(candidates)):
                    if assigned[j]:
                        continue
                    if not self._initials_compatible(candidates[i], candidates[j]):
                        continue
                    score = fuzz.token_sort_ratio(candidates[i], candidates[j])
                    coauthor_bonus = (
                        10
                        if self._coauthor_overlap(
                            candidates[i], candidates[j], coauthor_sets
                        )
                        > 0.2
                        else 0
                    )
                    if score + coauthor_bonus >= self._threshold:
                        group.add(candidates[j])
                        assigned[j] = True
                local_groups.append(group)

            groups.extend(local_groups)

        return groups

    def _save_mapping(self, mapping: dict[str, str]) -> None:
        output_path = config.OUTPUTS_DIR / "author_canonical_map.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_groups: dict[str, list[str]] = defaultdict(list)
        for variant, canonical in sorted(mapping.items()):
            if variant != canonical:
                canonical_groups[canonical].append(variant)
        save_data = {
            canon: sorted(variants)
            for canon, variants in sorted(canonical_groups.items())
            if variants
        }
        output_path.write_text(json.dumps(save_data, indent=2, ensure_ascii=False))
        logger.info(f"Canonical map saved to {output_path}")
