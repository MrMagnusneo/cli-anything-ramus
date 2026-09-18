#!/usr/bin/env bash
#
# Installs the cli-anything-ramus skill: the CLI, the Ramus engine and SKILL.md,
# then proves the installation works by building and rendering a real model.
#
#   bash install.sh                    install everything and verify
#   bash install.sh --check            verify an existing installation only
#   bash install.sh --help             all options
#
# Safe to run repeatedly. Needs Python 3.10+ and a JDK 11+ (java and javac).
# Everything else is in this folder, so no network access is required.

set -uo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="cli-anything-ramus"
CLI_NAME="cli-anything-ramus"

JAR_TARGET="${HOME}/.local/share/ramus/ramus.jar"
VENV_DIR="${HOME}/.local/share/cli-anything-ramus/venv"
BIN_DIR="${HOME}/.local/bin"

MODE="install"
METHOD="auto"
JAR_SOURCE=""
SKIP_SKILL=0
SKIP_SMOKE=0
SKILL_DIRS=()

# ------------------------------------------------------------------ output

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_OK=$'\033[32m'; C_ERR=$'\033[31m'; C_WARN=$'\033[33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_ERR=""; C_WARN=""; C_DIM=""; C_OFF=""
fi

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '%s  [OK]%s   %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '%s  [WARN]%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
info() { printf '%s         %s%s\n' "$C_DIM" "$*" "$C_OFF"; }
die()  {
    printf '%s  [FAIL]%s %s\n' "$C_ERR" "$C_OFF" "$1" >&2
    shift
    local arg
    for arg in "$@"; do
        printf '%s\n' "$arg" | while IFS= read -r line; do printf '         %s\n' "$line" >&2; done
    done
    printf '\nRESULT: FAILED\n' >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: bash install.sh [options]

  --check              Only verify an existing installation; change nothing.
  --method METHOD      How to install the Python package:
                         auto  (default) pip --user, falling back to a private venv
                         user  pip install --user only
                         venv  private venv in ~/.local/share/cli-anything-ramus/venv
  --jar PATH           Use this ramus.jar instead of the one in vendor/.
  --skills-dir DIR     Install SKILL.md into DIR/cli-anything-ramus/. Repeatable.
                       Default: ~/.claude/skills and ~/.agents/skills.
  --no-skill           Do not install SKILL.md anywhere.
  --no-smoke-test      Skip the end-to-end render test.
  -h, --help           Show this help.

Exit status is 0 only when every check passed. The last line of output is
always "RESULT: OK" or "RESULT: FAILED".
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --check) MODE="check" ;;
        --method) METHOD="${2:-}"; shift ;;
        --jar) JAR_SOURCE="${2:-}"; shift ;;
        --skills-dir) SKILL_DIRS+=("${2:-}"); shift ;;
        --no-skill) SKIP_SKILL=1 ;;
        --no-smoke-test) SKIP_SMOKE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "Unknown option: $1" ;;
    esac
    shift
done

case "$METHOD" in auto|user|venv) ;; *) die "Unknown --method '$METHOD'" "Use auto, user or venv." ;; esac

