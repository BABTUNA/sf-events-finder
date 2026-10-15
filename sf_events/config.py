"""env loading, one place

reads .env from the project root so keys never have to be exported. every
optional integration checks its key here and stays off when it is missing
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY") or None
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or None
# only needed when the key is not scoped to a workspace
ANTHROPIC_WORKSPACE_ID = os.environ.get("ANTHROPIC_WORKSPACE_ID") or None
# the classifier reads short bios and search snippets, haiku is plenty
LOOKUP_MODEL = os.environ.get("LOOKUP_MODEL") or "claude-haiku-5-5"


def lookup_enabled() -> bool:
    return bool(FIRECRAWL_API_KEY and ANTHROPIC_API_KEY)
