"""Generate the Windows version resource for the bundled executables.

PyInstaller only stamps ProductName/ProductVersion onto an .exe when given a
version resource file. Code signing programs (SignPath Foundation among them)
require those attributes on signed binaries, and Windows shows them in the file
properties dialog and the SmartScreen prompt.

The version comes from backend/app/release_notes.py, which is the single source
of truth for the app version, so nothing here needs bumping at release time.
"""

from pathlib import Path

# ASCII-only: the resource file is parsed as a Python literal by PyInstaller.
_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers},
    prodvers={vers},
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Backchannel'),
          StringStruct('FileDescription', '{description}'),
          StringStruct('FileVersion', '{version}.0'),
          StringStruct('InternalName', '{stem}'),
          StringStruct('LegalCopyright', 'MIT License'),
          StringStruct('OriginalFilename', '{filename}'),
          StringStruct('ProductName', 'Backchannel'),
          StringStruct('ProductVersion', '{version}.0'),
        ],
      ),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def file_version(version):
    """Turn "0.4.0" into the 4-tuple Windows version resources require."""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"expected a three-part version, got {version!r}")
    major, minor, patch = (int(part) for part in parts)
    return (major, minor, patch, 0)


def resource_text(version, filename, description):
    return _TEMPLATE.format(
        vers=file_version(version),
        version=version,
        filename=filename,
        stem=Path(filename).stem,
        description=description,
    )


def write_resource(directory, version, filename, description):
    """Write the resource next to the build and return its path."""
    target = Path(directory) / f"{Path(filename).stem}_version.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(resource_text(version, filename, description), encoding="ascii")
    return target
