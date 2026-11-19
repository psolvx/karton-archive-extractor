"""
ACE archive unpacking for the ungoose backend.

Uses the pure-Python-capable ``acefile`` package (with its optional C
accelerator which can be disabled with ACEFILE_FORCE_ACEBITSTREAM=0).

Extraction semantics mirror sevenzip.py:

- every non-directory member is materialized into the temporary
  extraction directory and exposed as an fd-backed ChildFile,
- encrypted archives are reported via ``ExtractedArchive.error``
  (acefile does not accept passwords),
- partial results are kept: members extracted before a failure stay in
  the children list, with the error noted.
"""

import logging
import os
import tempfile
from typing import Optional

import acefile

from .backends import ChildFile, ExtractedArchive, collect_children

logger = logging.getLogger("karton.archive-extractor.ace")


def unpack_ace(
    filepath: bytes,
    filename: bytes,
    password: Optional[str],
) -> ExtractedArchive:
    """Unpack an ACE archive with acefile, returning extracted children.

    Reports unpacking failures via ``error`` field of ExtractedArchive.
    ``password`` is accepted for interface parity but unused: acefile
    raises ``EncryptedArchiveError`` on encrypted archives.
    """
    archive_path = os.fsdecode(filepath)

    result: ExtractedArchive
    with tempfile.TemporaryDirectory(prefix="karton-ae-ace-") as outdir:
        error: Optional[str]
        try:
            with acefile.open(archive_path) as archive:
                _extract_members(archive, outdir)
            error = None
        except acefile.EncryptedArchiveError as e:
            error = f"Encrypted ACE archive: {e}"
        except acefile.CorruptedArchiveError as e:
            # Keep whatever was extracted before the corruption point
            children = collect_children(outdir)
            error = (
                f"Corrupted ACE archive (partial extraction, "
                f"{len(children)} files): {e}"
            )
            logger.warning("ACE partial extraction for %r: %s", filename, e)
            return ExtractedArchive(
                filename=filename, children=children, error=error
            )
        except acefile.AceError as e:
            error = f"ACE unpacking failed: {e}"
        except OSError as e:
            error = f"Failed to read ACE archive: {e}"

        if error is not None:
            children = []
        else:
            children = collect_children(outdir)
        result = ExtractedArchive(
            filename=filename, children=children, error=error
        )

    if result.error is not None:
        logger.warning("ACE unpacking error for %r: %s", filename, result.error)
    return result


def _extract_members(archive: acefile.AceArchive, outdir: str) -> None:
    """Write every non-directory member into ``outdir``."""
    for member in archive.getmembers():
        if member.is_dir():
            continue
        archive.extract(member, path=outdir)
