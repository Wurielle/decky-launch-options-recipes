#!/usr/bin/env python3
"""Resolve explicit environment overrides for existing OptiScaler INI settings.

Source: https://github.com/xXJSONDeruloXx/Decky-Framegen/blob/main/defaults/assets/update-optiscaler-config.py
The installer reuses the pure resolver; it never invokes an unmanaged second write.

BSD 3-Clause License (upstream attribution retained)
Copyright (c) 2024, Kurt Himebauch (JSON Derulo)
Original Copyright (c) 2022-2024, Steam Deck Homebrew
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import os
import re
from pathlib import Path
import stat
import tempfile


def update_optiscaler_config(file_path):
    """Standalone compatibility entrypoint; installer uses pure functions only."""
    path = Path(file_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Configuration must be an existing regular file")
    data = path.read_bytes()
    overrides = resolve_overrides(data)
    updated = render_overrides(data, overrides)
    if updated == data:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".optiscaler-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(updated)
            output.flush()
            os.fchmod(output.fileno(), stat.S_IMODE(path.stat().st_mode))
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    for section, key in overrides:
        print("Updated: [" + section + "] " + key)


def entries(data):
    """Return exact, case-sensitive existing settings and their physical lines."""
    result = {}
    section = None
    sections = set()
    for index, line in enumerate(data.decode("utf-8-sig").splitlines(keepends=True)):
        header = re.match(r"^\s*\[([^]]+)\]", line)
        if header:
            section = header[1]
            if section in sections:
                raise ValueError("Duplicate INI section")
            sections.add(section)
        elif section is not None:
            match = re.match(r"^([^;#=\s][^=]*?)\s*=([^\r\n]*)(\r?\n)?$", line.lstrip(" \t"))
            if match:
                key = (section, match[1].strip())
                if key in result:
                    raise ValueError("Duplicate INI key")
                result[key] = {"index": index, "value": match[2], "line": line}
    return result


def resolve_overrides(data, environ=None):
    environ = os.environ if environ is None else environ
    indexed = entries(data)
    normalize = lambda name: name.replace("-", "").replace(".", "")
    candidates = {}
    occurrences = {}
    for section, key in indexed:
        occurrences[key] = occurrences.get(key, 0) + 1
        for section_name in {section, normalize(section)}:
            for prefix, priority in (("OptiScaler_", 3), ("", 2)):
                candidates.setdefault(prefix + section_name + "_" + key, set()).add(((section, key), priority))
    for section, key in indexed:
        if occurrences[key] == 1:
            candidates.setdefault(key, set()).add(((section, key), 1))
    selected = {}
    for name, choices in candidates.items():
        if name not in environ:
            continue
        if len({key for key, priority in choices}) != 1:
            raise ValueError("Ambiguous environment setting: " + name)
        key, priority = max(choices, key=lambda item: item[1])
        value = environ[name]
        if any(character in value for character in "\r\n\0"):
            raise ValueError("Invalid single-line INI override: " + name)
        previous = selected.get(key)
        if previous is None or priority > previous[0]:
            selected[key] = (priority, value)
        elif priority == previous[0] and value != previous[1]:
            raise ValueError("Ambiguous environment aliases for: " + name)
    return {key: value for key, (priority, value) in selected.items()}


def render_overrides(data, overrides):
    indexed = entries(data)
    lines = data.decode("utf-8-sig").splitlines(keepends=True)
    for key, value in overrides.items():
        if any(character in value for character in "\r\n\0"):
            raise ValueError("Invalid single-line INI override")
        entry = indexed[key]
        line = entry["line"]
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        lines[entry["index"]] = line.split("=", 1)[0] + "=" + value + ending
    return (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + "".join(lines).encode()


def restore_overrides(data, settings):
    indexed = entries(data)
    lines = data.decode("utf-8-sig").splitlines(keepends=True)
    for entry in settings.values():
        key = (entry["section"], entry["key"])
        current = indexed.get(key)
        if current and current["value"] == entry["after"]:
            lines[current["index"]] = entry["before_line"]
    return (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + "".join(lines).encode()
