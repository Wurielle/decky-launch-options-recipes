"""Fail-closed local OptiScaler placement discovery; stdlib, no writes/network.

Paths are matched case-insensitively within the caller-selected installation.
Symlinks/case collisions anywhere in its tree cause refusal. The selected root
itself may pass through Steam library symlinks and is resolved once per call.
This is discovery over a stable tree, not an atomic filesystem-write guard.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
import re


# Parsing is seek-based: no whole-executable reads, even for very large games.
_MAX_PE_SIZE = 4 * 1024 ** 3
_GRAPHICS_DLLS = {"dxgi.dll", "d3d11.dll", "d3d12.dll", "d3d9.dll", "vulkan-1.dll"}


def _pe_imports(path: Path) -> set[str] | None:
    """Return bounded normal imports for an AMD64 executable; None if invalid.

    This validates metadata, not authenticity or game compatibility. Delay-load
    imports and dynamically loaded graphics APIs are not renderer evidence here.
    """
    try:
        size = path.stat().st_size
        if not 64 <= size <= _MAX_PE_SIZE:
            return None
        with path.open("rb") as stream:
            def read(offset, length):
                if offset < 0 or length < 0 or length > 65536 or offset + length > size:
                    raise ValueError("PE range outside file")
                stream.seek(offset)
                data = stream.read(length)
                if len(data) != length:
                    raise ValueError("Truncated PE")
                return data

            dos = read(0, 64)
            pe = struct.unpack_from("<I", dos, 60)[0]
            if dos[:2] != b"MZ" or not 64 <= pe <= 1024 * 1024:
                return None
            header = read(pe, 24)
            machine, sections, _, _, _, optional_size, flags = struct.unpack_from("<HHIIIHH", header, 4)
            if (header[:4] != b"PE\0\0" or machine != 0x8664 or not flags & 2
                    or flags & 0x2000 or not 1 <= sections <= 96 or not 128 <= optional_size <= 4096):
                return None
            optional = read(pe + 24, optional_size)
            if struct.unpack_from("<H", optional)[0] != 0x20B:
                return None
            table = read(pe + 24 + optional_size, sections * 40)
            mappings = []
            for index in range(sections):
                _, address, raw_size, raw_offset = struct.unpack_from("<IIII", table, index * 40 + 8)
                if raw_size and (address + raw_size > 2 ** 32 or raw_offset + raw_size > size
                                 or raw_offset < pe + 24 + optional_size + len(table)):
                    return None
                for old_address, old_size, old_offset in mappings:
                    if raw_size and old_size and (
                            max(address, old_address) < min(address + raw_size, old_address + old_size)
                            or max(raw_offset, old_offset) < min(raw_offset + raw_size, old_offset + old_size)):
                        return None
                mappings.append((address, raw_size, raw_offset))

            def locate(rva, length):
                matches = [(offset + rva - address, raw_size - (rva - address))
                           for address, raw_size, offset in mappings
                           if address <= rva and rva + length <= address + raw_size]
                if len(matches) != 1:
                    raise ValueError("Unbacked or ambiguous PE RVA")
                return matches[0]

            if struct.unpack_from("<I", optional, 108)[0] < 2:
                return set()
            import_rva, import_size = struct.unpack_from("<II", optional, 120)
            if not import_rva and not import_size:
                return set()
            if not import_rva or not 20 <= import_size <= 20 * 1024:
                return None
            offset, _ = locate(import_rva, import_size)
            descriptors = read(offset, import_size)
            imports = set()
            for index in range(import_size // 20):
                descriptor = struct.unpack_from("<IIIII", descriptors, index * 20)
                if not any(descriptor):
                    return imports
                name_offset, available = locate(descriptor[3], 1)
                name = read(name_offset, min(available, 256))
                if b"\0" not in name:
                    return None
                imports.add(name.split(b"\0", 1)[0].decode("ascii").casefold())
            return None  # An unterminated directory is not evidence.
    except (OSError, ValueError, struct.error):
        return None


class DiscoveryError(ValueError):
    """Unsafe, unsupported or ambiguous installation context; change nothing."""


def _root(root: Path) -> Path:
    # Steam's library parents may themselves be symlinks; inside this boundary,
    # links are forbidden. Never resolve a descendant before validating it.
    try:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise DiscoveryError(f"Not a game directory: {root}")
        return root
    except OSError as error:
        raise DiscoveryError(f"Cannot read game root: {root}") from error


def _safe(root: Path, relative: str, allow_missing: bool = True) -> Path:
    normalized = relative.replace("\\", "/")
    parts = normalized.split("/")
    if ("\x00" in relative or PureWindowsPath(relative).drive or normalized.startswith("/")
            or ".." in parts):
        raise DiscoveryError(f"Unsafe relative path: {relative!r}")
    current = root
    try:
        for part in parts:
            if part in ("", "."):
                continue
            if current.exists() and not current.is_dir():
                raise DiscoveryError(f"Not a directory: {current}")
            matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()] if current.exists() else []
            if len(matches) > 1:
                raise DiscoveryError(f"Case-colliding path: {current / part}")
            current = matches[0] if matches else current / part
            if current.is_symlink():
                raise DiscoveryError(f"Symlink inside game root: {current}")
            if not matches and not allow_missing:
                raise DiscoveryError(f"Missing path: {current}")
        return current
    except OSError as error:
        raise DiscoveryError(f"Cannot read path: {current}") from error


def safe_path(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    """Resolve a relative Windows name, rejecting links, traversal and collisions.

    Absolute names (including drive-relative/UNC) are forbidden. Missing children
    are permitted by default; no directories or files are ever created.
    """
    return _safe(_root(root), relative, allow_missing)


def _files(root: Path) -> list[Path]:
    """Walk only root, refusing links/collisions rather than following aliases."""
    pending, files = [root], []
    try:
        while pending:
            folder = pending.pop()
            names = set()
            for path in folder.iterdir():
                name = path.name.casefold()
                if name in names:
                    raise DiscoveryError(f"Case-colliding path: {path}")
                names.add(name)
                if path.is_symlink():
                    raise DiscoveryError(f"Symlink inside game root: {path}")
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    files.append(path)
        return files
    except OSError as error:
        raise DiscoveryError(f"Cannot scan game root: {root}") from error


def _choose_ini(anchors: list[Path], directory: Path | None = None) -> Path | None:
    if not anchors:
        return None
    if len(anchors) == 1:
        return anchors[0]
    associated = [p for p in anchors if p.parent == directory]
    if len(associated) == 1:
        return associated[0]
    raise DiscoveryError("Multiple OptiScaler.ini anchors; no unique colocated renderer")


def _under(boundary: Path, value: str) -> str | None:
    # Compare components, not casefolded string lengths (ß folds to two chars).
    path = PurePosixPath(value.replace("\\", "/"))
    parts, prefix = path.parts, boundary.parts
    if (path.is_absolute() and len(parts) >= len(prefix)
            and all(a.casefold() == b.casefold() for a, b in zip(parts, prefix))):
        return "/".join(parts[len(prefix):]) or "."
    return None


def _local_path(root: Path, value: str) -> Path:
    value = value.replace("\\", "/")
    if value.startswith("/"):
        relative = _under(root, value)
        if relative is None:
            raise DiscoveryError(f"Path outside selected game root: {value}")
        value = relative
    return _safe(root, value, allow_missing=False)


def _canonical_argument(root: Path, alias: Path, value: str) -> str:
    """Map only the caller's selected root alias; never resolve argv paths."""
    relative = _under(alias, value)
    return str(root / relative) if relative is not None else value


