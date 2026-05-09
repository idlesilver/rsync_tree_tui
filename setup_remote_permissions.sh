#!/usr/bin/env bash
#
# setup_remote_permissions.sh
#
# Normalize access on shared storage directories.
#
# Modes (applied recursively to all content under each target):
#   pvt:pvt — owner only
#   grp:pvt — owner + group read
#   grp:grp — owner + group write
#   any:pvt — owner + group + other read
#   any:grp — owner + group write, other read
#   any:any — owner + group + other write
#
# Usage:
#   setup_remote_permissions.sh [--group GROUP] [--dry-run] [-v] <mode> <path> [<path> ...]
#   setup_remote_permissions.sh --update
#   setup_remote_permissions.sh --version
#
# Options:
#   --group G   Selected group name for grp:* modes.
#   --owner U   Only process entries owned by U (default: $OWNER or current user).
#   --dry-run   Show how many entries would change, without modifying anything.
#   -v          Verbose: list every entry whose permissions will be/were changed.
#   --update    Download latest version from GitHub and replace local file.
#   --version   Show version number.
#
# Examples:
#   # Preview what would change, without applying
#   ./setup_remote_permissions.sh --dry-run any:pvt /data/storage/sn_assets
#
#   # Lock a released dataset so teammates can only download it
#   ./setup_remote_permissions.sh any:pvt /data/storage/datasets/v1.0
#
#   # Open a staging area so teammates can upload into it
#   ./setup_remote_permissions.sh grp:grp /data/storage/datasets/staging
#
#   # Hide a work-in-progress directory from teammates
#   ./setup_remote_permissions.sh pvt /data/storage/wip_secret
#
#   # Apply to multiple paths at once
#   ./setup_remote_permissions.sh any:pvt /data/storage/v1.0 /data/storage/v1.1
#
# Run remotely from local machine:
#   ssh user@host "bash /path/to/scripts/setup_remote_permissions.sh any:pvt /remote/path"
#

set -euo pipefail

# ─────────────────────────── config ─────────────────────────────────────── #

VERSION="0.2.8"
GITHUB_RAW_URL="https://raw.githubusercontent.com/idlesilver/rsync_tree_tui/main/setup_remote_permissions.sh"

# Edit this line to persist a site-specific default, or pass --group.
GROUP="${GROUP:-}"
OWNER="${OWNER:-$(id -un)}"

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
        --owner)
            [[ $# -lt 2 ]] && { echo "ERROR: --owner requires a value" >&2; usage; }
            OWNER="$2"
            shift 2
            ;;
        --owner=*)
            OWNER="${1#*=}"
            shift
            ;;
        --dry-run)        DRY_RUN=1; shift ;;
        -v|--verbose)     VERBOSE=1; shift ;;
        --help|-h)        usage ;;
        pvt|grp:r|grp:w|any:r|any:w|pvt:pvt|grp:pvt|grp:grp|any:pvt|any:grp|any:any)
            [[ -n "$MODE" ]] && { echo "ERROR: mode specified twice ('$MODE' and '$1')"; exit 1; }
            MODE="$1"
            shift
            ;;
        rdo|pub)
            echo "ERROR: unknown mode: $1" >&2
            usage
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

case "$MODE" in
    pvt) MODE="pvt:pvt" ;;
    grp:r) MODE="grp:pvt" ;;
    grp:w) MODE="grp:grp" ;;
    any:r) MODE="any:pvt" ;;
    any:w) MODE="any:any" ;;
esac

