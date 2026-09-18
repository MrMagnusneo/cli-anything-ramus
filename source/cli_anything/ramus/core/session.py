"""Stateful session: the open project, and undo history.

Ramus's own undo stack lives inside a running JVM and is never written to the
``.rsf`` file, so it cannot survive between one-shot CLI invocations. This
session therefore keeps its own history as real ``.rsf`` snapshots on disk,
written by Ramus itself. Undo reopens a snapshot, which means undo restores
exactly the file Ramus would have written — not an approximation.

History is keyed by project path, so a chain of one-shot commands against the
same file shares one history, and the REPL sees the same one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from ..utils.ramus_backend import BridgeError, get_bridge

SESSION_ROOT = Path(
    os.environ.get("CLI_ANYTHING_RAMUS_HOME", str(Path.home() / ".cli-anything-ramus"))
).expanduser() / "sessions"

MAX_UNDO_DEPTH = 50


def _locked_save_json(path, data, **dump_kwargs) -> None:
    """Atomically write JSON with exclusive file locking."""
    path = str(path)
    try:
        handle = open(path, "r+")
    except FileNotFoundError:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        handle = open(path, "w")
    with handle:
        locked = False
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass  # Windows / unsupported filesystem — proceed unlocked.
        try:
            handle.seek(0)
            handle.truncate()
            json.dump(data, handle, **dump_kwargs)
            handle.flush()
        finally:
            if locked:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def session_id_for(project_path: str) -> str:
    """A stable id for a project file, so history follows the file."""
    resolved = str(Path(project_path).expanduser().resolve())
    digest = hashlib.sha1(resolved.encode()).hexdigest()[:12]
    stem = Path(resolved).stem or "project"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in stem)[:32]
    return f"{safe}-{digest}"


class Session:
    """Tracks the open project and its undo history."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id
        self.project_path: str | None = None
        self._modified = False
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._counter = 0
        #: When set, mutations run but nothing is written to the project file.
        self.dry_run = False

    # -- state ----------------------------------------------------------

    @property
    def bridge(self):
        return get_bridge()

    def has_project(self) -> bool:
        return self.project_path is not None

    def require_project(self) -> None:
        if not self.has_project():
            raise RuntimeError(
                "No project is open. Pass --project <file.rsf>, or create one with: project new <file.rsf>"
            )

    @property
    def directory(self) -> Path:
        if self.session_id is None:
            raise RuntimeError("Session has no id yet; open or create a project first")
        return SESSION_ROOT / self.session_id

    @property
    def snapshot_dir(self) -> Path:
        return self.directory / "snapshots"

    @property
    def state_path(self) -> Path:
        return self.directory / "session.json"

    # -- open / create / save -------------------------------------------

    def open_project(self, path: str) -> dict:
        resolved = str(Path(path).expanduser().resolve())
        info = self.bridge.call("project.open", path=resolved)
        self.project_path = info.get("path", resolved)
        self.session_id = session_id_for(self.project_path)
        self._modified = False
        self._load_history()
        return info

    def new_project(self, path: str, **kwargs) -> dict:
        resolved = str(Path(path).expanduser().absolute())
        info = self.bridge.call("project.new", path=resolved, **kwargs)
        self.project_path = info.get("path", resolved)
        self.session_id = session_id_for(self.project_path)
        self._modified = False
        self._reset_history()
        return info

    def save_project(self, path: str | None = None, overwrite: bool = True) -> dict:
        self.require_project()
        info = self.bridge.call("project.save", path=path, overwrite=overwrite)
        self.project_path = info.get("path", self.project_path)
        self.session_id = session_id_for(self.project_path)
        self._modified = False
        self.save_session()
        return info

    def close_project(self) -> dict:
        info = self.bridge.call("project.close")
        self.project_path = None
        self._modified = False
        return info

    # -- mutation bookkeeping -------------------------------------------

    def snapshot(self) -> str | None:
        """Record the project's current state so the next change can be undone.

        A dry run leaves no trace on disk, so it records nothing.
        """
        self.require_project()
        if self.dry_run:
            return None
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._counter += 1
        target = self.snapshot_dir / f"{int(time.time() * 1000)}-{self._counter}.rsf"
        self._save_copy(target)
        self._undo.append(str(target))
        for stale in self._redo:
            self._discard(stale)
        self._redo.clear()
        while len(self._undo) > MAX_UNDO_DEPTH:
            self._discard(self._undo.pop(0))
        return str(target)

    def _save_copy(self, target) -> None:
        """Write a byte-exact copy without retargeting the open project."""
        self.bridge.call("project.save-copy", path=str(target))

    def mark_modified(self) -> None:
        self._modified = True

    @property
    def modified(self) -> bool:
        return self._modified

    def undo(self) -> dict:
        """Restore the state before the most recent change."""
        self.require_project()
        if not self._undo:
            raise RuntimeError("Nothing to undo")
        current = self.snapshot_dir / f"redo-{int(time.time() * 1000)}-{self._counter + 1}.rsf"
        self._counter += 1
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._save_copy(current)

        restore = self._undo.pop()
        self.bridge.call("project.open", path=restore)
        self.bridge.call("project.save", path=self.project_path, overwrite=True)
        self._redo.append(str(current))
        self._modified = False
        self.save_session()
        return {
            "undone": True,
            "restored_from": restore,
            "project": self.project_path,
            "undo_available": len(self._undo),
            "redo_available": len(self._redo),
        }

    def redo(self) -> dict:
        """Re-apply the change that :meth:`undo` rolled back."""
        self.require_project()
        if not self._redo:
            raise RuntimeError("Nothing to redo")
        current = self.snapshot_dir / f"{int(time.time() * 1000)}-{self._counter + 1}.rsf"
        self._counter += 1
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._save_copy(current)

        restore = self._redo.pop()
        self.bridge.call("project.open", path=restore)
        self.bridge.call("project.save", path=self.project_path, overwrite=True)
        self._undo.append(str(current))
        self._modified = False
        self.save_session()
        return {
            "redone": True,
            "restored_from": restore,
            "project": self.project_path,
            "undo_available": len(self._undo),
            "redo_available": len(self._redo),
        }

    # -- persistence ----------------------------------------------------

    def save_session(self) -> str:
        """Persist session metadata so the next process finds the history."""
        if self.session_id is None:
            raise RuntimeError("Session has no id yet; open or create a project first")
        self.directory.mkdir(parents=True, exist_ok=True)
        state = {
            "session_id": self.session_id,
            "project_path": self.project_path,
            "modified": self._modified,
            "undo": self._undo,
            "redo": self._redo,
            "counter": self._counter,
            "timestamp": time.time(),
        }
        _locked_save_json(self.state_path, state, indent=2, sort_keys=True)
        return str(self.state_path)

    def _load_history(self) -> None:
        self._undo = []
        self._redo = []
        self._counter = 0
        if not self.state_path.is_file():
            return
        try:
            with open(self.state_path) as handle:
                state = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return
        # Snapshots can be removed out from under us; keep only what survives.
        self._undo = [p for p in state.get("undo", []) if Path(p).is_file()]
        self._redo = [p for p in state.get("redo", []) if Path(p).is_file()]
        self._counter = int(state.get("counter", 0))

    def _reset_history(self) -> None:
        self._undo = []
        self._redo = []
        self._counter = 0
        if self.session_id is not None and self.snapshot_dir.is_dir():
            shutil.rmtree(self.snapshot_dir, ignore_errors=True)

    @staticmethod
    def _discard(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    # -- reporting ------------------------------------------------------

    def status(self) -> dict:
        state = {
            "session_id": self.session_id,
            "project_open": self.has_project(),
            "project_path": self.project_path,
            "modified": self._modified,
            "undo_available": len(self._undo),
            "redo_available": len(self._redo),
            "dry_run": self.dry_run,
            "max_undo_depth": MAX_UNDO_DEPTH,
            "session_dir": str(self.directory) if self.session_id else None,
        }
        if self.has_project():
            try:
                info = self.bridge.call("project.info")
                state["models"] = info.get("models", [])
                state["model_count"] = info.get("model_count", 0)
                state["function_count"] = info.get("function_count", 0)
                state["arrow_count"] = info.get("arrow_count", 0)
                state["classifier_count"] = info.get("classifier_count", 0)
                state["file_size"] = info.get("file_size", 0)
            except BridgeError:
                pass
        return state

    def history(self) -> dict:
        def describe(paths: list[str]) -> list[dict]:
            entries = []
            for path in paths:
                file = Path(path)
                entries.append(
                    {
                        "path": path,
                        "exists": file.is_file(),
                        "size": file.stat().st_size if file.is_file() else 0,
                        "saved_at": file.stat().st_mtime if file.is_file() else None,
                    }
                )
            return entries

        return {
            "session_id": self.session_id,
            "project_path": self.project_path,
            "undo": describe(self._undo),
            "redo": describe(self._redo),
            "undo_available": len(self._undo),
            "redo_available": len(self._redo),
        }

    @classmethod
    def list_sessions(cls) -> list[dict]:
        SESSION_ROOT.mkdir(parents=True, exist_ok=True)
        sessions = []
        for state_file in SESSION_ROOT.glob("*/session.json"):
            try:
                with open(state_file) as handle:
                    state = json.load(handle)
            except (json.JSONDecodeError, OSError):
                continue
            sessions.append(
                {
                    "session_id": state.get("session_id"),
                    "project_path": state.get("project_path"),
                    "project_exists": bool(state.get("project_path"))
                    and Path(state["project_path"]).is_file(),
                    "undo_available": len(state.get("undo", [])),
                    "redo_available": len(state.get("redo", [])),
                    "timestamp": state.get("timestamp", 0),
                }
            )
        sessions.sort(key=lambda s: s.get("timestamp", 0), reverse=True)
        return sessions


_session: Session | None = None


def get_session() -> Session:
    """The process-wide session."""
    global _session
    if _session is None:
        _session = Session()
    return _session


def reset_session() -> None:
    """Drop the process-wide session (used by tests)."""
    global _session
    _session = None