def discover_ini(root: Path, renderer: Path | None = None) -> Path | None:
    """Find INI recursively; multiple anchors require exact colocation.

    renderer may be an existing executable or directory inside root. A unique
    anchor always wins, even if the caller supplied misleading launch context.
    """
    alias = Path(root).absolute()
    root = _root(root)
    anchors = [p for p in _files(root) if p.name.casefold() == "optiscaler.ini"]
    context = _local_path(root, _canonical_argument(root, alias, str(renderer))) if len(anchors) > 1 and renderer is not None else None
    directory = context if context is None or context.is_dir() else context.parent
    return _choose_ini(anchors, directory)


def _context_path(root: Path, value: str) -> Path | None:
    """Recognize local argv executables without examining external files."""
    value = value.replace("\\", "/")
    if not value.casefold().endswith(".exe") or value.startswith("-"):
        return None
    if value.startswith("/"):
        relative = _under(root, value)
        if relative is None:
            return None
        value = relative
    elif PureWindowsPath(value).drive:
        return None
    path = _safe(root, value)
    return path if path.is_file() else None


def _shipping_stem(path: Path) -> str | None:
    match = re.fullmatch(r"(.+)-(?:Win64|WinGDK)-Shipping\.exe", path.name, re.IGNORECASE)
    return match[1].casefold() if match else None