[[ -z "$MODE"            ]] && { echo "ERROR: mode is required"; echo; usage; }
[[ ${#TARGETS[@]} -eq 0 ]] && { echo "ERROR: at least one path is required"; echo; usage; }
[[ -z "$OWNER"           ]] && { echo "ERROR: owner must not be empty"; echo; usage; }

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

find_permission_mismatches() {
    local target="$1"
    local type="$2"
    local wanted_mode="$3"
    find -L "$target" -user "$OWNER" -type "$type" -exec bash -c '
        wanted_mode="$0"
        entry_type="$1"
        shift
        for path do
            mode=$(stat -c "%a" "$path") || exit 1
            mode=$((8#$mode & 07777))
            bits=$((mode & 0777))
            special=$((mode & 07000))
            ok=1
            case "$wanted_mode:$entry_type" in
                pvt:pvt:d)
                    (( bits == 0700 && (special & 02000) == 0 )) || ok=0
                    ;;
                pvt:pvt:f)
                    (( (bits & 0600) == 0600 && (bits & 0077) == 0 && special == 0 )) || ok=0
                    ;;
                grp:pvt:d)
                    (( bits == 0750 && (special & 02000) != 0 )) || ok=0
                    ;;
                grp:pvt:f)
                    (( (bits & 0600) == 0600 && (bits & 0040) != 0 && (bits & 0020) == 0 && (bits & 0007) == 0 && special == 0 )) || ok=0
                    ;;
                grp:grp:d)
                    (( bits == 0770 && (special & 02000) != 0 )) || ok=0
                    ;;
                grp:grp:f)
                    (( (bits & 0600) == 0600 && (bits & 0060) == 0060 && (bits & 0007) == 0 && special == 0 )) || ok=0
                    ;;
                any:pvt:d)
                    (( bits == 0755 && (special & 02000) != 0 )) || ok=0
                    ;;
                any:pvt:f)
                    (( (bits & 0600) == 0600 && (bits & 0044) == 0044 && (bits & 0022) == 0 && special == 0 )) || ok=0
                    ;;
                any:grp:d)
                    (( bits == 0775 && (special & 02000) != 0 )) || ok=0
                    ;;
                any:grp:f)
                    (( (bits & 0600) == 0600 && (bits & 0060) == 0060 && (bits & 0004) != 0 && (bits & 0002) == 0 && special == 0 )) || ok=0
                    ;;
                any:any:d)
                    (( bits == 0777 && (special & 02000) != 0 )) || ok=0
                    ;;
                any:any:f)
                    (( (bits & 0600) == 0600 && (bits & 0066) == 0066 && special == 0 )) || ok=0
                    ;;
            esac
            if (( ok == 0 )); then
                printf "%s\n" "$path"
            fi
        done
    ' "$wanted_mode" "$type" {} +
}

show_skipped_owners() {
    local target="$1"
    local owner_tmp owner_err
    owner_tmp="$(mktemp)"
    owner_err="$(mktemp)"
    find -L "$target" ! -user "$OWNER" -printf '%u\n' >"$owner_tmp" 2>"$owner_err" || true
    echo "Skipped non-owned owners:"
    if [[ -s "$owner_tmp" ]]; then
        sort "$owner_tmp" | uniq -c | sort -rn |
            while read -r count owner_name; do
                printf "  %-20s %s\n" "$owner_name" "$count"
            done
    else
        echo "  (none)"
    fi
    if [[ -s "$owner_err" ]]; then
        echo "Warnings:"
        sed 's/^/  /' "$owner_err"
    fi
    rm -f "$owner_tmp" "$owner_err"
}

# find predicates: return entries whose permissions DO NOT yet match the target
# (these are the entries that would be changed)
find_mismatched_dirs() {
    local target="$1"
    case "$MODE" in
        pvt:pvt)
            find_permission_mismatches "$target" d pvt:pvt
            ;;
        grp:pvt)
            find_permission_mismatches "$target" d grp:pvt
            ;;
        grp:grp)
            find_permission_mismatches "$target" d grp:grp
            ;;
        any:pvt)
            find_permission_mismatches "$target" d any:pvt
            ;;
        any:grp)
            find_permission_mismatches "$target" d any:grp
            ;;
        any:any)
            find_permission_mismatches "$target" d any:any
            ;;
    esac
}

