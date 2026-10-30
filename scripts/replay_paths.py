"""Keep replay reports separate from original archives and explicit inputs."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def implementation_inputs():
    """Protect program trees, including manifests/resources and inode aliases."""
    return tuple(path for name in ("scripts", "custom_components")
                 for path in (SOURCE_ROOT / name).rglob("*")
                 if "__pycache__" not in path.parts and path.is_file())


def validate_output(output: Path, archive: Path, inputs=()):
    """Reject both lexical/resolved archive paths and existing inode aliases."""
    lexical = Path(os.path.abspath(output))
    archive_lexical = Path(os.path.abspath(archive))
    if (lexical.is_relative_to(archive_lexical)
            or lexical.is_relative_to(archive.resolve())
            or output.resolve().is_relative_to(archive.resolve())):
        raise ValueError("replay output must be outside the source archive")
    _validate_program_output(output, inputs)
    if output.exists() and output.stat().st_nlink > 1 and archive.exists():
        identity = output.stat()
        for source in archive.rglob("*"):
            info = source.stat()
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                raise ValueError("replay output is a hardlink to the source archive")


def _validate_program_output(output, inputs, *, descriptor=None, protected_identities=()):
    """Check the actual opened inode too; the pathname may have been replaced."""
    lexical = Path(os.path.abspath(output))
    if output.is_symlink():
        raise ValueError("replay output must not be a symlink")
    resolved = output.resolve()
    identity = os.fstat(descriptor) if descriptor is not None else output.stat() if output.exists() else None
    protected = set(protected_identities)
    for name in ("scripts", "custom_components"):
        folder = SOURCE_ROOT / name
        if lexical.is_relative_to(folder.absolute()) or resolved.is_relative_to(folder.resolve()):
            raise ValueError("report output must stay outside program directories")
    for source in (*inputs, *implementation_inputs()):
        if source is None:
            continue
        source = Path(source)
        info = source.stat() if source.exists() else None
        if info is not None:
            protected.add((info.st_dev, info.st_ino))
        if resolved == source.resolve():
            raise ValueError("replay output aliases an input file")
    if identity is not None and (identity.st_dev, identity.st_ino) in protected:
        raise ValueError("replay output aliases an input file")
    return identity, frozenset(protected)


def validate_append_output(output: Path, inputs=(), *, descriptor=None, protected_identities=()):
    """Append mutates an inode: require a dedicated target and intact inputs."""
    for source in inputs:
        if source is not None:
            Path(source).stat()
    identity, protected = _validate_program_output(output, inputs, descriptor=descriptor,
                                                  protected_identities=protected_identities)
    if descriptor is not None:
        current = output.stat()
        if (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("append output path changed after opening")
    if identity is not None and identity.st_nlink != 1:
        raise ValueError("append output must be a dedicated file without hardlink aliases")
    return protected


def publish_output(temporary: Path, output: Path, archive: Path, inputs=()):
    """Recheck after computation and publish without following destination links."""
    validate_output(output, archive, inputs)
    temporary.replace(output)


def write_output(body: str, output: Path, archive: Path, inputs=()):
    validate_output(output, archive, inputs)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        publish_output(temporary, output, archive, inputs)
    finally:
        temporary.unlink(missing_ok=True)
