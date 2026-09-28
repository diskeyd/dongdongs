"""dongdongs: semi-automated transfer of test-report PDF results into an existing HWP report."""

__version__ = "0.1.0"

# GitHub's "Download ZIP" fills this in (export-subst in .gitattributes); a git checkout keeps the placeholder
_BUILD = "$Format:%h %cs$"
BUILD = "dev" if _BUILD.startswith("$") else _BUILD