if [ ${#SKILL_DIRS[@]} -eq 0 ]; then
    SKILL_DIRS=("${HOME}/.claude/skills" "${HOME}/.agents/skills")
fi

# ------------------------------------------------------------ requirements

jdk_hint() {
    cat <<'EOF'
Install a JDK 11 or newer (the full JDK: javac is required, a JRE is not enough):
  Debian/Ubuntu:  sudo apt install -y default-jdk
  Fedora/RHEL:    sudo dnf install -y java-21-openjdk-devel
  Arch:           sudo pacman -S --needed jdk-openjdk
  macOS:          brew install openjdk
Or point JAVA_HOME at an existing JDK. Then run this script again.
EOF
}

java_major() {
    # Prints the major version from `java -version` / `javac -version` output.
    sed -n 's/.*[" ]\([0-9][0-9]*\)\(\.[0-9][0-9]*\)*[" ].*/\1/p;s/^javac \([0-9][0-9]*\).*/\1/p' | head -n1
}

find_tool() {
    local name="$1"
    if [ -n "${JAVA_HOME:-}" ] && [ -x "${JAVA_HOME}/bin/${name}" ]; then
        printf '%s\n' "${JAVA_HOME}/bin/${name}"
    else
        command -v "$name" 2>/dev/null
    fi
}

check_requirements() {
    step "Checking requirements"

    PYTHON="$(command -v python3 || true)"
    [ -n "$PYTHON" ] || die "python3 was not found." \
        "Install Python 3.10 or newer (e.g. sudo apt install -y python3 python3-venv python3-pip)."
    if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        die "Python $("$PYTHON" -c 'import platform; print(platform.python_version())') is too old." \
            "Python 3.10 or newer is required."
    fi
    ok "python3 $("$PYTHON" -c 'import platform; print(platform.python_version())') ($PYTHON)"

    local java javac jver cver
    java="$(find_tool java || true)"
    javac="$(find_tool javac || true)"
    if [ -z "$java" ]; then
        die "java was not found." "$(jdk_hint)"
    fi
    if [ -z "$javac" ]; then
        die "javac was not found — a JRE is installed but the CLI needs a full JDK." "$(jdk_hint)"
    fi
    jver="$("$java" -version 2>&1 | java_major)"
    cver="$("$javac" -version 2>&1 | java_major)"
    if [ -z "$jver" ] || [ "$jver" -lt 11 ]; then
        die "java ${jver:-?} is too old; 11 or newer is required." "$(jdk_hint)"
    fi
    ok "java $jver ($java)"
    ok "javac ${cver:-?} ($javac)"
}

# --------------------------------------------------------------------- jar

install_jar() {
    step "Installing the Ramus engine (ramus.jar)"

    local source="${JAR_SOURCE:-$BUNDLE_DIR/vendor/ramus.jar}"
    [ -f "$source" ] || die "ramus.jar not found at $source" \
        "Pass --jar /path/to/ramus.jar, or build one:" \
        "  git clone https://github.com/Vitaliy-Yakovchuk/ramus" \
        "  cd ramus && ./gradlew :local-client:shadowJar"

    if [ -z "$JAR_SOURCE" ] && [ -f "$BUNDLE_DIR/vendor/ramus.jar.sha256" ]; then
        if ! (cd "$BUNDLE_DIR/vendor" && sha256sum -c --quiet ramus.jar.sha256 >/dev/null 2>&1); then
            die "vendor/ramus.jar does not match vendor/ramus.jar.sha256." \
                "The bundle is damaged. Copy it again from its source."
        fi
        ok "checksum matches vendor/ramus.jar.sha256"
    fi

    if ! head -c 4 "$source" | od -An -c | grep -q 'P   K'; then
        die "$source is not a jar (no ZIP header)."
    fi

    mkdir -p "$(dirname "$JAR_TARGET")"
    if [ -f "$JAR_TARGET" ] && cmp -s "$source" "$JAR_TARGET"; then
        ok "already installed: $JAR_TARGET"
    else
        cp "$source" "$JAR_TARGET" || die "Could not copy ramus.jar to $JAR_TARGET"
        ok "installed: $JAR_TARGET"
    fi
    info "The CLI finds the jar here automatically; no RAMUS_JAR needed."
}

# ------------------------------------------------------------------ python

pip_install() {
    # $1 = python interpreter, remaining = extra pip args
    local py="$1"; shift
    local wheels="$BUNDLE_DIR/vendor/wheels"
    # Dependencies first, without disturbing versions the user already has.
    "$py" -m pip install --disable-pip-version-check --no-index --find-links "$wheels" \
        "$@" "click>=8.0" "prompt-toolkit>=3.0" || \
    "$py" -m pip install --disable-pip-version-check --find-links "$wheels" \
        "$@" "click>=8.0" "prompt-toolkit>=3.0" || return 1
    # Then this package, always replacing whatever version was there before.
    "$py" -m pip install --disable-pip-version-check --no-index --find-links "$wheels" \
        --force-reinstall --no-deps "$@" "$wheels"/cli_anything_ramus-*.whl
}

install_user() {
    info "pip install --user"
    local log
    log="$(mktemp)"
    if pip_install "$PYTHON" --user >"$log" 2>&1; then
        rm -f "$log"
        INSTALLED_BY="pip --user"
        return 0
    fi
    warn "pip install --user failed:"
    sed 's/^/           /' "$log" | tail -n 8
    rm -f "$log"
    return 1
}

install_venv() {
    info "private virtualenv at $VENV_DIR"
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        "$PYTHON" -m venv "$VENV_DIR" >/dev/null 2>&1 || die "Could not create a virtualenv." \
            "Install the venv module (e.g. sudo apt install -y python3-venv) and run again."
    fi
    local log
    log="$(mktemp)"
    if ! pip_install "$VENV_DIR/bin/python" >"$log" 2>&1; then
        cat "$log" >&2; rm -f "$log"
        die "pip install into the virtualenv failed (output above)."
    fi
    rm -f "$log"
    mkdir -p "$BIN_DIR"
    ln -sf "$VENV_DIR/bin/$CLI_NAME" "$BIN_DIR/$CLI_NAME" || die "Could not link $BIN_DIR/$CLI_NAME"
    INSTALLED_BY="venv ($VENV_DIR)"
}

install_package() {
    step "Installing the CLI (Python package)"
    INSTALLED_BY=""
    if [ -n "${VIRTUAL_ENV:-}" ] && [ "$METHOD" = "auto" ]; then
        info "active virtualenv: $VIRTUAL_ENV"
        pip_install "$PYTHON" >/dev/null 2>&1 || die "pip install into $VIRTUAL_ENV failed."
        INSTALLED_BY="active venv ($VIRTUAL_ENV)"
    else
        case "$METHOD" in
            user) install_user || die "pip install --user failed." "Try: bash install.sh --method venv" ;;
            venv) install_venv ;;
            auto) install_user || { warn "falling back to a private virtualenv"; install_venv; } ;;
        esac
    fi
    ok "installed via $INSTALLED_BY"
}

