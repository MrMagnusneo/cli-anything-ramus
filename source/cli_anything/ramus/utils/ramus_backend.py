"""Backend that drives the real Ramus engine.

Ramus is a Java desktop application with no command-line interface of its own,
so this module speaks to it the only honest way: it compiles a small JSON bridge
against the shipped ``ramus.jar`` and runs Ramus's own classes headlessly. Every
model edit goes through ``com.ramussoft`` APIs and every rendered diagram comes
out of ``PIDEF0painter`` — the same painter the Ramus GUI uses for File > Export.

Nothing here reimplements Ramus behaviour. Without a Ramus build on the machine
the CLI cannot work, and says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

CACHE_DIR = Path(
    os.environ.get("CLI_ANYTHING_RAMUS_HOME", str(Path.home() / ".cli-anything-ramus"))
).expanduser()
BRIDGE_CLASS = "com.cliany.ramus.RamusBridge"
JAVA_SOURCE_DIR = Path(__file__).resolve().parent / "java"

#: Where a Ramus build is normally found, in the order we try them.
JAR_SEARCH_PATHS = (
    "/opt/ramus/ramus.jar",
    "/usr/share/ramus/ramus.jar",
    "/usr/local/lib/ramus/ramus.jar",
    "/usr/local/share/ramus/ramus.jar",
    "~/.local/share/ramus/ramus.jar",
    "/Applications/Ramus.app/Contents/MacOS/ramus.jar",
    "/Applications/Ramus.app/Contents/app/ramus.jar",
)

#: Relative locations of the fat jar inside a Ramus source checkout.
JAR_IN_CHECKOUT = (
    "local-client/build/libs/ramus.jar",
    "build/libs/ramus.jar",
    "dest/full/bin/ramus.jar",
)

INSTALL_HINT = """Ramus was not found.

