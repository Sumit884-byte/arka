function _to_canon_path --description "Canonical existing directory path (internal)"
    set -l p (string trim -- "$argv[1]" | string replace -r '/+$' '')
    test -n "$p"; and test -d "$p"; or return 1
    realpath "$p" 2>/dev/null; or echo "$p"
end

function _to_python_resolve --description "Resolve folder via Python cache/aliases (internal)"
    set -l name (string trim -- "$argv[1]")
    test -n "$name"; or return 1
    set -l py (command -v python3 2>/dev/null)
    test -n "$py"; or return 1
    set -l src ""
    if set -q _ARKA_ROOT; and test -d "$_ARKA_ROOT/src"
        set src "$_ARKA_ROOT/src"
    else if set -q PYTHONPATH; and test -n "$PYTHONPATH"
        set src (string split : -- "$PYTHONPATH" | head -1)
    end
    test -n "$src"; or return 1
    env PYTHONPATH="$src" $py -c "
from arka.core.to_folder import resolve_folder
import sys
p = resolve_folder(sys.argv[1])
print(p if p else '', end='')
" $name 2>/dev/null
end

function _to_alias_paths --description "Expand short folder aliases (internal)"
    set -l low (string lower (string trim -- "$argv[1]"))
    switch $low
        case dev
            echo "$HOME/dev" "$HOME/Developer" "$HOME/Developers" "$HOME/development"
        case dl downloads
            echo "$HOME/Downloads"
        case docs documents
            echo "$HOME/Documents"
        case desk desktop
            echo "$HOME/Desktop"
        case pics pictures
            echo "$HOME/Pictures"
        case proj projects
            echo "$HOME/Projects"
    end
end

function to --description "cd to a folder by name (tab completes dirs under ~ and cwd)"
    set -l print_only 0
    set -l args
    for a in $argv
        switch $a
            case --print -p
                set print_only 1
            case '*'
                set -a args $a
        end
    end
    set -l name (string trim -- (string join " " $args))
    if test -z "$name"
        echo "Usage: to <folder>"
        echo "Example: to Downloads"
        echo "       to Downloads --print   # print path (for arka CLI / scripts)"
        echo "Tab-complete shows folders under ~ and the current directory."
        return 1
    end

    set -l low (string lower "$name")
    set -l raw_paths

    set -l py_hit (_to_python_resolve "$name")
    if test -n "$py_hit"
        set -l py_canon (_to_canon_path "$py_hit")
        if test $status -eq 0
            if test $print_only -eq 1
                echo "$py_canon"
                return 0
            end
            cd "$py_canon"
            return 0
        end
    end

    set -a raw_paths "$PWD/$name" "$HOME/$name"
    for alias_path in (_to_alias_paths "$name")
        set -a raw_paths "$alias_path"
    end

    for p in \
            (command -v xdg-user-dir >/dev/null; and xdg-user-dir DOWNLOADS 2>/dev/null; or echo "") \
            (command -v xdg-user-dir >/dev/null; and xdg-user-dir DOCUMENTS 2>/dev/null; or echo "") \
            (command -v xdg-user-dir >/dev/null; and xdg-user-dir DESKTOP 2>/dev/null; or echo "") \
            (command -v xdg-user-dir >/dev/null; and xdg-user-dir PICTURES 2>/dev/null; or echo "") \
            (command -v xdg-user-dir >/dev/null; and xdg-user-dir MUSIC 2>/dev/null; or echo "") \
            (command -v xdg-user-dir >/dev/null; and xdg-user-dir VIDEOS 2>/dev/null; or echo "")
        if test -n "$p"; and test -d "$p"
            if test (string lower (basename "$p")) = "$low"
                set -a raw_paths "$p"
            end
        end
    end

    for base in $HOME $PWD
        test -d "$base"; or continue
        for d in $base/*/
            test -d "$d"; or continue
            if test (string lower (basename "$d")) = "$low"
                set -a raw_paths "$d"
            end
        end
    end

    set -l candidates
    for p in $raw_paths
        set -l canon (_to_canon_path "$p")
        test $status -eq 0; or continue
        contains -- "$canon" $candidates; or set -a candidates "$canon"
    end

    if test (count $candidates) -eq 0
        for d in (find $HOME -maxdepth 4 -type d -iname "$name" 2>/dev/null | head -20)
            set -l canon (_to_canon_path "$d")
            test $status -eq 0; or continue
            contains -- "$canon" $candidates; or set -a candidates "$canon"
        end
    end

    if test (count $candidates) -eq 0
        echo (set_color red)"No folder matching: $name"(set_color normal)
        return 1
    end

    if test (count $candidates) -eq 1
        if test $print_only -eq 1
            echo "$candidates[1]"
            return 0
        end
        cd "$candidates[1]"
        return 0
    end

    set -l picked ""
    if type -q fzf; and isatty stdout; and isatty stdin
        set picked (printf '%s\n' $candidates | fzf --prompt="to $name> " --height=40% --reverse)
        if test -z "$picked"
            echo "Cancelled."
            return 1
        end
    else
        echo (set_color yellow)"Multiple folders match '$name':"(set_color normal)
        set -l i 0
        for c in $candidates
            set i (math $i + 1)
            echo "  $i) $c"
        end
        read -P "Pick number: " -l choice
        if not string match -qr '^\d+$' "$choice"; or test "$choice" -lt 1 -o "$choice" -gt (count $candidates)
            echo "Invalid choice."
            return 1
        end
        set picked $candidates[$choice]
    end

    if test $print_only -eq 1
        echo "$picked"
        return 0
    end
    cd "$picked"
end

function __fish_to_candidates --description "Directory names for 'to' tab completion"
    set -l wd (commandline -t)
    set -l wd_low (string lower "$wd")
    set -l seen
    set -l out

    for base in $HOME $PWD
        test -d "$base"; or continue
        for d in $base/*/
            test -d "$d"; or continue
            set -l bn (basename "$d")
            if test -n "$wd"; and not string match -qi "*$wd_low*" "$bn"
                continue
            end
            contains -- "$bn" $seen; and continue
            set -a seen $bn
            set -a out $bn
        end
    end

    for bn in dev dl docs desk proj Downloads Documents Desktop Pictures Music Videos Projects .config
        if test -n "$wd"; and not string match -qi "*$wd_low*" "$bn"
            continue
        end
        contains -- "$bn" $seen; and continue
        if test -d "$HOME/$bn"; or test -d "$PWD/$bn"
            set -a seen $bn
            set -a out $bn
        end
    end

    printf '%s\n' $out | sort -fu
end

complete -c to -f -a "(__fish_to_candidates)" -d "folder"
