import os
import decky
import asyncio
from pathlib import Path


MAX_LOG_BYTES = 1024 * 1024


def _logs_directory():
    return Path(decky.DECKY_USER_HOME) / ".dlor" / "logs"


def _read_log_file(path):
    root = _logs_directory().resolve()
    selected = Path(path).resolve()
    if not selected.is_relative_to(root) or selected.suffix.lower() != ".log":
        raise ValueError("Choose a .log file inside ~/.dlor/logs.")
    if not selected.is_file():
        raise FileNotFoundError("This log no longer exists or is not a regular file.")

    with selected.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, size - MAX_LOG_BYTES))
        content = stream.read(MAX_LOG_BYTES).decode("utf-8", errors="replace")
    return {
        "path": str(selected.relative_to(root)),
        "content": content,
        "truncated": size > MAX_LOG_BYTES,
    }


class Plugin:
    async def get_logs_directory(self):
        directory = _logs_directory()
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        return str(directory)

    async def read_log_file(self, path: str):
        return await asyncio.to_thread(_read_log_file, path)

    async def _main(self):
        self.loop = asyncio.get_event_loop()

    async def _unload(self):
        pass

    async def _uninstall(self):
        pass

    async def _migration(self):
        pass
