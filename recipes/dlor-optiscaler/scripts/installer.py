"""Recipe-local file ownership. Payloads are verified before reaching this module."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import configparser
import posixpath
import re
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import struct


class InstallerError(ValueError):
    """Installation refused without taking ownership of unknown content."""


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_target(root, relative):
    relative = PurePosixPath(relative)
    if relative.is_absolute() or not relative.parts or any(part in ("..", ".") or "\\" in part or ":" in part for part in relative.parts):
        raise InstallerError("Unsafe installation path")
    current = root
    for part in relative.parts:
        if current.exists():
            matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
            if len(matches) > 1:
                raise InstallerError("Ambiguous Windows filename")
            current = matches[0] if matches else current / part
        else:
            current = current / part
        if current.is_symlink():
            raise InstallerError("Symlink inside installation directory")
    return current


def atomic_write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".dlor-" + secrets.token_hex(12))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), mode)
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def remove_owned(path):
    try:
        path.unlink()
    except FileNotFoundError:
        return
    descriptor = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def game_state(game, state_home, *, asi_only=False, recover=True):
    game = Path(game).resolve(strict=True)
    if not game.is_dir():
        raise InstallerError("Game root is not a directory")
    state_home = Path(state_home)
    state_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state_home.is_symlink():
        raise InstallerError("State directory is a symlink")
    directory = safe_target(state_home, hashlib.sha256(os.fsencode(game)).hexdigest())
    directory.mkdir(exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    lock = os.open(directory / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        journal = safe_target(directory, "state.json")
        state = json.loads(journal.read_text()) if journal.exists() else {"version": 1, "root": str(game), "files": {}}
        if state.get("version") != 1 or state.get("root") != str(game) or not isinstance(state.get("files"), dict):
            raise InstallerError("Invalid installation journal")
        if asi_only:
            # Ownership is not permission to keep mutating retired settings.
            # Do this before recovery as well as before ON/OFF processing.
            transaction = state.get("transaction")
            snapshots = [state] + ([transaction["before"]] if transaction else [])
            legacy = {name for snapshot in snapshots for name, record in snapshot["files"].items()
                      if Path(name).name.casefold() == "optiscaler.ini"
                      and any(key.casefold() != "plugins.loadasiplugins" and not entry.get("environment")
                              for key, entry in record.get("settings", {}).items())}
            ini_changes = transaction and any(Path(name).name.casefold() == "optiscaler.ini" for name in transaction["changes"])
            if transaction and ini_changes and (
                (not transaction.get("asi_only") and not transaction.get("ini_policy"))
                or legacy.intersection(transaction["changes"])
            ):
                raise InstallerError("Interrupted legacy INI transaction requires review; preserving current configuration and backups")
            if transaction and ini_changes and transaction.get("ini_policy"):
                validate_ini_transaction(directory, transaction)
            changed = False
            for snapshot in snapshots:
                for name, record in snapshot["files"].items():
                    if name in legacy:
                        record["settings"] = {key: value for key, value in record.get("settings", {}).items()
                                              if key.casefold() == "plugins.loadasiplugins" or value.get("environment")}
                        # Sticky: an exact old installed hash must never grant
                        # whole-file restoration/removal of relinquished bytes.
                        record["foreign_edits"] = True
                        changed = True
            if changed:
                save_state(journal, state)
        if recover and state.get("transaction"):
            recover_transaction(game, directory, journal, state)
        yield game, directory, journal, state
    finally:
        os.close(lock)


def save_state(path, state):
    atomic_write(path, (json.dumps(state, indent=2) + "\n").encode())


def validate_ini_transaction(directory, transaction):
    """Replay the narrow INI operations before allowing any rollback writes."""
    from update_optiscaler_config import render_overrides
    for name, change in transaction["changes"].items():
        if Path(name).name.casefold() != "optiscaler.ini":
            continue
        policy = transaction["ini_policy"].get(name)
        if not policy or policy.get("version") != 1:
            raise InstallerError("Interrupted INI transaction has no valid setting permissions")
        configuration = {(s, k): v for s, k, v in policy["configuration"]}
        explicit = {tuple(key) for key in policy["explicit"]}
        if not explicit.issubset(configuration) or any(
            key not in explicit and (key[0].casefold(), key[1].casefold()) != ("plugins", "loadasiplugins")
            for key in configuration
        ):
            raise InstallerError("Interrupted INI transaction exceeds setting permissions")
        previous_settings = transaction["before"]["files"].get(name, {}).get("settings", {})
        for label, entry in policy["retired"].items():
            if not entry.get("environment") or previous_settings.get(label) != entry:
                raise InstallerError("Interrupted INI transaction has invalid retired ownership")
        if change["previous"] is None:
            continue  # New recipe-created file: rollback only removes that file.
        backup = safe_target(directory, "backups/" + change["previous"])
        if digest(backup) != change["previous"]:
            raise InstallerError("Rollback backup failed verification")
        data = restore_settings(backup.read_bytes(), policy["retired"])
        data = edit_ini(data, {key: value for key, value in configuration.items() if key not in explicit})
        data = render_overrides(data, {key: configuration[key] for key in explicit})
        if hashlib.sha256(data).hexdigest() != change["next"]:
            raise InstallerError("Interrupted INI transaction exceeds recorded setting permissions")


def recover_transaction(root, directory, journal, state):
    transaction = state["transaction"]
    for relative, change in transaction["changes"].items():
        path = safe_target(root, relative)
        current = digest(path) if path.exists() else None
        if current == change["previous"]:
            continue
        if current not in (None, change["next"]):
            raise InstallerError("Interrupted installation conflicts with a changed file")
        if change["previous"] is None:
            remove_owned(path)
        else:
            backup = safe_target(directory, "backups/" + change["previous"])
            if digest(backup) != change["previous"]:
                raise InstallerError("Rollback backup failed verification")
            atomic_write(path, backup.read_bytes(), change["mode"])
    previous = transaction["before"]
    save_state(journal, previous)
    state.clear()
    state.update(previous)


def split_ini_comment(value):
    """Separate whitespace-delimited inline comments, not quoted path bytes."""
    quoted = False
    for index, character in enumerate(value):
        if character == '"':
            quoted = not quoted
        elif not quoted and character in ";#" and index and value[index - 1].isspace():
            start = index
            while start and value[start - 1].isspace():
                start -= 1
            return value[:start], value[start:]
    return value, ""


def split_ini_annotation(section, key, value):
    # SimpleIni treats unquoted paths as the entire line, including ; and #.
    # Only explicitly quoted human paths distinguish an inline annotation.
    path = (section.casefold() == "libraries" and key.casefold().endswith("path")) or (section.casefold() == "plugins" and key.casefold() == "path")
    if path and not value.lstrip().startswith('"'):
        return value, ""
    return split_ini_comment(value)


def edit_ini(data, settings, *, restoring=False):
    """Change only requested lines; preserve comments, unrelated keys and CRLF."""
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    for (section, key), value in settings.items():
        entry = value if restoring else None
        if entry is not None:
            value = entry.get("before_raw", entry["before"])
        if any(c in section + key + str(value) for c in "\r\n\0"):
            raise InstallerError("Invalid configuration value")

        section_start = None
        end = len(lines)
        found = []
        current = ""
        for index, line in enumerate(lines):
            header = re.match(r"^\s*\[([^]]+)\]", line)
            if header:
                if current.casefold() == section.casefold() and section_start is not None:
                    end = min(end, index)
                current = header.group(1)
                if current.casefold() == section.casefold():
                    if section_start is not None:
                        raise InstallerError("Duplicate managed INI section")
                    section_start = index
            if current.casefold() == section.casefold():
                match = re.match(r"^(\s*" + re.escape(key) + r"\s*=\s*)([^\r\n]*)(\r?\n)?$", line, re.I)
                if match:
                    found.append((index, match))
        if len(found) > 1:
            raise InstallerError("Duplicate managed INI key")
        if found:
            index, match = found[0]
            if entry is not None and entry.get("comment") and index and lines[index - 1] == entry["comment"] + newline:
                del lines[index - 1]
                index -= 1
            if value is None:
                del lines[index]
            else:
                _, suffix = split_ini_annotation(section, key, match.group(2))
                lines[index] = match.group(1) + str(value) + (match.group(3) or newline)
                if suffix:
                    lines.insert(index, suffix + newline)
        elif value is not None:
            if section_start is None:
                if lines and not lines[-1].endswith(("\r", "\n")):
                    lines[-1] += newline
                lines.extend(["[" + section + "]" + newline, key + "=" + str(value) + newline])
            else:
                if end and not lines[end - 1].endswith(("\r", "\n")):
                    lines[end - 1] += newline
                lines.insert(end, key + "=" + str(value) + newline)
    return (b"\xef\xbb\xbf" if bom else b"") + "".join(lines).encode("utf-8")


def restore_settings(data, settings):
    environment = {name: entry for name, entry in settings.items() if entry.get("environment")}
    if environment:
        from update_optiscaler_config import restore_overrides
        data = restore_overrides(data, environment)
    changes = {}
    for name, entry in settings.items():
        if entry.get("environment"):
            continue
        section, key = name.split(".", 1)
        if ini_value(data, section, key, None) == entry["after"]:
            changes[(section, key)] = entry
    return edit_ini(data, changes, restoring=True)


def apply_install(game, target, files, state_home, *, proxy="dxgi", configuration=None, relative_to_root=False, components=None, asi_only=False, explicit_overrides=None, expected_configuration_data=None, require_installed=False):
    explicit_overrides = explicit_overrides or {}
    if any(key not in (configuration or {}) or (configuration or {})[key] != value for key, value in explicit_overrides.items()):
        raise InstallerError("Explicit override does not match requested configuration")
    if asi_only and any((section.casefold(), key.casefold()) != ("plugins", "loadasiplugins") and (section, key) not in explicit_overrides for section, key in (configuration or {})):
        raise InstallerError("Only Plugins.LoadAsiPlugins may be configured")
    with game_state(game, state_home, asi_only=asi_only) as (root, directory, journal, state):
        relative = Path(target).relative_to(root)
        if require_installed:
            path = safe_target(root, (relative / (proxy + ".dll")).as_posix())
            proxy_key = path.relative_to(root).as_posix()
            record = state["files"].get(proxy_key)
            if not record or not path.is_file() or digest(path) != record["installed"]:
                raise InstallerError("OptiScaler is no longer installed unchanged; refusing upgrade")
        if state.get("target", relative.as_posix()) != relative.as_posix() and state["files"]:
            raise InstallerError("Managed installation target changed")
        base = Path() if relative_to_root else relative
        plan = [(safe_target(root, (base / name).as_posix()), Path(source)) for name, source in files.items()]
        managed_settings = None
        retired_environment = {}
        ini = None
        if configuration is not None:
            ini = safe_target(root, (relative / "OptiScaler.ini").as_posix())
            ini_source = next((source for destination, source in plan if destination == ini), None)
            if ini.exists() or ini_source is not None:
                data = ini.read_bytes() if ini.exists() else ini_source.read_bytes()
                key = ini.relative_to(root).as_posix()
                managed_settings = deepcopy(state["files"].get(key, {}).get("settings", {}))
                requested = {section + "." + name for section, name in configuration}
                old = {name: entry for name, entry in managed_settings.items()
                       if name not in requested or (entry.get("environment") and (entry["section"], entry["key"]) not in explicit_overrides)}
                retired_environment = {name: entry for name, entry in old.items() if entry.get("environment")}
                data = restore_settings(data, old)
                if expected_configuration_data is not None:
                    from update_optiscaler_config import render_overrides
                    if render_overrides(data, explicit_overrides) != expected_configuration_data:
                        raise InstallerError("Effective INI configuration changed after placement planning")
                for name in old:
                    del managed_settings[name]
                for (section, name), value in configuration.items():
                    label = section + "." + name
                    if (section, name) in explicit_overrides:
                        from update_optiscaler_config import entries
                        current = entries(data)[(section, name)]
                        if label in managed_settings and current["value"] != managed_settings[label]["after"]:
                            # Active ENV is a fresh request. Retain the latest
                            # displaced overlay value, not an obsolete original.
                            del managed_settings[label]
                        if current["value"] != value:
                            if label not in managed_settings:
                                managed_settings[label] = {"environment": True, "section": section, "key": name, "before_line": current["line"]}
                            managed_settings[label]["after"] = value
                        continue
                    before = ini_value(data, section, name, None)
                    raw = ini_value(data, section, name, None, raw=True)
                    label = section + "." + name
                    if label in managed_settings and before != managed_settings[label]["after"]:
                        raise InstallerError("Managed INI setting was changed outside this recipe")
                    if before != value or raw != value:
                        if label not in managed_settings:
                            managed_settings[label] = {"before": before, "before_raw": raw, "comment": split_ini_annotation(section, name, raw)[1] if raw is not None else ""}
                        managed_settings[label]["after"] = value
                data = edit_ini(data, {key: value for key, value in configuration.items() if key not in explicit_overrides})
                if explicit_overrides:
                    from update_optiscaler_config import render_overrides
                    data = render_overrides(data, explicit_overrides)
                prepared = safe_target(directory, "prepared.ini")
                atomic_write(prepared, data)
                plan = [(destination, source) for destination, source in plan if destination != ini] + [(ini, prepared)]
        folded = [path.relative_to(root).as_posix().casefold() for path, source in plan]
        if len(set(folded)) != len(folded) or any(str(parent) in folded for key in folded for parent in PurePosixPath(key).parents if str(parent) != "."):
            raise InstallerError("Conflicting installation paths")
        for path, source in plan:
            if source.is_symlink() or not source.is_file() or (path.exists() and not path.is_file()):
                raise InstallerError("Installation payload must contain regular files")
            record = state["files"].get(path.relative_to(root).as_posix())
            if record and path.exists() and path.name.casefold() != "optiscaler.ini" and digest(path) not in (record["installed"], record.get("pending")):
                raise InstallerError("Owned file was changed outside this recipe")
        previous = deepcopy(state)
        desired = {path.relative_to(root).as_posix() for path, source in plan}
        stale = [(key, safe_target(root, key), record) for key, record in state["files"].items() if key not in desired]
        changes = {}
        for path, source in plan:
            current = digest(path) if path.exists() else None
            wanted = digest(source)
            if (current is not None and path.name.casefold() == "optiscaler.ini" and configuration is None) or current == wanted:
                continue
            mode = stat.S_IMODE(path.stat().st_mode) if current else 0o600
            if current:
                backup = safe_target(directory, "backups/" + current)
                atomic_write(backup, path.read_bytes())
                if digest(backup) != current:
                    raise InstallerError("File changed during rollback preparation")
            changes[path.relative_to(root).as_posix()] = {"previous": current, "next": wanted, "mode": mode}
        for key, path, record in stale:
            current = digest(path) if path.exists() else None
            if current not in (None, record["installed"], record.get("pending")):
                continue
            if current:
                backup = safe_target(directory, "backups/" + current)
                atomic_write(backup, path.read_bytes())
            if record["original"]:
                backup = safe_target(directory, "backups/" + record["original"])
                if digest(backup) != record["original"]:
                    raise InstallerError("Stale-file original backup failed verification")
            changes[key] = {"previous": current, "next": record["original"], "mode": stat.S_IMODE(path.stat().st_mode) if current else 0o600}
        ini_policy = {}
        if asi_only and ini is not None:
            ini_policy[ini.relative_to(root).as_posix()] = {
                "version": 1, "configuration": [[s, k, v] for (s, k), v in (configuration or {}).items()],
                "explicit": [list(key) for key in explicit_overrides], "retired": retired_environment,
            }
        state["transaction"] = {"before": previous, "changes": changes,
                                "asi_only": asi_only and not explicit_overrides and not retired_environment,
                                "ini_policy": ini_policy}
        state["target"] = relative.as_posix()
        state["proxy"] = proxy
        if components is not None:
            state["components"] = components
        save_state(journal, state)
        try:
            for path, source in plan:
                key = path.relative_to(root).as_posix()
                current = digest(path) if path.exists() else None
                if current is not None and path.name.casefold() == "optiscaler.ini" and configuration is None:
                    continue  # Keep existing game-specific settings, including user edits.
                wanted = digest(source)
                record = state["files"].get(key)
                if record:
                    if path.name.casefold() == "optiscaler.ini" and current not in (None, record["installed"], record.get("pending")):
                        # Rebasing owned settings must never acquire the user's other bytes.
                        record["foreign_edits"] = True
                    if current not in (None, record["installed"], record.get("pending")) and not (path.name.casefold() == "optiscaler.ini" and configuration is not None):
                        raise InstallerError("Owned file was changed outside this recipe")
                    if current == wanted and record["installed"] == wanted:
                        continue
                    record["pending"] = wanted
                else:
                    if current == wanted:
                        continue  # Equal pre-existing bytes do not grant removal ownership.
                    record = {"installed": wanted, "original": current}
                    if current:
                        backup = safe_target(directory, "backups/" + current)
                        atomic_write(backup, path.read_bytes())
                        record["original_mode"] = stat.S_IMODE(path.stat().st_mode)
                    state["files"][key] = record
                save_state(journal, state)
                mode = stat.S_IMODE(path.stat().st_mode) if path == ini and current is not None else 0o600
                atomic_write(path, Path(source).read_bytes(), mode)
                record["installed"] = wanted
                record.pop("pending", None)
                save_state(journal, state)
            for key, path, record in stale:
                current = digest(path) if path.exists() else None
                if current not in (None, record["installed"], record.get("pending")):
                    print("Preserving externally changed stale file:", key)
                    continue
                if record["original"]:
                    backup = safe_target(directory, "backups/" + record["original"])
                    atomic_write(path, backup.read_bytes(), record.get("original_mode", 0o600))
                else:
                    remove_owned(path)
                del state["files"][key]
                save_state(journal, state)
            if managed_settings is not None and ini is not None:
                key = ini.relative_to(root).as_posix()
                if key in state["files"]:
                    state["files"][key]["settings"] = managed_settings
            finished = deepcopy(state)
            finished.pop("transaction")
            save_state(journal, finished)
            state.clear()
            state.update(finished)
        except BaseException:
            if state.get("transaction"):
                recover_transaction(root, directory, journal, state)
            raise
        return {"proxy": proxy, "target": str(target)}


def uninstall(game, state_home, *, asi_only=False):
    with game_state(game, state_home, asi_only=asi_only) as (root, directory, journal, state):
        preserved = []
        for relative, record in list(state["files"].items()):
            path = safe_target(root, relative)
            current = digest(path) if path.exists() else None
            if current is not None and current == record["original"]:
                pass  # A prior uninstall durably restored bytes before its journal save.
            elif current is not None and (
                record.get("foreign_edits")
                or current not in (record["installed"], record.get("pending"))
                or (asi_only and path.name.casefold() == "optiscaler.ini" and record["original"] is not None)
            ):
                preserved.append(relative)
                if path.name.casefold() == "optiscaler.ini":
                    atomic_write(path, restore_settings(path.read_bytes(), record.get("settings", {})), stat.S_IMODE(path.stat().st_mode))
                elif record["original"] is not None:
                    continue  # Keep the original backup and retryable ownership.
            elif record["original"] is not None:
                backup = safe_target(directory, "backups/" + record["original"])
                if digest(backup) != record["original"]:
                    raise InstallerError("Original backup failed verification")
                atomic_write(path, backup.read_bytes(), record.get("original_mode", 0o600))
            elif path.exists():
                remove_owned(path)
            del state["files"][relative]
            save_state(journal, state)
        return {"preserved": preserved}


def identifies_optiscaler(path):
    # Upstream setup renames the main DLL. Read its PE version resource instead
    # of requiring the original filename. This identifies a borrowed install;
    # it is neither a signature/authenticity check nor file-removal ownership.
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        return False
    image = path.read_bytes()
    try:
        if image[:2] != b"MZ":
            return False
        pe = struct.unpack_from("<I", image, 60)[0]
        if image[pe:pe + 4] != b"PE\0\0":
            return False
        sections = struct.unpack_from("<H", image, pe + 6)[0]
        if not 1 <= sections <= 96:
            return False
        optional_size = struct.unpack_from("<H", image, pe + 20)[0]
        optional = pe + 24
        magic = struct.unpack_from("<H", image, optional)[0]
        directories = {0x10b: 96, 0x20b: 112}.get(magic)
        if directories is None or optional_size < directories + 24:
            return False
        rva, size = struct.unpack_from("<II", image, optional + directories + 16)

        def offset(address, length):
            for index in range(sections):
                _, start, raw_size, raw = struct.unpack_from("<IIII", image, optional + optional_size + index * 40 + 8)
                if start <= address and address + length <= start + raw_size and raw + address - start + length <= len(image):
                    return raw + address - start
            raise ValueError("Unmapped PE resource")

        root = offset(rva, size)

        def entries(relative):
            if relative < 0 or relative + 16 > size:
                raise ValueError("Invalid PE resource directory")
            named, ids = struct.unpack_from("<HH", image, root + relative + 12)
            if relative + 16 + (named + ids) * 8 > size:
                raise ValueError("Truncated PE resource directory")
            return [struct.unpack_from("<II", image, root + relative + 16 + index * 8) for index in range(named + ids)]

        def version_block(version, begin, limit):
            if begin + 6 > limit:
                raise ValueError("Truncated version block")
            length, value_length, text = struct.unpack_from("<HHH", version, begin)
            end = begin + length
            if length < 8 or end > limit or text not in (0, 1):
                raise ValueError("Invalid version block bounds")
            cursor = begin + 6
            while cursor + 2 <= end and version[cursor:cursor + 2] != b"\0\0":
                cursor += 2
            if cursor + 2 > end:
                raise ValueError("Unterminated version key")
            name = version[begin + 6:cursor].decode("utf-16le")
            value = (cursor + 2 + 3) & ~3
            value_end = value + value_length * (2 if text else 1)
            if value_end > end:
                raise ValueError("Version value exceeds declared block")
            return name, text, version[value:value_end], (value_end + 3) & ~3, end

        def version_children(version, parent):
            cursor, end = parent[3:]
            children = []
            while cursor < end:
                child = version_block(version, cursor, end)
                children.append(child)
                cursor = (child[4] + 3) & ~3
            return children

        for kind, types in entries(0):
            if kind != 16 or not types & 0x80000000:
                continue  # Only RT_VERSION, never coincidental strings elsewhere.
            for _, names in entries(types & 0x7fffffff):
                if not names & 0x80000000:
                    continue
                for _, leaf in entries(names & 0x7fffffff):
                    if leaf & 0x80000000 or leaf + 16 > size:
                        continue
                    address, length = struct.unpack_from("<II", image, root + leaf)
                    begin = offset(address, length)
                    if not root <= begin <= begin + length <= root + size:
                        continue
                    version = image[begin:begin + length]
                    info = version_block(version, 0, len(version))
                    if info[0] != "VS_VERSION_INFO" or info[1] != 0:
                        continue
                    # Walk only declared children, never scan values or bytes
                    # outside the root/StringFileInfo/StringTable boundaries.
                    for strings in version_children(version, info):
                        if strings[:3] != ("StringFileInfo", 1, b""):
                            continue
                        for table in version_children(version, strings):
                            if not re.fullmatch(r"[0-9a-fA-F]{8}", table[0]) or table[1:3] != (1, b""):
                                continue
                            for record in version_children(version, table):
                                if record[0:2] == ("OriginalFilename", 1):
                                    if record[2].decode("utf-16le").rstrip("\0").casefold() == "optiscaler.dll":
                                        return True
    except (struct.error, ValueError, UnicodeError):
        pass
    return False



PROXIES = ("dxgi", "winmm", "version", "d3d12", "dbghelp", "wininet", "winhttp")
LIBRARY_KEYS = {
    "fakenvapi.dll": "NvapiPath",
    "amd_fidelityfx_dx12.dll": "FfxDx12Path",
    "amd_fidelityfx_loader_dx12.dll": "FfxDx12Path",
    "amd_fidelityfx_upscaler_dx12.dll": "FfxDx12SRPath",
    "amd_fidelityfx_framegeneration_dx12.dll": "FfxDx12FGPath",
    "amd_fidelityfx_vk.dll": "FfxVkPath",
    "libxess.dll": "XeSSPath",
    "libxess_dx11.dll": "XeSSDx11Path",
}


def ini_value(data, section, key, default="auto", *, raw=False):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = lambda option: option
    parser.read_string(data.decode("utf-8-sig"))
    sections = [name for name in parser.sections() if name.casefold() == section.casefold()]
    if len(sections) > 1:
        raise InstallerError("Ambiguous configuration section")
    if sections and not parser.has_option(sections[0], key):
        matches = [name for name in parser.options(sections[0]) if name.casefold() == key.casefold()]
        if len(matches) > 1:
            raise InstallerError("Ambiguous configuration key")
        key = matches[0] if matches else key
    value = parser.get(sections[0], key, fallback=default) if sections else default
    if raw:
        # ConfigParser trims trailing bytes that must survive ownership rollback.
        current = ""
        for line in data.decode("utf-8-sig").splitlines():
            header = re.match(r"^\s*\[([^]]+)\]", line)
            if header:
                current = header.group(1)
            elif current.casefold() == section.casefold():
                match = re.match(r"^\s*" + re.escape(key) + r"\s*=\s*([^\r\n]*)$", line, re.I)
                if match:
                    return match.group(1)
        return default
    return split_ini_annotation(section, key, value)[0].strip().strip('"') if value is not None else None


def configured_path(root, base, value):
    value = value.replace("\\", "/")
    if value.casefold().startswith("z:/"):
        value = value[2:]
    if re.match(r"^[A-Za-z]:", value):
        raise InstallerError("Configured Windows drive cannot be resolved inside this game")
    if value.startswith("/"):
        relative = Path(value).relative_to(root).as_posix()
    else:
        relative = posixpath.normpath((base.relative_to(root) / value).as_posix())
    return root if relative == "." else safe_target(root, relative)


def build_plan(game, target, core, *, plugins=None, proxy="dxgi", extra_libraries=None, configuration_data=None):
    """Map verified package trees using their INI/library contract, not game names."""
    game, target, core = Path(game).resolve(), Path(target), Path(core)
    anchors = [path for path in core.rglob("*") if path.name.casefold() == "optiscaler.ini" and path.is_file()]
    if len(anchors) != 1 or proxy not in PROXIES:
        raise InstallerError("Ambiguous OptiScaler package or unsupported proxy")
    base = anchors[0].parent
    main = safe_target(base, "OptiScaler.dll")
    if not main.is_file():
        raise InstallerError("Verified archive has no OptiScaler injector")
    installed_ini = safe_target(game, (target.relative_to(game) / "OptiScaler.ini").as_posix())
    data = configuration_data if configuration_data is not None else (installed_ini.read_bytes() if installed_ini.exists() else anchors[0].read_bytes())
    def path_value(section, key):
        raw = ini_value(data, section, key, raw=True)
        if raw is not None and raw.lstrip().startswith('"'):
            # Native path consumers retain quotes; do not silently normalize.
            raise InstallerError("Quoted configured path cannot be honored without rewriting the INI")
        return ini_value(data, section, key)
    package_support = safe_target(base, "OptiScaler")
    if not package_support.is_dir():
        raise InstallerError("Nightly package is missing its OptiScaler supporting-library directory")
    configured = path_value("Libraries", "OptiDllPath")
    library = configured_path(game, target, "OptiScaler" if configured.casefold() == "auto" else configured)
    files = {}
    settings = {}
    def library_override(value, key):
        # LoadProxyLibrary tests per-library overrides against process CWD,
        # unlike the separate OptiDllPath contract.
        normalized = value.replace("\\", "/")
        base = target
        if not normalized.startswith("/") and not re.match(r"^[A-Za-z]:", normalized):
            cwd = Path.cwd()
            relative = cwd.relative_to(game).as_posix()
            base = game if relative == "." else safe_target(game, relative)
            if not base.is_dir():
                raise InstallerError("Relative library override requires an existing in-game launch directory")
        destination = configured_path(game, base, value)
        return destination

    def add(destination, source):
        relative = destination.relative_to(game).as_posix()
        checked = safe_target(game, relative)
        if any(name.casefold() == relative.casefold() for name in files):
            raise InstallerError("Package maps multiple files to one Windows path")
        files[checked.relative_to(game).as_posix()] = source
    for source in sorted(base.rglob("*")):
        if source.is_symlink():
            raise InstallerError("Symlink in prepared package")
        if not source.is_file():
            continue
        relative = source.relative_to(base)
        if source == main:
            destination = target / (proxy + ".dll")
        elif relative.parts[0].casefold() == "optiscaler":
            destination = library.joinpath(*relative.parts[1:])
        else:
            destination = target / relative
        key = LIBRARY_KEYS.get(source.name.casefold())
        override = path_value("Libraries", key) if key else "auto"
        if override.casefold() != "auto":
            destination = library_override(override, key)
            if destination.suffix.casefold() != ".dll" and not destination.is_file():
                destination /= source.name
        add(destination, source)
    for name, source in (extra_libraries or {}).items():
        destination = library / name
        key = LIBRARY_KEYS.get(name.casefold())
        override = path_value("Libraries", key) if key else "auto"
        if override.casefold() != "auto":
            destination = library_override(override, key)
            if destination.suffix.casefold() != ".dll" and not destination.is_file():
                destination /= name
        relative = safe_target(game, destination.relative_to(game).as_posix()).relative_to(game).as_posix()
        files[relative] = source
    if plugins:
        value = path_value("Plugins", "Path")
        plugin_directory = library / "plugins"
        if value.casefold() != "auto":
            # Custom PluginPath is consumed directly relative to process CWD.
            normalized = value.replace("\\", "/")
            base = target
            if not normalized.startswith("/") and not re.match(r"^[A-Za-z]:", normalized):
                relative = Path.cwd().relative_to(game).as_posix()
                base = game if relative == "." else safe_target(game, relative)
                if not base.is_dir():
                    raise InstallerError("Relative plugin path requires an existing in-game launch directory")
            plugin_directory = configured_path(game, base, value)
        for name, source in plugins.items():
            if Path(name).name != name or not name.casefold().endswith(".asi"):
                raise InstallerError("Unsupported plugin filename")
            add(plugin_directory / name, source)
        settings[("Plugins", "LoadAsiPlugins")] = "true"
    return {"files": files, "settings": settings, "proxy": proxy, "target": str(target)}


def package_inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise InstallerError("Unsafe prepared package entry")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = digest(path)
    return result


def cached_package(asset, cache):
    from artifacts import download_asset, extract_archive
    import shutil
    archive = download_asset(asset, cache)
    packages = safe_target(cache, "packages")
    packages.mkdir(exist_ok=True, mode=0o700)
    directory = safe_target(packages, asset["sha256"])
    receipt = safe_target(packages, asset["sha256"] + ".json")
    descriptor = os.open(packages / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if directory.is_dir() and receipt.is_file() and receipt.stat().st_size <= 4 * 1024 * 1024:
            try:
                record = json.loads(receipt.read_text())
                if record["sha256"] == asset["sha256"] and package_inventory(directory) == record["files"]:
                    return directory
            except (ValueError, KeyError, OSError):
                pass
        if directory.exists():
            shutil.rmtree(directory)
        extract_archive(archive, directory, cache=cache)
        save_state(receipt, {"sha256": asset["sha256"], "files": package_inventory(directory)})
        return directory
    finally:
        os.close(descriptor)


def choose_proxy(target, previous=None):
    found = []
    for proxy in PROXIES:
        path = safe_target(target, proxy + ".dll")
        if path.is_file() and identifies_optiscaler(path):
            found.append(proxy)
    if len(found) > 1:
        raise InstallerError("Multiple existing OptiScaler proxies")
    if found and found != ["dxgi"]:
        raise InstallerError("Existing injector uses a different proxy; uninstall it before switching")
    path = safe_target(target, "dxgi.dll")
    if path.exists() and not found and previous != "dxgi":
        raise InstallerError("DXGI proxy is occupied by another file")
    return "dxgi"


def optional_components(cache):
    from artifacts import resolve_asset, download_asset
    profile = os.environ.get("DLOR_OPTISCALER_FSR_PROFILE", "bundled")
    profiles = {
        "bundled": [],
        "rdna23-int8": [("opti-9-2-a", "amd_fidelityfx_upscaler_dx12.dll")],
        "rdna34-official-411": [("fsr-4-1-1", "amdxcffx64.dll")],
        "rdna2-valve-411": [("fsr-4-1-1-rdna2", "amdxcffx64.dll"), ("fsr-4-1-1-rdna2", "amdxc64.dll")],
    }
    if profile not in profiles:
        raise InstallerError("Unsupported FSR compatibility profile")
    plugins, libraries, settings, components = {}, {}, {}, []
    # Mandatory even when an older imported checkbox still exports "0".
    asset = resolve_asset("optiscaler/OptiPatcher", "stable", r"OptiPatcher(?:_v[0-9.]+)?\.asi", cache)
    plugins["OptiPatcher.asi"] = download_asset(asset, cache)
    components.append(asset)
    for tag, name in profiles[profile]:
        asset = resolve_asset("xXJSONDeruloXx/OptiScaler-Bleeding-Edge", "tag:" + tag, re.escape(name), cache)
        libraries[name] = download_asset(asset, cache)
        components.append(asset)
    if profile != "bundled":
        print("Explicit third-party FSR compatibility profile:", profile)
    return plugins, libraries, settings, components


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Install or uninstall recipe-owned OptiScaler files")
    parser.add_argument("action", choices=("install", "uninstall", "upgrade"))
    parser.add_argument("game")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--argv-file", type=Path)
    args = parser.parse_args(argv)
    if not args.game:
        raise InstallerError("Steam did not provide a game installation directory")
    root = Path(args.game).resolve(strict=True)
    home = Path.home().resolve(strict=True)
    state_home = home / ".dlor/state/dlor-optiscaler"
    if args.action == "uninstall":
        result = uninstall(root, state_home, asi_only=True)
        print("OptiScaler uninstall completed; changed external files preserved:", len(result["preserved"]))
        return 0
    if args.action == "upgrade":
        # Ordinary assignments are visible to both helpers in the stock runner.
        # Main ON already performs the fresh transaction; main OFF must win.
        if os.environ.get("DLOR_OPTISCALER_ACTION") in ("install", "uninstall"):
            return 0
        journal_path = state_home / hashlib.sha256(os.fsencode(root)).hexdigest() / "state.json"
        if not journal_path.exists() and not journal_path.is_symlink():
            from nightly import legacy_upgrade
            return legacy_upgrade(root)
        with game_state(root, state_home, asi_only=True) as (_, directory, journal, state):
            if not state["files"]:
                return 0
            path = safe_target(root, (Path(state.get("target", ".")) / "dxgi.dll").as_posix())
            proxy_key = path.relative_to(root).as_posix()
            record = state["files"].get(proxy_key)
            if not record or not path.is_file() or digest(path) != record["installed"]:
                raise InstallerError("Nightly upgrade requires an unchanged DLOR-owned proxy")
            if "DLOR_OPTISCALER_FSR_PROFILE" not in os.environ:
                tags = {component.get("tag") for component in state.get("components", [])
                        if component.get("repository") == "xXJSONDeruloXx/OptiScaler-Bleeding-Edge"}
                profiles = {"opti-9-2-a": "rdna23-int8", "fsr-4-1-1": "rdna34-official-411", "fsr-4-1-1-rdna2": "rdna2-valve-411"}
                selected = [profile for tag, profile in profiles.items() if tag in tags]
                if len(selected) > 1:
                    raise InstallerError("Ambiguous installed compatibility profile")
                if selected:
                    os.environ["DLOR_OPTISCALER_FSR_PROFILE"] = selected[0]
        os.environ["DLOR_OPTISCALER_LATEST"] = "1"
    from artifacts import resolve_asset
    from game_discovery import discover_game_directory
    game_argv = []
    if args.argv_file:
        if args.argv_file.stat().st_size > 16 * 1024 * 1024:
            raise InstallerError("Game argument handoff is too large")
        game_argv = json.loads(args.argv_file.read_text())
        if not isinstance(game_argv, list) or any(not isinstance(value, str) for value in game_argv):
            raise InstallerError("Invalid game argument handoff")
    with game_state(root, state_home, asi_only=True) as (_, directory, journal, state):
        previous = state.get("proxy")
        known = state.get("target") if state["files"] else None
        proxy_key = (Path(state.get("target", ".")) / (str(previous) + ".dll")).as_posix()
        if proxy_key not in state["files"]:
            previous = None
    target = (root if known == "." else safe_target(root, known)) if known is not None else discover_game_directory(root, game_argv, executable=os.environ.get("DLOR_OPTISCALER_EXECUTABLE"))
    proxy = choose_proxy(target, previous)
    cache = home / ".dlor/cache/dlor-optiscaler/artifacts"
    resolution = {"fresh": True} if os.environ.get("DLOR_OPTISCALER_LATEST") == "1" else {}
    asset = resolve_asset("optiscaler/OptiScaler-nightly", "nightly", r"(?i)(?!.*(?:debug|symbols|source)).*optiscaler.*\.7z", cache, **resolution)
    core = cached_package(asset, cache)
    plugins, libraries, settings, components = optional_components(cache)
    from update_optiscaler_config import resolve_overrides, render_overrides
    anchors = [path for path in core.rglob("*") if path.name.casefold() == "optiscaler.ini" and path.is_file()]
    if len(anchors) != 1:
        raise InstallerError("Ambiguous OptiScaler package")
    ini = safe_target(root, (target.relative_to(root) / "OptiScaler.ini").as_posix())
    data = ini.read_bytes() if ini.exists() else anchors[0].read_bytes()
    overrides = resolve_overrides(data)
    with game_state(root, state_home, asi_only=True) as (_, directory, journal, state):
        owned = state["files"].get(ini.relative_to(root).as_posix(), {}).get("settings", {})
        retired = {name: entry for name, entry in owned.items()
                   if entry.get("environment") and (entry["section"], entry["key"]) not in overrides}
        data = restore_settings(data, retired)
    effective = render_overrides(data, overrides)
    plan = build_plan(root, target, core, proxy=proxy, plugins=plugins, extra_libraries=libraries, configuration_data=effective)
    plan["settings"].update(settings)
    plan["settings"].update(overrides)
    result = apply_install(root, target, plan["files"], state_home, proxy=proxy, configuration=plan["settings"], relative_to_root=True, components=[asset, *components], asi_only=True, explicit_overrides=overrides, expected_configuration_data=effective, require_installed=args.action == "upgrade")
    if args.result:
        atomic_write(args.result, (json.dumps(result) + "\n").encode())
    print("OptiScaler installed:", asset["tag"], "proxy", proxy)
    return 0