def _shipping_targets(bootstrap: Path, candidates: list[Path]) -> list[Path]:
    # A nested AMD64 shipping executable sharing the launcher stem is stronger
    # than the bootstrap's own graphics imports. Never rank by size or order.
    return [p for p in candidates if _shipping_stem(p) == bootstrap.stem.casefold()
            and bootstrap.parent in p.parents and p.parent != bootstrap.parent]


def _renderer(root: Path, files: list[Path], argv: list[str], executable: str | None) -> Path:
    override = _local_path(root, executable) if executable is not None else None
    if override is not None and (override.suffix.casefold() != ".exe" or _pe_imports(override) is None):
        raise DiscoveryError("Executable override is not a valid AMD64 executable")
    candidates, valid = [], []
    for path in files:
        if path.suffix.casefold() == ".exe":
            imports = _pe_imports(path)
            if imports is not None:
                valid.append(path)
                if path == override or imports & _GRAPHICS_DLLS or _shipping_stem(path):
                    candidates.append(path)
    renderers = [p for p in candidates if not _shipping_targets(p, candidates)]
    context = override if override is not None else next(
        (path for value in argv if (path := _context_path(root, value)) in valid), None)
    targets = _shipping_targets(context, renderers) if context is not None else []
    if len(targets) == 1:
        return targets[0]
    if context is not None and context in renderers:
        nested = [p for p in renderers if p != context and p.parent != context.parent
                  and context.parent in p.parents]
        if nested and override is None:
            raise DiscoveryError("Launch executable may be a bootstrap; nested renderers are unassociated")
        return context
    if len(renderers) == 1:
        return renderers[0]
    if not renderers and len(valid) == 1 and context == valid[0]:
        return valid[0]  # Unique launched AMD64 game may load graphics dynamically.
    raise DiscoveryError("No unique AMD64 rendering executable found")


def discover_game_directory(root: Path, argv: list[str], *, executable: str | None = None) -> Path:
    """Return the installation directory, never an executable path.

    A unique existing INI wins over argv and executable. Otherwise normal
    graphics-import/Unreal shipping metadata selects candidates; the first
    local, metadata-valid AMD64 argv executable supplies launch context. External
    argv tools are ignored, never inspected. A sole launched AMD64 executable
    also works without static graphics imports. Ambiguity raises DiscoveryError.

    executable is an optional advanced, root-contained AMD64 override for
    disambiguation/dynamic loading, not ordinary setup. Known paired Unreal
    bootstraps still redirect to their nested shipping executable.
    """
    alias = Path(root).absolute()
    root = _root(root)
    argv = [_canonical_argument(root, alias, value) for value in argv]
    if executable is not None:
        executable = _canonical_argument(root, alias, executable)
    files = _files(root)
    anchors = [p for p in files if p.name.casefold() == "optiscaler.ini"]
    if len(anchors) == 1:
        return anchors[0].parent
    renderer = _renderer(root, files, argv, executable)
    ini = _choose_ini(anchors, renderer.parent)
    return ini.parent if ini is not None else renderer.parent
