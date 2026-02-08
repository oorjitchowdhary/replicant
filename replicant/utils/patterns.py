"""Common regex patterns used across multiple modules."""
import re

# GitHub URL pattern
GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+")