from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SkillProfile = Literal["baseline", "candidate", "approved"]


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    name: str
    description: str
    version: str
    sha256: str
    content: str


class SkillRegistryError(RuntimeError):
    pass


class SkillRegistry:
    """Load small project skills without putting the whole catalog in every prompt."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(__file__).with_name("skills")).resolve()
        self.manifest_path = self.root / "manifest.json"

    def _manifest(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillRegistryError("Skill manifest is unavailable or invalid") from exc
        if payload.get("schema_version") != 1:
            raise SkillRegistryError("Unsupported Skill manifest schema")
        return payload

    @staticmethod
    def _frontmatter(text: str) -> tuple[dict[str, str], str]:
        lines = text.splitlines()
        if len(lines) < 4 or lines[0].strip() != "---":
            raise SkillRegistryError("SKILL.md is missing YAML frontmatter")
        try:
            end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        except StopIteration as exc:
            raise SkillRegistryError("SKILL.md frontmatter is not closed") from exc
        metadata: dict[str, str] = {}
        for line in lines[1:end]:
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip().strip('"')
        return metadata, "\n".join(lines[end + 1 :]).strip()

    def _load(self, name: str, definition: dict[str, Any]) -> LoadedSkill:
        folder = (self.root / name).resolve()
        try:
            folder.relative_to(self.root)
        except ValueError as exc:
            raise SkillRegistryError(f"Unsafe Skill path: {name}") from exc
        path = folder / "SKILL.md"
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillRegistryError(f"Skill file is unavailable: {name}") from exc
        metadata, body = self._frontmatter(raw)
        if metadata.get("name") != name:
            raise SkillRegistryError(f"Skill name mismatch: {name}")
        description = metadata.get("description", "").strip()
        if not description or not body:
            raise SkillRegistryError(f"Skill is incomplete: {name}")
        return LoadedSkill(
            name=name,
            description=description,
            version=str(definition.get("version", "0")),
            sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            content=body,
        )

    def select(
        self,
        profile: SkillProfile,
        stage: str,
        *,
        iteration: int = 0,
    ) -> list[LoadedSkill]:
        manifest = self._manifest()
        profiles = manifest.get("profiles", {})
        if profile not in profiles:
            raise SkillRegistryError(f"Unknown Skill profile: {profile}")
        definitions = manifest.get("skills", {})
        selected: list[LoadedSkill] = []
        for name in profiles[profile]:
            definition = definitions.get(name)
            if not isinstance(definition, dict):
                raise SkillRegistryError(f"Skill is not defined: {name}")
            if stage not in definition.get("stages", []):
                continue
            mode = definition.get("mode", "all")
            if mode == "first_pass" and iteration > 0:
                continue
            if mode == "revision" and iteration == 0:
                continue
            selected.append(self._load(name, definition))
        return selected

    @staticmethod
    def packet(skills: list[LoadedSkill]) -> dict[str, Any]:
        entries = [
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "sha256": skill.sha256,
                "instructions": skill.content,
            }
            for skill in skills
        ]
        canonical = json.dumps(
            [{"name": item["name"], "version": item["version"], "sha256": item["sha256"]} for item in entries],
            ensure_ascii=False,
            sort_keys=True,
        )
        return {
            "bundle_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "skills": entries,
        }

    def describe_profile(self, profile: SkillProfile) -> dict[str, Any]:
        manifest = self._manifest()
        names = list(manifest.get("profiles", {}).get(profile, []))
        loaded = [self._load(name, manifest["skills"][name]) for name in names]
        packet = self.packet(loaded)
        return {
            "profile": profile,
            "skill_names": names,
            "bundle_sha256": packet["bundle_sha256"],
        }