find_mismatched_files() {
    local target="$1"
    case "$MODE" in
        pvt:pvt)
            find_permission_mismatches "$target" f pvt:pvt
            ;;
        grp:pvt)
            find_permission_mismatches "$target" f grp:pvt
            ;;
        grp:grp)
            find_permission_mismatches "$target" f grp:grp
            ;;
        any:pvt)
            find_permission_mismatches "$target" f any:pvt
            ;;
        any:grp)
            find_permission_mismatches "$target" f any:grp
            ;;
        any:any)
            find_permission_mismatches "$target" f any:any
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
    echo "[1/3] Collecting skipped non-owned owners..."
    show_skipped_owners "$target"

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

    echo "[2/3] Applying selected group to owned entries..."
    if [[ -n "$GROUP" ]]; then
        find -L "$target" -user "$OWNER" ! -group "$GROUP" -exec chgrp "$GROUP" {} + || return 1
    else
        echo "No selected group; skipping chgrp."
    fi
    case "$MODE" in
        pvt:pvt)
            echo "[3/3] Applying chmod to owned directories/files..."
            find -L "$target" -user "$OWNER" -type d -exec chmod u+rwx,go-rwx,g-s {} + || return 1
            find -L "$target" -user "$OWNER" -type f -exec chmod u+rw,go-rwx      {} + || return 1
            ;;
        grp:pvt)
            echo "[3/3] Applying chmod to owned directories/files..."
            find -L "$target" -user "$OWNER" -type d -exec chmod u+rwx,g+rx,g-w,o-rwx,g+s {} + || return 1
            find -L "$target" -user "$OWNER" -type f -exec chmod u+rw,g+r,g-w,o-rwx       {} + || return 1
            ;;
        grp:grp)
            echo "[3/3] Applying chmod to owned directories/files..."
            find -L "$target" -user "$OWNER" -type d -exec chmod u+rwx,g+rwx,o-rwx,g+s {} + || return 1
            find -L "$target" -user "$OWNER" -type f -exec chmod u+rw,g+rw,o-rwx       {} + || return 1
            ;;
        any:pvt)
            echo "[3/3] Applying chmod to owned directories/files..."
            find -L "$target" -user "$OWNER" -type d -exec chmod u+rwx,g+rx,g-w,o+rx,o-w,g+s {} + || return 1
            find -L "$target" -user "$OWNER" -type f -exec chmod u+rw,g+r,g-w,o+r,o-w       {} + || return 1
            ;;
        any:grp)
            echo "[3/3] Applying chmod to owned directories/files..."
            find -L "$target" -user "$OWNER" -type d -exec chmod u+rwx,g+rwx,o+rx,o-w,g+s {} + || return 1
            find -L "$target" -user "$OWNER" -type f -exec chmod u+rw,g+rw,o+r,o-w       {} + || return 1
            ;;
        any:any)
            echo "[3/3] Applying chmod to owned directories/files..."
            find -L "$target" -user "$OWNER" -type d -exec chmod u+rwx,go+rwx,g+s {} + || return 1
            find -L "$target" -user "$OWNER" -type f -exec chmod u+rw,go+rw       {} + || return 1
            ;;
    esac

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
    GROUP_DISPLAY="$GROUP"
    [[ -z "$GROUP_DISPLAY" ]] && GROUP_DISPLAY="not change group"
    echo -e "Applying mode: ${BOLD}$MODE${RESET}  |  group: ${BOLD}$GROUP_DISPLAY${RESET}  |  owner: ${BOLD}$OWNER${RESET}"
    if [[ -n "$GROUP" ]]; then
        echo    "Add a teammate:  sudo usermod -aG $GROUP <username>"
    fi
fi
echo "────────────────────────────────────────────"
echo

# ─────────────────────────── main ───────────────────────────────────────── #

exit_code=0
for target in "${TARGETS[@]}"; do
    fix_target "$target" || exit_code=1
done

exit $exit_code
