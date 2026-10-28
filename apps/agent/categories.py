"""
Map an app + window title to a category.

Rules are checked in order; the first rule whose `match` text appears
(case-insensitive) in the app name or title wins. Override them per user
in Firestore at users/{uid}/settings/main → categoryRules.
"""

DEFAULT_RULES: list[dict] = [
    # meetings
    {"match": "zoom", "category": "meeting"},
    {"match": "meet.google.com", "category": "meeting"},
    {"match": "teams", "category": "meeting"},
    # communication
    {"match": "slack", "category": "comms"},
    {"match": "discord", "category": "comms"},
    {"match": "whatsapp", "category": "comms"},
    {"match": "gmail", "category": "comms"},
    {"match": "outlook", "category": "comms"},
    # deep work
    {"match": "code", "category": "deep"},          # VS Code, Code.exe
    {"match": "pycharm", "category": "deep"},
    {"match": "intellij", "category": "deep"},
    {"match": "terminal", "category": "deep"},
    {"match": "iterm", "category": "deep"},
    {"match": "figma", "category": "deep"},
    {"match": "notion", "category": "deep"},
    {"match": "docs.google.com", "category": "deep"},
    {"match": "github.com", "category": "deep"},
    {"match": "stackoverflow", "category": "deep"},
    # browsing / distraction
    {"match": "youtube", "category": "browsing"},
    {"match": "instagram", "category": "browsing"},
    {"match": "twitter", "category": "browsing"},
    {"match": "x.com", "category": "browsing"},
    {"match": "reddit", "category": "browsing"},
]


def categorize(app: str, title: str, rules: list[dict]) -> str:
    haystack = f"{app} {title}".lower()
    for rule in rules:
        if rule["match"].lower() in haystack:
            return rule["category"]
    return "other"