The CLI is a command-line interface to Ramus, not a replacement for it, so a
Ramus build is required. Any one of these works:

  1. Point the CLI at an existing build:
       export RAMUS_JAR=/path/to/ramus.jar
     or
       export RAMUS_HOME=/path/to/ramus            # containing ramus.jar

  2. Build it from source (needs a JDK; downloads Gradle dependencies once):
       git clone https://github.com/Vitaliy-Yakovchuk/ramus
       cd ramus && ./gradlew :local-client:shadowJar
       export RAMUS_JAR=$PWD/local-client/build/libs/ramus.jar

  3. Run the CLI from inside a Ramus checkout that has already been built;
     the jar is found automatically."""


class RamusNotFound(RuntimeError):
    """Raised when no Ramus build can be located."""


class JavaNotFound(RuntimeError):
    """Raised when the JDK tools the bridge needs are missing."""


class BridgeError(RuntimeError):
    """An operation that the Ramus engine refused.

    ``trace`` carries the Java stack trace, which is worth showing when the
    failure is not something the caller could have anticipated.
    """

    def __init__(self, message: str, error_type: str = "", trace: str = ""):
        super().__init__(message)
        self.error_type = error_type
        self.trace = trace


# --------------------------------------------------------------------- tooling


def find_java() -> str:
    """Locate the ``java`` launcher."""
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("java")
    if found:
        return found
    raise JavaNotFound(
        "java was not found on PATH. Ramus needs a Java runtime (JDK 11 or newer).\n"
        "  apt install default-jdk      # Debian/Ubuntu\n"
        "  dnf install java-latest-openjdk-devel   # Fedora/RHEL\n"
        "  brew install openjdk         # macOS"
    )


def find_javac() -> str:
    """Locate ``javac``, needed once to compile the bridge."""
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("javac")
    if found:
        return found
    raise JavaNotFound(
        "javac was not found on PATH. The CLI compiles a small bridge against ramus.jar "
        "on first use, so a full JDK is required (a JRE alone is not enough).\n"
        "  apt install default-jdk                 # Debian/Ubuntu\n"
        "  dnf install java-latest-openjdk-devel   # Fedora/RHEL\n"
        "  brew install openjdk                    # macOS"
    )


def find_ramus_jar() -> str:
    """Find ``ramus.jar``, raising :class:`RamusNotFound` with instructions."""
    env_jar = os.environ.get("RAMUS_JAR")
    if env_jar:
        path = Path(env_jar).expanduser()
        if not path.is_file():
            raise RamusNotFound(f"RAMUS_JAR points at {path}, which is not a file.\n\n{INSTALL_HINT}")
        return str(path.resolve())

    ramus_home = os.environ.get("RAMUS_HOME")
    if ramus_home:
        home = Path(ramus_home).expanduser()
        for relative in ("ramus.jar",) + JAR_IN_CHECKOUT:
            candidate = home / relative
            if candidate.is_file():
                return str(candidate.resolve())
        raise RamusNotFound(
            f"RAMUS_HOME is {home}, but no ramus.jar was found under it.\n\n{INSTALL_HINT}"
        )

    for raw in JAR_SEARCH_PATHS:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())

    # Walk up from the working directory, so running inside a built checkout
    # just works.
    for base in [Path.cwd()] + list(Path.cwd().parents):
        for relative in JAR_IN_CHECKOUT:
            candidate = base / relative
            if candidate.is_file():
                return str(candidate.resolve())

    raise RamusNotFound(INSTALL_HINT)


# --------------------------------------------------------------------- bridge


def _source_files() -> list[Path]:
    if not JAVA_SOURCE_DIR.is_dir():
        raise RuntimeError(f"Bridge sources are missing from the package: {JAVA_SOURCE_DIR}")
    return sorted(JAVA_SOURCE_DIR.rglob("*.java"))


def _fingerprint(jar: str) -> str:
    """Identifies a compiled bridge: its own sources plus the jar it targets."""
    digest = hashlib.sha256()
    for path in _source_files():
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    stat = os.stat(jar)
    digest.update(f"{jar}:{stat.st_size}:{int(stat.st_mtime)}".encode())
    return digest.hexdigest()[:16]


def build_bridge(jar: str | None = None, force: bool = False) -> str:
    """Compile the bridge if needed and return its classes directory."""
    jar = jar or find_ramus_jar()
    target = CACHE_DIR / "bridge" / _fingerprint(jar)
    marker = target / ".ok"
    if marker.is_file() and not force:
        return str(target)

    javac = find_javac()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    command = [javac, "-nowarn", "-cp", jar, "-d", str(target)] + [str(p) for p in _source_files()]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError(
            "Failed to compile the Ramus bridge against " + jar + "\n" + (result.stderr or result.stdout)
        )
    marker.write_text(jar + "\n")
    return str(target)


class RamusBridge:
    """A long-lived Ramus JVM, driven one JSON request at a time.

    Starting a JVM and loading the Ramus engine takes a couple of seconds, so
    the process is started once and reused: a REPL session, or a one-shot
    command's whole chain of operations, pays that cost only once.
    """

    def __init__(self, jar: str | None = None, classes: str | None = None):
        self.jar = jar or find_ramus_jar()
        self.classes = classes or build_bridge(self.jar)
        self._process: subprocess.Popen | None = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._stderr: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        java = find_java()
        separator = ";" if os.name == "nt" else ":"
        classpath = separator.join([self.jar, self.classes])
        # Headless by default so the CLI runs on servers and in CI. Ramus's EMF
        # writer is the one path that needs a real display, so an operator with
        # a display can opt out.
        headless = os.environ.get("CLI_ANYTHING_RAMUS_HEADLESS", "1").strip() != "0"
        command = [
            java,
            f"-Djava.awt.headless={'true' if headless else 'false'}",
            "-Dfile.encoding=UTF-8",
            "-Xss4m",
            "-cp",
            classpath,
            BRIDGE_CLASS,
        ]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._stderr = []
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        """Keep the JVM's stderr from filling its pipe and blocking the JVM."""
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr.append(line.rstrip("\n"))
            del self._stderr[:-400]

    def stop(self) -> None:
        if self._process is None:
            return
        process, self._process = self._process, None
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(json.dumps({"id": -1, "op": "shutdown"}) + "\n")
                process.stdin.flush()
                process.wait(timeout=10)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            process.kill()
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass

    def __enter__(self) -> RamusBridge:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- protocol -------------------------------------------------------

    def call(self, op: str, **args) -> dict:
        """Run one operation, returning its result or raising :class:`BridgeError`."""
        with self._lock:
            self.start()
            process = self._process
            assert process is not None and process.stdin is not None and process.stdout is not None

            self._next_id += 1
            request = {"id": self._next_id, "op": op, "args": {k: v for k, v in args.items() if v is not None}}
            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                raise BridgeError(self._died_message(f"writing {op}")) from exc

            line = process.stdout.readline()
            if not line:
                raise BridgeError(self._died_message(f"running {op}"))
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BridgeError(
                    f"Unreadable response from the Ramus bridge while running {op}: {line[:400]!r}"
                ) from exc

        if frame.get("ok"):
            result = frame.get("result")
            return result if isinstance(result, dict) else {"result": result}
        raise BridgeError(
            frame.get("error") or f"{op} failed",
            error_type=frame.get("error_type", ""),
            trace=frame.get("trace", ""),
        )

    def _died_message(self, during: str) -> str:
        tail = "\n".join(self._stderr[-25:])
        message = f"The Ramus engine stopped unexpectedly while {during}."
        if tail:
            message += "\nJava output:\n" + tail
        return message

    # -- convenience ----------------------------------------------------

    def ping(self) -> dict:
        info = self.call("ping")
        info["ramus_jar"] = self.jar
        info["bridge_classes"] = self.classes
        return info


_shared: RamusBridge | None = None


def get_bridge() -> RamusBridge:
    """The process-wide bridge, started on first use."""
    global _shared
    if _shared is None or not _shared.running:
        if _shared is not None:
            _shared.stop()
        _shared = RamusBridge()
        _shared.start()
    return _shared


def shutdown_bridge() -> None:
    """Stop the shared bridge, if one was started."""
    global _shared
    if _shared is not None:
        _shared.stop()
        _shared = None


def backend_info() -> dict:
    """Describe the backend without requiring an open project."""
    info = {"java": None, "javac": None, "ramus_jar": None, "available": False, "problem": None}
    try:
        info["java"] = find_java()
    except JavaNotFound as exc:
        info["problem"] = str(exc)
        return info
    try:
        info["javac"] = find_javac()
    except JavaNotFound as exc:
        info["problem"] = str(exc)
        return info
    try:
        info["ramus_jar"] = find_ramus_jar()
    except RamusNotFound as exc:
        info["problem"] = str(exc)
        return info
    info["available"] = True
    return info


if __name__ == "__main__":  # pragma: no cover - manual diagnostics
    print(json.dumps(backend_info(), indent=2))
    try:
        with RamusBridge() as bridge:
            print(json.dumps(bridge.ping(), indent=2))
    except (RamusNotFound, JavaNotFound, BridgeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
