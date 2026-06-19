import re

_ROMAN_PREFIX = re.compile(
    r'^(IX|VIII|VII|VI|V|IV|III|II|I)[._]\s*',
    re.IGNORECASE
)

CANONICAL_SECTION_NAMES = [
    "Feature Definition & Objective",
    "Content Strategy & Value Proposition",
    "Scope, Out of Scope, and Dependencies",
    "Studio, Design & Accessibility",
    "Copywriting, Messaging & Compliance",
    "SEO, SEM, Analytics",
    "Campaigns",
    "Engineering, Publishing, QA & Content Model",
    "User Stories & Acceptance Criteria",
]


def _cmp_key(name: str) -> str:
    """Punctuation-free lowercase key for fuzzy section name matching."""
    name = _ROMAN_PREFIX.sub('', name)
    name = name.replace('_', ' ')
    name = name.replace('&', 'and')
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name


_KEY_TO_CANONICAL: dict[str, str] = {
    _cmp_key(c): c for c in CANONICAL_SECTION_NAMES
}


def normalize_section_name(name: str) -> str:
    """Map any Reviewer section key variant to the canonical display name.

    Handles Roman numeral prefixes ("I. Feature Definition & Objective"),
    underscore separators ("I_Feature_Definition_and_Objective"), and
    'and'/'&' differences. Returns the input unchanged if no match is found.
    """
    if name in CANONICAL_SECTION_NAMES:
        return name
    return _KEY_TO_CANONICAL.get(_cmp_key(name), name)


def normalize_scorecard(scorecard: dict) -> dict:
    """Return a copy of *scorecard* with all section keys normalized."""
    if "sections" not in scorecard:
        return scorecard
    return {
        **scorecard,
        "sections": {
            normalize_section_name(k): v
            for k, v in scorecard["sections"].items()
        },
    }
