"""SFX config for AI-DM library pipeline.

2026-04-23 v2 note:
- Keeps original 6 category buckets and 50 keyword buckets unchanged.
- Adds keyword-level audit thresholds, alias fallback, and noisy-token filters.
"""

from __future__ import annotations

from typing import Dict, List, Set


SFX_LIBRARY_DIR = "audio_library/sfx"
SFX_BUNDLE_DIR = "audio_library/sfx_demo_bundle"

METADATA_FILENAME = "metadata.csv"
REJECTED_FILENAME = "rejected.csv"
SUMMARY_FILENAME = "summary.json"
LICENSE_MANIFEST_FILENAME = "license_manifest.csv"
KEYWORD_AUDIT_CSV_FILENAME = "keyword_audit.csv"
KEYWORD_AUDIT_JSON_FILENAME = "keyword_audit.json"

DEFAULT_TARGET_PER_KEYWORD = 3
DEFAULT_MIN_DURATION_SEC = 0.2
DEFAULT_MAX_DURATION_SEC = 8.0
DEFAULT_RATE_LIMIT = 45
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGE_LIMIT = 4
DEFAULT_MAX_PER_QUERY = 40
DEFAULT_RANDOM_SEED = 42

DEFAULT_MAX_CANDIDATES_PER_KEYWORD = 120
DEFAULT_CANDIDATE_BUFFER_MULTIPLIER = 8
DEFAULT_MAX_ATTEMPTS_PER_KEYWORD = 80
DEFAULT_MAX_AUTHOR_PER_KEYWORD = 2

AUDIT_LOW_SUPPLY_THRESHOLD = 5
AUDIT_NOISY_THRESHOLD = 0.35

ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg"}

# Base quality thresholds. We do not run ML scoring in v2.
RMS_TARGET_DBFS = -20.0
RECOMMENDED_GAIN_MIN_DB = -12.0
RECOMMENDED_GAIN_MAX_DB = 12.0
MIN_VALID_RMS_DBFS = -55.0
MAX_CLIPPING_RATIO = 0.02

MUSIC_LIKE_TOKENS: Set[str] = {
    "ambient",
    "atmosphere",
    "background",
    "cinematic",
    "drone",
    "instrumental",
    "loop",
    "melody",
    "music",
    "orchestra",
    "soundtrack",
    "song",
    "theme",
}

SFX_STYLE_BLOCK_TOKENS: Set[str] = {
    "ambient",
    "atmosphere",
    "background",
    "documentary",
    "drone",
    "meditation",
    "music",
    "pack",
    "song",
    "soundtrack",
}

SFX_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "transition": [
        "whoosh",
        "transition sweep",
        "cinematic rise short",
        "stinger",
        "bell hit",
        "low boom",
        "soft impact",
        "ui confirm",
    ],
    "clue_search": [
        "paper rustle",
        "envelope open",
        "drawer open",
        "cabinet open",
        "key jingle",
        "key turn",
        "object pickup",
        "book page flip",
        "photo pickup",
    ],
    "environment": [
        "door knock",
        "door creak",
        "door open",
        "door close",
        "footsteps wood",
        "footsteps concrete",
        "running footsteps",
        "chair drag",
        "window open",
        "window slam",
    ],
    "suspense_horror": [
        "heartbeat",
        "clock ticking",
        "whisper",
        "breathing tense",
        "wind gust",
        "thunder rumble",
        "metal scrape",
        "sudden hit",
        "horror sting",
    ],
    "conflict_climax": [
        "gunshot",
        "knife slash",
        "glass break",
        "body fall thud",
        "table hit",
        "dramatic impact",
        "crowd gasp",
        "shock hit",
    ],
    "ending": [
        "soft piano hit",
        "sad sting",
        "warm resolve",
        "mystery resolve",
        "relief chime",
        "ending swell",
    ],
}

# Keep keyword buckets unchanged; aliases are query-only fallback.
SFX_KEYWORD_ALIASES: Dict[str, List[str]] = {
    "cinematic rise short": [
        "short riser",
        "transition riser short",
        "whoosh riser short",
    ],
    "envelope open": [
        "envelope tear open",
        "paper envelope open",
        "letter envelope open",
    ],
    "photo pickup": [
        "photo pick up",
        "picture pick up",
        "photo handling",
    ],
    "breathing tense": [
        "tense breathing",
        "heavy breathing",
        "anxious breath",
    ],
    "warm resolve": [
        "soft resolve cue",
        "gentle resolve chime",
        "resolution hit soft",
    ],
    "mystery resolve": [
        "mystery reveal stinger",
        "mystery solve cue",
        "investigation resolve",
    ],
    "relief chime": [
        "success chime soft",
        "relief tone",
        "resolve chime soft",
    ],
    "ending swell": [
        "finale swell short",
        "resolution swell short",
        "ending sting short",
    ],
    # Noisy keywords also get alias chains.
    "thunder rumble": [
        "thunder clap short",
        "distant thunder hit",
        "thunder impact",
    ],
    "horror sting": [
        "horror hit",
        "scare stinger short",
        "horror impact",
    ],
    "shock hit": [
        "shock impact short",
        "sudden impact hit",
        "impact stinger",
    ],
    "soft piano hit": [
        "piano stab short",
        "piano accent hit",
        "single piano hit",
    ],
    "sad sting": [
        "sad stinger short",
        "minor sting",
        "sad impact",
    ],
}

SFX_KEYWORD_NEGATIVE_TOKENS: Dict[str, Set[str]] = {
    "thunder rumble": {"ambient", "cinematic", "drone", "music", "soundtrack"},
    "horror sting": {"ambient", "loop", "melody", "music", "orchestra", "song", "theme"},
    "shock hit": {"ambient", "background", "loop", "music", "soundtrack"},
    "soft piano hit": {"ambient", "melody", "music", "song", "theme", "loop"},
    "sad sting": {"ambient", "melody", "music", "song", "theme", "loop", "soundtrack"},
}

DEFAULT_PRELOAD_HOTSPOTS = ["transition", "clue_search", "suspense_horror"]