locate_cli() {
    CLI="$(command -v "$CLI_NAME" 2>/dev/null || true)"
    if [ -z "$CLI" ] && [ -x "$BIN_DIR/$CLI_NAME" ]; then
        CLI="$BIN_DIR/$CLI_NAME"
    fi
    if [ -z "$CLI" ] && [ -x "$VENV_DIR/bin/$CLI_NAME" ]; then
        CLI="$VENV_DIR/bin/$CLI_NAME"
    fi
    [ -n "$CLI" ]
}

check_path() {
    case ":$PATH:" in
        *":$(dirname "$CLI"):"*) ok "$CLI_NAME is on PATH ($CLI)" ;;
        *)
            warn "$(dirname "$CLI") is not on PATH, so '$CLI_NAME' will not be found by name."
            info "Add it for future shells:"
            info "  echo 'export PATH=\"$(dirname "$CLI"):\$PATH\"' >> ~/.bashrc"
            info "Until then call it by full path: $CLI"
            ;;
    esac
}

# ------------------------------------------------------------------- skill

install_skill() {
    step "Installing SKILL.md"
    local dir target
    for dir in "${SKILL_DIRS[@]}"; do
        target="$dir/$SKILL_NAME/SKILL.md"
        mkdir -p "$(dirname "$target")" || die "Cannot create $(dirname "$target")"
        # The skill points back at this bundle for reinstalls and deeper docs.
        sed "s|{{BUNDLE_DIR}}|$BUNDLE_DIR|g" "$BUNDLE_DIR/skill/SKILL.md" >"$target" \
            || die "Cannot write $target"
        ok "$target"
    done
}

