#!/usr/bin/env bash
#
# Removes everything install.sh put in place. Project files (.rsf) and rendered
# diagrams you created are never touched.
#
#   bash uninstall.sh              remove CLI, ramus.jar, skills and caches
#   bash uninstall.sh --keep-jar   leave ~/.local/share/ramus/ramus.jar in place
#   bash uninstall.sh --keep-state leave undo history and the bridge cache

set -uo pipefail

KEEP_JAR=0
KEEP_STATE=0
for arg in "$@"; do
    case "$arg" in
        --keep-jar) KEEP_JAR=1 ;;
        --keep-state) KEEP_STATE=1 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

removed() { printf '  [removed] %s\n' "$1"; }
skipped() { printf '  [absent]  %s\n' "$1"; }

remove_path() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        rm -rf "$1" && removed "$1"
    else
        skipped "$1"
    fi
}

echo "==> Python package"
if python3 -m pip show cli-anything-ramus >/dev/null 2>&1; then
    python3 -m pip uninstall -y cli-anything-ramus >/dev/null 2>&1 \
        && removed "cli-anything-ramus (pip)" \
        || echo "  [warn]    pip could not uninstall cli-anything-ramus; remove it manually" >&2
else
    skipped "cli-anything-ramus (pip)"
fi
remove_path "$HOME/.local/share/cli-anything-ramus/venv"
# Only remove the launcher if it is ours (a venv symlink or a pip script).
LAUNCHER="$HOME/.local/bin/cli-anything-ramus"
if [ -L "$LAUNCHER" ] || { [ -f "$LAUNCHER" ] && grep -q "cli_anything.ramus" "$LAUNCHER" 2>/dev/null; }; then
    remove_path "$LAUNCHER"
else
    skipped "$LAUNCHER"
fi

echo "==> Skills"
for dir in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
    remove_path "$dir/cli-anything-ramus"
done

echo "==> Ramus engine"
if [ "$KEEP_JAR" -eq 1 ]; then
    echo "  [kept]    $HOME/.local/share/ramus/ramus.jar"
else
    remove_path "$HOME/.local/share/ramus/ramus.jar"
    rmdir "$HOME/.local/share/ramus" 2>/dev/null || true
fi

echo "==> State and caches"
if [ "$KEEP_STATE" -eq 1 ]; then
    echo "  [kept]    ${CLI_ANYTHING_RAMUS_HOME:-$HOME/.cli-anything-ramus}"
else
    remove_path "${CLI_ANYTHING_RAMUS_HOME:-$HOME/.cli-anything-ramus}"
fi
rmdir "$HOME/.local/share/cli-anything-ramus" 2>/dev/null || true

echo
echo "RESULT: OK"
