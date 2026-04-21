#!/usr/bin/env bash
#
# setup_remote_permissions.sh
#
# Normalize group access on shared storage directories.
#
# Three modes (applied recursively to all content under each target):
#   readonly  — group/others can browse and download, group cannot write [ro]  in TUI
#   public    — group can browse, download, and upload (write)    [pub] in TUI
#   private   — group/others have no access                       [pvt] in TUI
#
# Usage:
#   setup_remote_permissions.sh [--group GROUP] [--dry-run] [-v] <mode> <path> [<path> ...]
#   setup_remote_permissions.sh --update
#   setup_remote_permissions.sh --version
#
# Options:
#   --group G   Shared group name (default: $GROUP or current primary group).
#   --dry-run   Show how many entries would change, without modifying anything.
#   -v          Verbose: list every entry whose permissions will be/were changed.
#   --update    Download latest version from GitHub and replace local file.
#   --version   Show version number.
#
# Examples:
#   # Preview what would change, without applying
#   ./setup_remote_permissions.sh --dry-run readonly /data/storage/sn_assets
#
#   # Lock a released dataset so teammates can only download it
#   ./setup_remote_permissions.sh readonly /data/storage/datasets/v1.0
#
#   # Open a staging area so teammates can upload into it
#   ./setup_remote_permissions.sh public /data/storage/datasets/staging
#
#   # Hide a work-in-progress directory from teammates
#   ./setup_remote_permissions.sh private /data/storage/wip_secret
#
#   # Apply to multiple paths at once
#   ./setup_remote_permissions.sh readonly /data/storage/v1.0 /data/storage/v1.1
#
# Run remotely from local machine:
#   ssh user@host "bash /path/to/scripts/setup_remote_permissions.sh readonly /remote/path"
#

set -euo pipefail

# ─────────────────────────── config ─────────────────────────────────────── #

VERSION="0.1.0"
GITHUB_RAW_URL="https://raw.githubusercontent.com/idlesilver/rsync_tree_tui/main/setup_remote_permissions.sh"

# Edit this line to persist a site-specific default, or pass --group.
GROUP="${GROUP:-$(id -gn)}"

# ─────────────────────────── arg parsing ────────────────────────────────── #

DRY_RUN=0
VERBOSE=0
UPDATE=0
MODE=""
TARGETS=()

usage() {
    sed -n '/^# Usage:/,/^[^#]/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
    exit 1
}

do_self_update() {
    local script_path
    script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    echo "setup_remote_permissions.sh $VERSION - Self Update"
    echo "----------------------------------------"

    echo "Downloading latest version from GitHub..."
    local tmp_path
    tmp_path="$(mktemp)"

    if ! curl -fsSL "$GITHUB_RAW_URL" -o "$tmp_path"; then
        echo "ERROR: Download failed"
        rm -f "$tmp_path"
        exit 1
    fi

    # Basic validation
    if ! grep -q "setup_remote_permissions.sh" "$tmp_path"; then
        echo "ERROR: Downloaded content does not appear to be a valid script"
        rm -f "$tmp_path"
        exit 1
    fi

    # Extract remote version
    local remote_version
    remote_version="$(grep '^VERSION=' "$tmp_path" | cut -d'"' -f2 || echo "unknown")"
    echo "Remote version: $remote_version"
    if [[ "$remote_version" == "$VERSION" ]]; then
        echo "Already up to date!"
        rm -f "$tmp_path"
        exit 0
    fi

    echo ""
    read -r -p "Update? [y/N] " answer
    case "$answer" in
        [yY][eE][sS]|[yY])
            ;;
        *)
            echo "Cancelled."
            rm -f "$tmp_path"
            exit 0
            ;;
    esac

    # Preserve permissions and replace
    chmod --reference="$script_path" "$tmp_path" 2>/dev/null || chmod 755 "$tmp_path"

    if mv "$tmp_path" "$script_path"; then
        echo "Updated: $script_path"
        echo "Successfully updated to version $remote_version"
        exit 0
    else
        echo "ERROR: Permission denied - cannot write to $script_path"
        rm -f "$tmp_path"
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --update)         UPDATE=1; shift ;;
        --version)        echo "setup_remote_permissions.sh $VERSION"; exit 0 ;;
        --group)
            [[ $# -lt 2 ]] && { echo "ERROR: --group requires a value" >&2; usage; }
            GROUP="$2"
            shift 2
            ;;
        --group=*)
            GROUP="${1#*=}"
            shift
            ;;
        --dry-run)        DRY_RUN=1; shift ;;
        -v|--verbose)     VERBOSE=1; shift ;;
        --help|-h)        usage ;;
        readonly|public|private)
            [[ -n "$MODE" ]] && { echo "ERROR: mode specified twice ('$MODE' and '$1')"; exit 1; }
            MODE="$1"
            shift
            ;;
        -*)
            echo "ERROR: unknown option: $1" >&2; usage ;;
        *)
            TARGETS+=("$1")
            shift
            ;;
    esac
done

# Handle --update before other validation
if [[ $UPDATE -eq 1 ]]; then
    do_self_update
fi