check_skill() {
    step "Checking SKILL.md"
    local dir target found=0
    for dir in "${SKILL_DIRS[@]}"; do
        target="$dir/$SKILL_NAME/SKILL.md"
        if [ -f "$target" ] && head -n 5 "$target" | grep -q "$SKILL_NAME"; then
            if grep -q '{{BUNDLE_DIR}}' "$target"; then
                warn "$target still contains an unfilled {{BUNDLE_DIR}} placeholder"
            else
                ok "$target"
            fi
            found=1
        else
            warn "missing: $target"
        fi
    done
    [ "$found" -eq 1 ] || die "SKILL.md is not installed in any skills directory." \
        "Run: bash $BUNDLE_DIR/install.sh"
}

# ------------------------------------------------------------ verification

verify() {
    step "Verifying the backend (first run compiles the Ramus bridge)"
    locate_cli || die "$CLI_NAME is not installed." "Run: bash $BUNDLE_DIR/install.sh"
    check_path

    local out
    if ! out="$("$CLI" --json doctor 2>&1)"; then
        die "'$CLI_NAME doctor' reports the backend is not usable:" "$out"
    fi
    if ! printf '%s' "$out" | "$PYTHON" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("available") else 1)'; then
        die "'$CLI_NAME doctor' reports the backend is not usable:" "$out"
    fi
    DOCTOR_JAR="$(printf '%s' "$out" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("ramus_jar"))')"
    ok "doctor: backend available, using $DOCTOR_JAR"

    if [ "$SKIP_SMOKE" -eq 1 ]; then
        warn "end-to-end test skipped (--no-smoke-test)"
        return
    fi

    step "End-to-end test: build a model and render it with Ramus"
    local work
    work="$(mktemp -d)"
    local p="$work/smoke.rsf"
    run() { "$CLI" "$@" >"$work/last.log" 2>&1 || die "Command failed: $CLI_NAME $*" "$(cat "$work/last.log")"; }

    run project new "$p" --model-name "Install check"
    run --project "$p" function add "Receive"
    run --project "$p" function add "Process"
    run --project "$p" arrow add --from border --from-side input --to "Receive" --name "Request"
    run --project "$p" arrow add --from "Receive" --to "Process" --name "Accepted request"
    run --project "$p" export diagram "$work/a0.png" --overwrite
    run --project "$p" export pdf "$work/model.pdf" --overwrite

    [ "$(head -c 4 "$p" | od -An -c | tr -d ' \n')" = "PK003004" ] \
        || die "The project file is not a valid .rsf (no ZIP header)."
    ok "created a .rsf project with 2 boxes and 2 arrows"
    [ "$(head -c 8 "$work/a0.png" | od -An -tx1 | tr -d ' \n')" = "89504e470d0a1a0a" ] \
        || die "The rendered PNG is not a PNG."
    ok "rendered PNG ($(wc -c <"$work/a0.png" | tr -d ' ') bytes)"
    [ "$(head -c 5 "$work/model.pdf")" = "%PDF-" ] || die "The rendered PDF is not a PDF."
    ok "rendered PDF ($(wc -c <"$work/model.pdf" | tr -d ' ') bytes)"
    rm -rf "$work"
}

# -------------------------------------------------------------------- main

printf 'cli-anything-ramus installer\n'
printf 'bundle: %s\n' "$BUNDLE_DIR"
printf 'mode:   %s\n' "$MODE"

check_requirements

if [ "$MODE" = "install" ]; then
    install_jar
    install_package
    [ "$SKIP_SKILL" -eq 1 ] || install_skill
fi

verify
[ "$SKIP_SKILL" -eq 1 ] || check_skill

step "Summary"
ok "CLI:       $CLI"
ok "ramus.jar: ${DOCTOR_JAR:-$JAR_TARGET}"
if [ "$SKIP_SKILL" -eq 0 ]; then
    for dir in "${SKILL_DIRS[@]}"; do ok "skill:     $dir/$SKILL_NAME/SKILL.md"; done
fi
printf '\nRESULT: OK\n'
