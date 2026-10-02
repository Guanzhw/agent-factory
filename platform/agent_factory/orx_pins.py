"""Reviewed ORX builds, selected by the actual execution platform.

Version text is never a substitute for a reviewed binary digest. Unknown
platforms fail closed; the historic Windows contract remains separately pinned.
"""
import sys

from .openresearch import BinaryPin, OpenResearchError, REVISION, VERSION

WINDOWS_SHA256 = "d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7"
LINUX_SHA256 = "a847d07e8c4c3f2efc47c3549fd27f52c9999b46a21451d4c07ec12de292b8cd"


def approved_pin(platform: str | None = None) -> BinaryPin:
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        sha256 = WINDOWS_SHA256
    elif platform == "linux":
        sha256 = LINUX_SHA256
    else:
        raise OpenResearchError("UNVERIFIED_PLATFORM", "No ORX build is approved for this platform")
    return BinaryPin(REVISION, VERSION, sha256)
