import json
from pathlib import Path
from typing import Dict, Any


BASE_DIR = Path(__file__).resolve().parent
RULES_DIR = BASE_DIR / "version_rules"
DEFAULT_VERSION = "18"


def normalize_version(version: str) -> str:
    if not version:
        return DEFAULT_VERSION

    version = version.strip()
    major = version.split(".")[0]

    if major in {"16", "17", "18"}:
        return major

    return DEFAULT_VERSION


def load_version_file(version: str) -> Dict[str, Any]:
    major = normalize_version(version)
    file_path = RULES_DIR / f"pg{major}.json"

    if not file_path.exists():
        file_path = RULES_DIR / f"pg{DEFAULT_VERSION}.json"

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_version_context(version: str) -> Dict[str, Any]:
    return load_version_file(version)


def build_version_prompt_block(version: str) -> str:
    context = get_version_context(version)

    doc_lines = "\n".join(f"- {line}" for line in context.get("documentation_summary", []))
    rule_lines = "\n".join(f"- {line}" for line in context.get("prompt_rules", []))

    return f"""
Version Context:
Target Version: {context.get('label', 'PostgreSQL')}

Documentation Guidance:
{doc_lines if doc_lines else '- No documentation guidance available.'}

Version-Specific Rules:
{rule_lines if rule_lines else '- No version-specific rules available.'}
""".strip()


def validate_version_rules(sql: str, version: str) -> tuple[bool, str]:
    context = get_version_context(version)
    blocked_patterns = context.get("blocked_patterns", [])

    sql_lower = sql.lower()

    for pattern in blocked_patterns:
        if pattern.lower() in sql_lower:
            return False, f"Blocked by {context.get('label', 'PostgreSQL')} rules: {pattern}"

    return True, f"SQL passed {context.get('label', 'PostgreSQL')} version checks."