[[ -z "$MODE"            ]] && { echo "ERROR: mode is required (readonly|public|private)"; echo; usage; }
[[ ${#TARGETS[@]} -eq 0 ]] && { echo "ERROR: at least one path is required"; echo; usage; }
[[ -z "$GROUP"           ]] && { echo "ERROR: group must not be empty"; echo; usage; }

# ─────────────────────────── helpers ────────────────────────────────────── #

# ANSI colors (disabled when not a terminal)
if [[ -t 1 ]]; then
    RED='\033[0;31m'; YELLOW='\033[0;33m'; GREEN='\033[0;32m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; YELLOW=''; GREEN=''; CYAN=''; BOLD=''; RESET=''
fi

log_info()  { echo -e "${CYAN}  ${*}${RESET}"; }
log_ok()    { echo -e "${GREEN}  ${*}${RESET}"; }
log_warn()  { echo -e "${YELLOW}  WARN: ${*}${RESET}" >&2; }
log_error() { echo -e "${RED}  ERROR: ${*}${RESET}" >&2; }

# find predicates: return entries whose permissions DO NOT yet match the target
# (these are the entries that would be changed)
find_mismatched_dirs() {
    local target="$1"
    case "$MODE" in
        readonly)
            # dirs that have group-write, OR are missing group/other read/exec
            find -L "$target" -type d \( -perm /020 -o ! -perm -055 \) -print
            ;;
        public)
            # dirs missing group-rwx, OR missing setgid bit
            find -L "$target" -type d \( ! -perm -070 -o ! -perm /2000 \) -print
            ;;
        private)
            # dirs that still expose group/other access, or setgid inheritance
            find -L "$target" -type d \( -perm /077 -o -perm /2000 \) -print
            ;;
    esac
}

find_mismatched_files() {
    local target="$1"
    case "$MODE" in
        readonly)
            # files with group-write, OR missing group/other read
            find -L "$target" -type f \( -perm /020 -o ! -perm -044 \) -print
            ;;
        public)
            # files missing group-rw
            find -L "$target" -type f ! -perm -060 -print
            ;;
        private)
            # files that still expose group/other access
            find -L "$target" -type f -perm /077 -print
            ;;
    esac
}

# ─────────────────────────── core logic ─────────────────────────────────── #

fix_target() {
    local target="$1"

    if [[ ! -e "$target" ]]; then
        log_error "path not found: $target — skipping"
        return 1
    fi

    echo -e "${BOLD}[$MODE] $target${RESET}"

    # ── dry-run: count and optionally list ─────────────────────────────── #
    if [[ $DRY_RUN -eq 1 ]]; then
        local dir_list file_list
        dir_list=$(find_mismatched_dirs  "$target") || true
        file_list=$(find_mismatched_files "$target") || true

        local dir_count file_count
        dir_count=$(echo -n "$dir_list"  | grep -c . || true)
        file_count=$(echo -n "$file_list" | grep -c . || true)

        if [[ $dir_count -eq 0 && $file_count -eq 0 ]]; then
            log_ok "Already correct — no changes needed."
        else
            log_info "[dry-run] Would change: ${BOLD}${dir_count} dirs${RESET}${CYAN}, ${BOLD}${file_count} files${RESET}"
            if [[ $VERBOSE -eq 1 ]]; then
                [[ -n "$dir_list"  ]] && echo "$dir_list"  | sed 's/^/    dir  /'
                [[ -n "$file_list" ]] && echo "$file_list" | sed 's/^/    file /'
            fi
        fi
        echo
        return 0
    fi

    # ── apply changes ──────────────────────────────────────────────────── #
    local changed_dirs=0 changed_files=0

    # Capture mismatched paths before chmod so the count is accurate
    local dir_list file_list
    dir_list=$(find_mismatched_dirs  "$target") || true
    file_list=$(find_mismatched_files "$target") || true
    changed_dirs=$(echo -n  "$dir_list"  | grep -c . || true)
    changed_files=$(echo -n "$file_list" | grep -c . || true)

    case "$MODE" in
        readonly)
            find -L "$target" -type d -exec chmod go+rx,g-w,g+s {} +
            find -L "$target" -type f -exec chmod go+r,g-w      {} +
            ;;
        public)
            find -L "$target" -type d -exec chmod g+rwxs    {} +
            find -L "$target" -type f -exec chmod g+rw      {} +
            ;;
        private)
            find -L "$target" -type d -exec chmod go-rwx,g-s {} +
            find -L "$target" -type f -exec chmod go-rwx     {} +
            ;;
    esac

    # chgrp: best-effort (may not own all files when syncing others' uploads)
    if ! chgrp -R "$GROUP" "$target" 2>/dev/null; then
        log_warn "chgrp failed on some entries (not owner) — group unchanged for those files"
    fi

    if [[ $changed_dirs -eq 0 && $changed_files -eq 0 ]]; then
        log_ok "Already correct — no changes needed."
    else
        log_ok "Changed: ${BOLD}${changed_dirs} dirs${RESET}${GREEN}, ${BOLD}${changed_files} files${RESET}"
        if [[ $VERBOSE -eq 1 ]]; then
            [[ -n "$dir_list"  ]] && echo "$dir_list"  | sed 's/^/    dir  /'
            [[ -n "$file_list" ]] && echo "$file_list" | sed 's/^/    file /'
        fi
    fi
    echo
}

# ─────────────────────────── banner ─────────────────────────────────────── #

echo
if [[ $DRY_RUN -eq 1 ]]; then
    echo -e "${YELLOW}${BOLD}[DRY-RUN]${RESET} No files will be modified."
else
    echo -e "Applying mode: ${BOLD}$MODE${RESET}  |  group: ${BOLD}$GROUP${RESET}"
    echo    "Add a teammate:  sudo usermod -aG $GROUP <username>"
fi
echo "────────────────────────────────────────────"
echo

# ─────────────────────────── main ───────────────────────────────────────── #

exit_code=0
for target in "${TARGETS[@]}"; do
    fix_target "$target" || exit_code=1
done

exit $exit_code
