function _to_canon_path --description "Canonical existing directory path (internal)"
    set -l p (string trim -- "$argv[1]" | string replace -r '/+$' '')
    test -n "$p"; and test -d "$p"; or return 1
    realpath "$p" 2>/dev/null; or echo "$p"
end

function to --description "cd to a folder by name (tab completes dirs under ~ and cwd)"
    set -l name (string trim -- (string join " " $argv))
    if test -z "$name"
        echo "Usage: to <folder>"
        echo "Example: to Downloads"
        echo "Tab-complete shows folders under ~ and the current directory."
        return 1
    end

    set -l low (string lower "$name")
    set -l raw_paths

    set -a raw_paths "$PWD/$name" "$HOME/$name"

    for p in \
            (xdg-user-dir DOWNLOADS 2>/dev/null) \
            (xdg-user-dir DOCUMENTS 2>/dev/null) \
            (xdg-user-dir DESKTOP 2>/dev/null) \
            (xdg-user-dir PICTURES 2>/dev/null) \
            (xdg-user-dir MUSIC 2>/dev/null) \
            (xdg-user-dir VIDEOS 2>/dev/null)
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

    for bn in Downloads Documents Desktop Pictures Music Videos Projects .config
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
