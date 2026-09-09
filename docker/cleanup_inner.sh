#!/bin/bash
# Container-side cleanup logic.
# Args: DRY_RUN [GUI_AGENT] [MODEL] [GAME]
# Runs as root inside docker, mounted at /app/game_agent
set -euo pipefail

BASE="/app/game_agent/coast"
SCREENSHOTS="$BASE/screenshots"
MEMORY="$BASE/memory"
OUTPUT_DIR="/app/output"
DRY_RUN="$1"
GUI="${2:-}"
MODEL="${3:-}"
GAME="${4:-}"

collect() {
    local base="$1"
    [[ -d "$base" ]] || return 0
    
    while IFS= read -r -d '' dir; do
        local rel="${dir#$base/}"
        local first="${rel%%/*}"
        local last="${rel##*/}"
        
        # Filter by gui_agent (first path component)
        if [[ -n "$GUI" ]]; then
            case "$first" in *"$GUI"*) ;; *) continue ;; esac
        fi
        
        # Filter by model (any path component)
        if [[ -n "$MODEL" ]]; then
            case "$rel" in *"$MODEL"*) ;; *) continue ;; esac
        fi
        
        # Filter by game (last path component)
        if [[ -n "$GAME" ]]; then
            case "$last" in *"$GAME"*) ;; *) continue ;; esac
        fi
        
        echo "$dir"
    done < <(find "$base" -mindepth 1 -type d -print0 2>/dev/null)
}

# Collect from both dirs
ss=$(collect "$SCREENSHOTS")
mem=$(collect "$MEMORY")
all=$(printf "%s\n%s" "$ss" "$mem" | { grep -v '^$' || true; } | sort -u)

# Prune subdirs of other listed dirs (rm -rf on parent covers children)
pruned=""
while IFS= read -r d; do
    [[ -n "$d" ]] || continue
    is_sub=false
    while IFS= read -r p; do
        [[ -n "$p" ]] || continue
        case "$d" in "$p"/*) is_sub=true; break ;; esac
        case "$p" in "$d"/*) pruned="${pruned#"$p"$'\n'}" ;; esac
    done <<< "$pruned"
    [[ "$is_sub" == false ]] && pruned+="$d"$'\n'
done <<< "$all"
pruned="${pruned%%$'\n'}"

[[ -z "$pruned" ]] && { echo "No matching directories found."; exit 0; }

count=$(echo "$pruned" | wc -l)

if [[ "$DRY_RUN" == "true" ]]; then
    echo "Would remove ($count directories):"
else
    echo "Removing $count directories:"
fi

echo "$pruned" | while IFS= read -r d; do
    echo "  $d"
done

if [[ "$DRY_RUN" != "true" ]]; then
    echo ""
    echo "$pruned" | xargs rm -rf
fi

if [[ -d "$OUTPUT_DIR" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "Would remove: $OUTPUT_DIR"
    else
        echo "Removing $OUTPUT_DIR ..."
        rm -rf "$OUTPUT_DIR"
    fi
fi

echo "✓ Done."
