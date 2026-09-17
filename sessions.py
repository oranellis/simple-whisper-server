"""Recording sessions: persistent metadata, listing, renaming, and transcript
accumulation across multiple start/stop recordings (segments)."""

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from recording import SessionRecording


class SessionNotFound(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _default_name():
    return "Session " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class SessionStore:
    """Manages one directory per session under `directory`, each holding a
    meta.json (name, language, accumulated transcript) and a segments/
    subdirectory with one .wav/.jsonl pair per start/stop recording."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def create(self, name=None):
        with self.lock:
            session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex
            path = self.directory / session_id
            path.mkdir(parents=True)
            now = _now()
            meta = {
                "id": session_id,
                "name": (name or "").strip() or _default_name(),
                "language": "en",
                "text": "",
                "created_at": now,
                "updated_at": now,
            }
            self._write(path, meta)
            return meta

    def list(self):
        sessions = []
        for path in self.directory.iterdir():
            if not path.is_dir():
                continue
            try:
                meta = self._read(path)
            except (OSError, json.JSONDecodeError):
                continue
            text = meta.get("text", "")
            sessions.append({
                "id": meta["id"],
                "name": meta.get("name", meta["id"]),
                "language": meta.get("language", "en"),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "preview": text[:120],
            })
        sessions.sort(key=lambda s: s["updated_at"] or "", reverse=True)
        return sessions

    def get(self, session_id):
        return self._read(self._existing_path(session_id))

    def rename(self, session_id, name):
        with self.lock:
            path = self._existing_path(session_id)
            meta = self._read(path)
            meta["name"] = name
            meta["updated_at"] = _now()
            self._write(path, meta)
            return meta

    def open_segment(self, session_id, language):
        path = self._existing_path(session_id)
        return SessionRecording(path / "segments", language)

    def append_text(self, session_id, text, language):
        if not text:
            return
        with self.lock:
            path = self._existing_path(session_id)
            meta = self._read(path)
            existing = meta.get("text", "")
            joiner = "" if not existing or existing[-1].isspace() else " "
            meta["text"] = existing + joiner + text
            meta["language"] = language
            meta["updated_at"] = _now()
            self._write(path, meta)
            return meta

    def _path(self, session_id):
        if not session_id or "/" in session_id or "\\" in session_id or session_id in (".", ".."):
            raise SessionNotFound(session_id)
        return self.directory / session_id

    def _existing_path(self, session_id):
        path = self._path(session_id)
        if not (path / "meta.json").exists():
            raise SessionNotFound(session_id)
        return path

    @staticmethod
    def _read(path):
        meta_path = path / "meta.json"
        if not meta_path.exists():
            raise SessionNotFound(path.name)
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write(path, meta):
        meta_path = path / "meta.json"
        tmp_path = meta_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        tmp_path.replace(meta_path)
