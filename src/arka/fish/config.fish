# --- Auto-copy output to clipboard ---
# Usage: ac <command> [args...] - runs command and copies output to clipboard
function ac --description "Run command and auto-copy output to clipboard"
    if test (count $argv) -eq 0
        echo "Usage: ac <command> [args...]"
        echo "Example: ac ls -la"
        return 1
    end
    
    # Run command and capture output
    set -l output (eval $argv 2>&1)
    set -l cmd_status $status
    
    # Print output
    echo "$output"
    
    # Copy to clipboard if there's output
    if test -n "$output"
        if _arka_copy_to_clipboard "$output"
            echo "Output copied to clipboard"
        end
    end
    
    return $cmd_status
end

# Auto-copy abbreviations - these commands auto-copy output to clipboard
# Usage: just type the command normally (ll, la, cat, etc.)
function _setup_auto_copy_abbreviations
    abbr -a ll 'ac ls -alF'
    abbr -a la 'ac ls -A'
    abbr -a l 'ac ls -CF'
    abbr -a cat 'ac cat'
    abbr -a head 'ac head'
    abbr -a tail 'ac tail'
    abbr -a grep 'ac grep'
    abbr -a find 'ac find'
    abbr -a diff 'ac diff'
    abbr -a history 'ac history'
    abbr -a pwd 'ac pwd'
    abbr -a date 'ac date'
    abbr -a whoami 'ac whoami'
end

if status is-interactive
    _setup_auto_copy_abbreviations
end

# --- Arka: Fish shell agent configuration ---
# This file manages the environment, aliases, and an advanced AI Agent system.
# 
# How it works:
# 1. Aliases & Environment: Standard productivity shortcuts and PATH setups.
# 2. Agent Skills: Modular Fish functions (e.g., weather, speedtest, browse_web) 
#    that perform specific terminal or GUI tasks.
# 3. agent: The central orchestrator. It checks if a command is a known 
#    skill or a valid shell command. If unrecognized, it uses Gemini/Groq 
#    LLMs to interpret the natural language and map it to the best skill.
# 4. Web Automation: The 'browse_web' skill uses Playwright and an LLM-to-Code 
#    bridge to automate browser actions (clicking, scrolling, etc.) via NL.
# 5. Dependency Management: 'install_skill_deps' bootstraps the system on first run.

# brightnessctl set 100%
if type -q zoxide
    zoxide init fish | source
end

# --- Arka install root (package bundle or legacy $_ARKA_ROOT) ---
function _arka_root --description "Arka scripts directory (bundled in pip package)"
    if set -q INSTALL_HOME; and test -n "$INSTALL_HOME"
        echo $INSTALL_HOME
        return
    end
    set -l here (path dirname (status filename))
    while test -n "$here"; and test "$here" != "/"
        if test -f "$here/bin/arka_chat.py"
            echo $here
            return
        end
        if test -f "$here/arka_chat.py"
            echo $here
            return
        end
        if test -f "$here/pyproject.toml"; and test -d "$here/src/arka"
            echo $here
            return
        end
        set here (path dirname $here)
    end
    echo "$HOME/.config/fish"
end

function _arka_config_dir --description "User config dir (.env, secrets)"
    if set -q CONFIG_DIR; and test -n "$CONFIG_DIR"
        echo $CONFIG_DIR
        return
    end
    if test -f "$HOME/.config/fish/.env"
        echo "$HOME/.config/fish"
        return
    end
    mkdir -p "$HOME/.config/arka"
    echo "$HOME/.config/arka"
end


function _arka_bin --description "Python entry shims (internal)"
    if test -d "$_ARKA_ROOT/bin"
        echo "$_ARKA_ROOT/bin"
        return
    end
    echo "$_ARKA_ROOT"
end

function _arka_py_script --description "Resolve python entry script (internal)"
    set -l name $argv[1]
    set -l dir (_arka_bin)
    if test -f "$dir/$name"
        echo "$dir/$name"
        return
    end
    if test -f "$_ARKA_ROOT/$name"
        echo "$_ARKA_ROOT/$name"
    end
end

function _arka_shell_script --description "Resolve shell runtime script (internal)"
    set -l name $argv[1]
    for candidate in \
            "$_ARKA_ROOT/src/arka/fish/scripts/$name" \
            "$_ARKA_ROOT/fish/scripts/$name" \
            "$_ARKA_ROOT/scripts/$name" \
            "$_ARKA_ROOT/$name"
        if test -f "$candidate"
            echo "$candidate"
            return
        end
    end
end

function _arka_requirements --description "Chat requirements path (internal)"
    for candidate in \
            "$_ARKA_ROOT/src/arka/requirements/chat.txt" \
            "$_ARKA_ROOT/requirements/chat.txt" \
            "$_ARKA_ROOT/arka_chat_requirements.txt"
        if test -f "$candidate"
            echo "$candidate"
            return
        end
    end
end

set -g _ARKA_ROOT (_arka_root)
set -g _ARKA_CFG (_arka_config_dir)

function _arka_env_key --description "Canonical .env key (strip legacy ARKA_ prefix)"
    set -l key $argv[1]
    if string match -qr '^ARKA_' -- $key
        set key (string replace -r '^ARKA_' '' -- $key)
        if test "$key" = HOME
            set key INSTALL_HOME
        end
    end
    echo $key
end

# --- Environment Setup ---
if test -f "$_ARKA_CFG/.env"
    for line in (cat "$_ARKA_CFG/.env" | grep -v '^#' | grep -v '^\s*$')
        set -l kv (string split -m 1 "=" $line)
        if test (count $kv) -eq 2
            set -l val (string trim -c '"' $kv[2])
            set val (string replace -r '#.*$' '' -- "$val" | string trim)
            set -l key (_arka_env_key $kv[1])
            set -gx $key $val
        end
    end
end
# Dev checkout .env — fill in vars not already set (e.g. REMOTE_TOKEN in repo root)
if test -f "$_ARKA_ROOT/.env"; and test "$_ARKA_ROOT/.env" != "$_ARKA_CFG/.env"
    for line in (cat "$_ARKA_ROOT/.env" | grep -v '^#' | grep -v '^\s*$')
        set -l kv (string split -m 1 "=" $line)
        if test (count $kv) -eq 2
            set -l key (_arka_env_key $kv[1])
            if not set -q $key
                set -l val (string trim -c '"' $kv[2])
                set val (string replace -r '#.*$' '' -- "$val" | string trim)
                set -gx $key $val
            end
        end
    end
end

function _arka_src_pythonpath --description "Directory to put on PYTHONPATH for arka imports (internal)"
    if test -d "$_ARKA_ROOT/src/arka"
        echo "$_ARKA_ROOT/src"
        return
    end
    if test -f "$_ARKA_ROOT/../__init__.py"
        echo (path resolve "$_ARKA_ROOT/..")
        return
    end
end

function _arka_apply_pythonpath --description "Export PYTHONPATH so bundled scripts can import arka (internal)"
    set -l src (_arka_src_pythonpath)
    test -z "$src"; and return
    if set -q PYTHONPATH; and test -n "$PYTHONPATH"
        for part in (string split : -- "$PYTHONPATH")
            if test "$part" = "$src"
                return
            end
        end
        set -gx PYTHONPATH "$src:$PYTHONPATH"
    else
        set -gx PYTHONPATH "$src"
    end
end

_arka_apply_pythonpath

function _arka_platform_init --description "Load cached platform profile (detect once on first run)"
    set -l env_platform ""
    if set -q PLATFORM; and test -n "$PLATFORM"
        set env_platform "$PLATFORM"
    end
    set -l pf "$_ARKA_CFG/platform.env"
    if not test -f "$pf"
        set -l vpy $_ARKA_ROOT/venv-arka/bin/python3
        set -l py python3
        test -x $vpy; and set py $vpy
        if test -f (_arka_py_script arka_platform.py)
            $py (_arka_py_script arka_platform.py) ensure 2>/dev/null
        end
    end
    if test -f "$pf"
        for line in (cat "$pf" | grep -v '^#' | grep -v '^\s*$')
            set -l kv (string split -m 1 "=" $line)
            if test (count $kv) -eq 2
                set -gx $kv[1] $kv[2]
            end
        end
    end
    if test -n "$env_platform"
        set -gx PLATFORM $env_platform
        set -gx _PLATFORM $env_platform
    else if set -q PLATFORM; and test -n "$PLATFORM"
        set -gx _PLATFORM $PLATFORM
    else if not set -q _PLATFORM
        set -l uname (uname -s)
        if test "$uname" = Darwin
            set -gx _PLATFORM macos
        else if test "$uname" = Linux
            set -gx _PLATFORM linux
        else
            set -gx _PLATFORM unknown
        end
    end
end

_arka_platform_init

function _arka_is_macos --description "True on macOS (cached from first-run detect)"
    test "$_PLATFORM" = macos
end

function _arka_is_linux --description "True on Linux (cached from first-run detect)"
    test "$_PLATFORM" = linux
end

function _arka_is_windows --description "True on Windows (cached from first-run detect)"
    test "$_PLATFORM" = windows
end

function _arka_agent_platform_label --description "Platform label for LLM agent prompts (internal)"
    if _arka_is_macos
        echo "macOS (Darwin)"
    else if _arka_is_linux
        echo "Linux"
    else if _arka_is_windows
        echo "Windows"
    else
        echo (uname -s 2>/dev/null)
    end
end

function _arka_agent_platform_hint --description "Platform-specific shell guidance for LLM prompts (internal)"
    if _arka_is_macos
        echo "Host: macOS. Prefer: sw_vers, sysctl, vm_stat, df -h, system_profiler, ipconfig getifaddr, ps aux, open, brew. Avoid: lscpu, free, lspci, lsb_release, apt, /proc, systemctl."
    else if _arka_is_linux
        echo "Host: Linux. Prefer: lscpu, free -h, df -h, lspci, uname, /proc/cpuinfo, apt/dnf/pacman, ss, systemctl, journalctl."
    else if _arka_is_windows
        echo "Host: Windows. Prefer: PowerShell/Get-ComputerInfo where available; many fish skills are Linux/macOS oriented."
    else
        echo "Host: unknown. Use portable commands: uname, df, ps, python3."
    end
end

function _arka_platform_ui_shortcuts --description "Platform UI/keyboard shortcut hints for how-to answers (internal)"
    if _arka_is_macos
        echo "macOS UI: red close button top-left; Cmd+W closes tab/window; Cmd+Q quits app; Cmd+Tab switches apps."
    else if _arka_is_linux
        echo "Linux UI: close/minimize/maximize usually top-right; Ctrl+W closes tab; Alt+F4 closes window."
    else if _arka_is_windows
        echo "Windows UI: X/minimize/maximize top-right; Ctrl+W closes tab; Alt+F4 closes window."
    else
        echo "Answer only for the user's current OS."
    end
end

function _arka_open --description "Open URL or file with the system default handler (cross-platform)"
    set -l target $argv[1]
    test -z "$target"; and return 1
    if _arka_is_macos
        open "$target" >/dev/null 2>&1 &
        disown 2>/dev/null
        return 0
    end
    if command -v xdg-open >/dev/null
        xdg-open "$target" 2>/dev/null &
        disown 2>/dev/null
        return 0
    end
    return 1
end

function _arka_copy_to_clipboard --description "Copy text to system clipboard (cross-platform)"
    set -l text "$argv[1]"
    test -z "$text"; and return 1
    if set -q CLIPBOARD_COPY; and test -n "$CLIPBOARD_COPY"
        if test "$CLIPBOARD_COPY" = xclip
            printf '%s' "$text" | xclip -selection clipboard 2>/dev/null
            return $status
        end
        printf '%s' "$text" | $CLIPBOARD_COPY
        return $status
    end
    if _arka_is_macos; and command -v pbcopy >/dev/null
        printf '%s' "$text" | pbcopy
        return 0
    end
    if command -v wl-copy >/dev/null
        printf '%s' "$text" | wl-copy
        return 0
    end
    if command -v xclip >/dev/null
        printf '%s' "$text" | xclip -selection clipboard 2>/dev/null
        return 0
    end
    if command -v xsel >/dev/null
        printf '%s' "$text" | xsel --clipboard --input 2>/dev/null
        return 0
    end
    if _arka_is_windows; and command -v clip.exe >/dev/null
        printf '%s' "$text" | clip.exe
        return 0
    end
    return 1
end

function _arka_paste_from_clipboard --description "Read text from system clipboard (cross-platform)"
    if set -q CLIPBOARD_PASTE; and test -n "$CLIPBOARD_PASTE"
        if test "$CLIPBOARD_PASTE" = xclip
            xclip -selection clipboard -o 2>/dev/null
            return $status
        end
        if test "$CLIPBOARD_PASTE" = xsel
            xsel --clipboard --output 2>/dev/null
            return $status
        end
        $CLIPBOARD_PASTE
        return $status
    end
    if _arka_is_macos; and command -v pbpaste >/dev/null
        pbpaste
        return 0
    end
    if command -v wl-paste >/dev/null
        wl-paste --no-newline
        return 0
    end
    if command -v xclip >/dev/null
        xclip -selection clipboard -o 2>/dev/null
        return 0
    end
    if command -v xsel >/dev/null
        xsel --clipboard --output 2>/dev/null
        return 0
    end
    if _arka_is_windows; and command -v powershell.exe >/dev/null
        powershell.exe -NoProfile -Command "Get-Clipboard -Raw" 2>/dev/null
        return 0
    end
    return 1
end

function _arka_copy_stdin_to_clipboard --description "Pipe stdin to system clipboard (cross-platform)"
    if set -q CLIPBOARD_COPY; and test -n "$CLIPBOARD_COPY"
        if test "$CLIPBOARD_COPY" = xclip
            xclip -selection clipboard 2>/dev/null
            return $status
        end
        $CLIPBOARD_COPY
        return $status
    end
    if _arka_is_macos; and command -v pbcopy >/dev/null
        pbcopy
        return 0
    end
    if command -v wl-copy >/dev/null
        wl-copy
        return 0
    end
    if command -v xclip >/dev/null
        xclip -selection clipboard 2>/dev/null
        return 0
    end
    if command -v xsel >/dev/null
        xsel --clipboard --input 2>/dev/null
        return 0
    end
    if _arka_is_windows; and command -v clip.exe >/dev/null
        clip.exe
        return 0
    end
    return 1
end

function _arka_generate_password_once --description "Generate one-time password via Python secrets (internal)"
    set -l length 16
    if test (count $argv) -ge 1; and string match -qr '^[0-9]+$' -- $argv[1]
        set length $argv[1]
    end
    set -l py (_arka_python)
    set -l out ($py (_arka_py_script arka_password_vault.py) once --length $length 2>&1)
    if test $status -ne 0
        echo $out >&2
        return 1
    end
    set -l password ""
    set -l out_length $length
    for line in $out
        if string match -qr '^__PASSWORD__=' -- $line
            set password (string replace '__PASSWORD__=' '' $line)
        else if string match -qr '^__LENGTH__=' -- $line
            set out_length (string replace '__LENGTH__=' '' $line)
        end
    end
    if test -z "$password"
        echo (set_color red)"Password generation failed."(set_color normal) >&2
        return 1
    end
    echo (set_color --bold blue)"━━━ Password Generator ━━━"(set_color normal)
    echo (set_color --bold green)"  $password"(set_color normal)
    echo (set_color brblack)"  Length: $out_length characters (one-time, not saved)"(set_color normal)
    if _arka_copy_to_clipboard "$password"
        echo (set_color brblack)"  ✓ Copied to clipboard"(set_color normal)
    end
    echo ""
    echo "Save with a name: generate_password save <name> [length]"
    echo "Store your own:  generate_password set <name> <password>"
end

function _arka_config_mtime --description "Modification time of config.fish (internal)"
    set -l cfg "$_ARKA_ROOT/config.fish"
    test -f "$cfg"; or return 1
    if _arka_is_macos
        stat -f %m "$cfg" 2>/dev/null
    else
        stat -c %Y "$cfg" 2>/dev/null
    end
end

function _arka_env_mtime --description "Modification time of .env (internal)"
    set -l env "$_ARKA_CFG/.env"
    test -f "$env"; or return 1
    if _arka_is_macos
        stat -f %m "$env" 2>/dev/null
    else
        stat -c %Y "$env" 2>/dev/null
    end
end

function _arka_reload_stamp --description "Combined stamp for config + env (internal)"
    set -l cfg (_arka_config_mtime); or set cfg 0
    set -l env (_arka_env_mtime); or set env 0
    echo "$cfg:$env"
end

function _arka_reload_config --description "Reload config.fish in the current shell (internal)"
    set -l cfg "$_ARKA_ROOT/config.fish"
    if not test -f "$cfg"
        echo (set_color red)"Missing $cfg"(set_color normal) >&2
        return 1
    end
    source "$cfg"
    set -g _ARKA_RELOAD_STAMP (_arka_reload_stamp)
    return 0
end

function _arka_maybe_reload --description "Auto-reload when config.fish or .env changed (internal)"
    set -l stamp (_arka_reload_stamp)
    if not set -q _ARKA_RELOAD_STAMP
        set -g _ARKA_RELOAD_STAMP $stamp
        return 0
    end
    if test "$stamp" = "$_ARKA_RELOAD_STAMP"
        return 0
    end
    set -g _ARKA_RELOAD_STAMP $stamp
    echo (set_color cyan)"↻ Arka updated — reloading…"(set_color normal) >&2
    source "$_ARKA_ROOT/config.fish"
    set -g _ARKA_RELOAD_STAMP (_arka_reload_stamp)
end

function _arka_reload_command --description "arka reload — refresh shell + optional listener (internal)"
    set -l restart_listen 0
    set -l sync_dev 0
    for flag in $argv
        switch $flag
            case listen -l listener mic
                set restart_listen 1
            case dev sync sync-bundle bundle
                set sync_dev 1
            case all
                set restart_listen 1
                set sync_dev 1
        end
    end

    if test $sync_dev -eq 1; and test -f "$_ARKA_ROOT/scripts/sync_bundled.py"
        echo (set_color cyan)"→ sync bundled"(set_color normal)
        python3 "$_ARKA_ROOT/scripts/sync_bundled.py"
    end

    _arka_reload_config
    echo (set_color green)"✔ Arka reloaded in this shell."(set_color normal)

    if test $restart_listen -eq 1
        if functions -q _agent_listen_stop
            _agent_listen_stop 2>/dev/null
            sleep 0.3
            _agent_listen_start
            echo (set_color green)"✔ Wake listener restarted (latest Python + config)."(set_color normal)
        end
    else
        echo "Tip: arka reload --listen  picks up arka_wake.py and other Python changes too."
    end
    return 0
end


# --- Environment Variables ---
set --export BUN_INSTALL "$HOME/.bun"
set --export PATH $BUN_INSTALL/bin $PATH

set -gx PNPM_HOME "/home/s/.local/share/pnpm"
if not string match -q -- $PNPM_HOME $PATH
    set -gx PATH "$PNPM_HOME" $PATH
end

# --- Abbreviations & Aliases ---
if status is-interactive
    abbr -a update 'sudo apt update'
    abbr -a up 'sudo apt update && sudo apt upgrade -y && sudo apt autoremove -y'
    
    alias ls='ls --color=auto'
    alias grep='grep --color=auto'
    alias ll='ls -alF'
    alias la='ls -A'
    alias l='ls -CF'

    # System Maintenance Aliases
    alias update='sudo apt update'
    alias upgrade='sudo apt upgrade'
    alias install='sudo apt install'
    alias remove='sudo apt remove'
    alias up='sudo apt update; and sudo apt upgrade -y; and sudo apt autoremove -y'
    alias pro='cd /home/s/Projects/python/products'
    alias ani='/home/s/Antigravity\ IDE/antigravity-ide --no-sandbox'
    alias an='/home/s/Antigravity-x64  && ./antigravity --no-sandbox'
    alias rplay='/home/s/Projects/python/venv/bin/python3 /home/s/Projects/python/medialistplay.py'


    # Project and Python Aliases
    alias p='cd /home/s/Projects'
    alias a='source ./venv/bin/activate.fish && source ./.venv/bin/activate.fish'

    # Spyder Aliases
    alias spyder='/home/s/.local/spyder-6/envs/spyder-runtime/bin/spyder'
    alias uninstall-spyder='/home/s/.local/spyder-6/uninstall-spyder.sh'

    # Help Function to print aliases
    function h
        echo "--- MY ALIASES ---"
        echo "p           -> Go to Projects"
        echo "a           -> Activate Venv (Fish version)"
        echo "up          -> System Updates"
        echo "pro         -> Product Folder"
        echo "spyder      -> Launch Spyder"
        echo "ai-models   -> List AI providers and limits"
        echo "ai-status   -> Show current AI provider and model"
        echo "ai-pref     -> Set preferred AI provider/model"
        echo "ai-skill-model -> Per-skill / per-profile model choices"
        echo "select_model   -> Recommend LLM models from PC resources"
        echo "rplay       -> Play media in current folder"
        echo "mkalias     -> Create and persist a new alias"
        echo ""
        echo "--- AI TOOLS ---"
        echo "ask <q>     -> Get a shell command from AI (macOS/Linux)"
        echo "talk <q>    -> Chat with AI"
        echo "ctx ask <q> -> Ask AI with directory context"
        echo "agent <request> -> NL command/skill router"
        echo "arka start     -> start everything (remote + wake listener)"
        echo "arka stop      -> stop everything"
        echo "arka autostart install -> survive reboot (systemd)"
        echo "arka phone-env -> print Termux config (one-time setup)"
        echo "arka serve     -> remote server (phone STT/TTS, PC agent)"
        echo "arka listen    -> wake listener only"
        echo "arka reload    -> pick up config changes (auto on next arka/agent command)"
        echo "arka reload --listen -> also restart wake listener after Python edits"
        echo "arka debug     -> wake listener with STT debug (or: arka listen debug)"
        echo "arka voice     -> HF speech-to-speech agent (mic → Arka skills → speaker)"
        echo "arka speak-lang -> choose voice language (hi-IN, ta-IN, en-IN, ...)"
        echo "arka speak <q>   -> answer a question and read it aloud"
        echo "arka brief       -> daily weather + news headlines"
        echo "arka aie status  -> Artificial Internet Enhancements"
        echo "arka yt-bulk     -> YouTube playlist/channel bulk downloader"
        echo "arka summarize   -> transcribe + summarize a local video/audio file"
        echo "arka compute       -> show CPU/GPU workers auto-detected"
        echo "arka queue list  -> background deep-search queue"
        echo "arka wifi        -> current Wi-Fi network"
        echo "arka stop     -> stop wake listener"
        echo "agent_hear <speech> -> agent with wake-word stripping (STT)"
        echo "AGENT_NAME=arka in .env (default); arka listen to start wake word; AGENT_WAKE_AUTO=1 for auto-start"
        echo "agent_plan <goal> -> AI plans & runs multi-step tasks"
        echo "goal <goal>       -> Autonomous goal agent (Arka or Butterfish Goal Mode)"
        echo "agent_loop  -> AI loop: run cmd → read output → fix & retry (-n max)"
        echo "loop <goal> -> Same as agent_loop (uses goal engine when GOAL_ENGINE=auto)"
        echo "skills      -> Show safe vs dangerous commands"
        echo "fix         -> AI fixes your last failed command"
        echo ""
        echo "--- AGENT SKILLS (use with agent) ---"
        echo "play_spotify    -> Play music (xdg-open default Brave / desktop app)"
        echo "spotify_brave_debug -> Optional: Brave CDP for DOM fallback only"
        echo "spotify_control -> Control Spotify (MPRIS + DOM play)"
        echo "  (Spotipy/Web API needs Premium; free web uses playerctl + Playwright DOM)"
        echo "play_song       -> Play song by name search, else random"
        echo "stop_music      -> Stop/pause song (mpv + MPRIS players)"
        echo "weather         -> Current weather"
        echo "timer <time>    -> Countdown timer"
        echo "remind <when>   -> Reminder later (idle/shutdown aware)"
        echo "screenshot      -> Take a screenshot"
        echo "describe_screen -> 10s countdown, capture screen, describe (vision)"
        echo "system_info     -> System overview"
        echo "search_web <q>  -> Google search"
        echo "open_urls       -> Open one or more URLs"
        echo "open_finance    -> Open top financial sites"
        echo "open_news       -> Open top news sites"
        echo "git_summary     -> Git project overview"
        echo "browse_web <q>  -> AI-powered web automation (visit, click, scroll)"
        echo "disk_usage      -> Storage analysis"
        echo "disk_breakdown  -> Space by videos, pictures, documents, etc."
        echo "pdf_ingest      -> Ingest a PDF (auto-starts PrivateGPT + Qdrant)"
        echo "pdf_ask         -> Ask/summarize ingested documents (--doc NAME optional)"
        echo "pdf_list        -> List ingested PDF documents"
        echo "port_scan       -> Show open ports"
        echo "speedtest       -> Internet speed test"
        echo "clipboard       -> Copy/paste from terminal"
        echo "todo            -> Quick task list"
        echo "translate       -> Translate text via AI"
        echo "survive_lang    -> Travel survival phrases (native → target language)"
        echo "pr_check        -> PR diff, CI status, explain failures, babysit until green"
        echo "generate_password -> Secure password"
        echo "ip_info         -> Public IP & location"
        echo "open_project    -> Find & open projects"
        echo "activate_venv   -> Activate virtual environment"
        echo "create_venv     -> Create new virtual environment"
        echo "write_script    -> Create a Python script"
        echo "run_script      -> Run a Python script"
        echo "create_folder   -> Create directories"
        echo "list_folders    -> List subfolder names"
        echo "show_folder     -> Show folder contents"
        echo "list_files      -> List files in a folder"
        echo "search_files    -> Find files by name"
        echo "open_file       -> Open a file"
        echo "play_movie      -> Play local video in Clapper (by title or folder)"
        echo "ollama_run      -> Run local LLM with Ollama"
        echo "lint_python     -> Lint Python code (flake8/pylint/ruff)"
        echo "------------------"
    end
    # Virtual Environment Activation
    function a
        if test -f ./venv/bin/activate.fish
            source ./venv/bin/activate.fish && source ./.venv/bin/activate.fish
        else
            echo "No venv/bin/activate.fish found"
        end
    end
    
    # Python installation alias
    function i
        uv pip install $argv; and pip freeze > requirements.txt
    end

    # Alias to create a persistent alias
    function mkalias --description "Create a persistent alias"
        if test (count $argv) -lt 2
            echo "Usage: mkalias <alias_name> <command>"
            return 1
        end
        alias $argv[1] $argv[2..-1]
        funcsave $argv[1]
    end

    # --- Temporary alias toggling ---
    # noalias: undefine all custom aliases & abbreviations for this session
    function noalias --description "Temporarily disable all aliases and abbreviations"
        # Erase known aliases (defined as functions by `alias`)
        for name in ls grep ll la l update upgrade install remove up pro ani an rplay p a spyder uninstall-spyder
            functions --erase $name 2>/dev/null
        end
        # Erase all abbreviations
        for abbr_name in (abbr --list)
            abbr --erase $abbr_name 2>/dev/null
        end
        set -g __noalias_active 1
        echo (set_color yellow)"⚡ All aliases & abbreviations disabled for this session."(set_color normal)
        echo (set_color cyan)"   Run "(set_color --bold)"realias"(set_color cyan)" to restore them."(set_color normal)
    end

    # realias: restore all aliases & abbreviations without opening a new terminal
    function realias --description "Restore all aliases and abbreviations (undo noalias)"
        source $_ARKA_ROOT/config.fish
        set -e __noalias_active
        echo (set_color green)"✔ Aliases & abbreviations restored."(set_color normal)
    end
end
# --- AI Functions ---

# Local Ollama helper
function ai
    ollama run llama3.2:1b $argv
end

function _json_escape
    # Escape text safely for JSON payloads.
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
end

# Multi-Provider AI Wrapper (Gemini + Groq)
function ask --description "Query AI APIs with cross-provider fallback"
    argparse 'p/provider=' 'm/model=' -- $argv
    or return

    set -l prompt "$argv"
    set -l provider_req $_flag_p
    set -l model_req $_flag_m
    
    if test -z "$prompt"
        echo "Usage: ask [-p provider] [-m model] Your prompt here"
        return 1
    end

    # Use preference if set and no override provided
    if test -z "$provider_req" -a -n "$AI_PREFERRED_PROVIDER"
        set provider_req "$AI_PREFERRED_PROVIDER"
    end
    if test -z "$model_req" -a -n "$AI_PREFERRED_MODEL"
        set model_req "$AI_PREFERRED_MODEL"
    end

    set -l aliases_list (alias | string join "\n")
    set -l plat (_arka_agent_platform_label)
    set -l plat_hint (_arka_agent_platform_hint)
    set -l system_prompt "You are a cross-platform shell expert on $plat (fish shell). Respond ONLY with the requested command. No markdown, no backticks.
$plat_hint
Available Shell Aliases:
$aliases_list
Use symbolic reasoning to match and use the most appropriate shell alias if one exists for the requested task.
CRITICAL NOTE ON ALIASES:
- `ls` is aliased to `eza`. `eza` does NOT support standard `ls` sorting flags like `-t`, `-ltr`, or `-lt`. To sort by newest/recency, use `eza --sort newest` (or `eza -snew`). To sort by oldest, use `eza --sort oldest` (or `eza -sold`). Alternatively, bypass the alias by running standard `ls` via `command ls -lt` or `command ls -ltr`.
- `cat` is aliased to `batcat`."

    if test -n "$provider_req" -a -n "$model_req"
        set -lx LLM_FALLBACK "$provider_req:$model_req"
    else if test -n "$provider_req"
        set -lx LLM_FALLBACK "$provider_req:gemini-2.0-flash,$provider_req:llama-3.3-70b-versatile"
    end

    set -l result (_agent_llm_complete "$system_prompt" "$prompt" 0.1 chat)
    if test -n "$result"
        echo $result
        if type -q pbcopy
            echo $result | pbcopy
        else if type -q wl-copy
            echo $result | wl-copy
        else if type -q xclip
            echo $result | xclip -selection clipboard
        end
        return 0
    end
    # --- Offline Fallback Logic ---
    set -l clean_prompt (string lower "$prompt")
    set -l fallback_cmd ""

    # Check local offline fallback heuristics dictionary
    if string match -qr '(?i)(torchvision::nms|operator torchvision|modulenotfounderror|importerror.*torch)' "$clean_prompt"
        set fallback_cmd "uv pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu"
    else if string match -qr '(extract|untar|unzip|tar\s+-x)' "$clean_prompt"
        set fallback_cmd "tar -xvf archive.tar.gz"
    else if string match -qr '(compress|zip|tar\s+-c)' "$clean_prompt"
        set fallback_cmd "tar -czvf archive.tar.gz folder/"
    else if string match -qr '(find|search.*file)' "$clean_prompt"
        set fallback_cmd "find . -name \"*filename*\""
    else if string match -qr '(find|search.*text|grep)' "$clean_prompt"
        set fallback_cmd "grep -rn \"search_term\" ."
    else if string match -qr '(disk|free.*space)' "$clean_prompt"
        set fallback_cmd "df -h"
    else if string match -qr '(?i)\b(mem|ram)\b' "$clean_prompt"
        if _arka_is_macos
            set fallback_cmd "vm_stat; sysctl hw.memsize"
        else
            set fallback_cmd "free -h"
        end
    else if string match -qr '(?i)\b(listening|open\s+port|ss\s+-tlnp)\b|\bport\s+(scan|check|in\s+use)\b' "$clean_prompt"
        if _arka_is_macos
            set fallback_cmd "lsof -iTCP -sTCP:LISTEN -P -n | head -20"
        else
            set fallback_cmd "ss -tlnp"
        end
    else if string match -qr '(process|ps.*aux)' "$clean_prompt"
        set fallback_cmd "ps aux | grep name"
    else if string match -qr '(ip.*addr|my.*ip)' "$clean_prompt"
        if _arka_is_macos
            set fallback_cmd "ipconfig getifaddr en0"
        else
            set fallback_cmd "hostname -I"
        end
    else if string match -qr '(copy.*folder|cp.*dir)' "$clean_prompt"
        set fallback_cmd "cp -r source_dir/ dest_dir/"
    else if string match -qr '(permission|chmod|execute)' "$clean_prompt"
        set fallback_cmd "chmod +x script.sh"
    else if string match -qr '(history|run.*last)' "$clean_prompt"
        set fallback_cmd "history | head -n 20"
    end

    if test -n "$fallback_cmd"
        echo (set_color yellow)"💡 [Local Heuristics Fallback]"(set_color normal)
        echo "$fallback_cmd"
        if command -v xclip &>/dev/null
            echo "$fallback_cmd" | xclip -selection clipboard
        end
        return 0
    end

    # Try tldr if installed
    set -l first_arg (string split -f 1 " " "$prompt")
    if command -v tldr &>/dev/null
        echo (set_color yellow)"💡 [Local TLDR Fallback]"(set_color normal)
        tldr "$first_arg" 2>/dev/null; and return 0
    end

    # Try apropos as final resort
    if command -v apropos &>/dev/null
        echo (set_color yellow)"💡 [Local Apropos Search Fallback]"(set_color normal)
        apropos "$prompt" | head -n 10
        return 0
    end

    echo "Fail: Check keys/connection."
    return 1
end

function ctx --description "Ask AI with current directory context and optional depth"
    argparse 'd/depth=' -- $argv
    or return

    set -l depth 1
    if set -q _flag_d
        set depth $_flag_d
        if not string match -qr '^[0-9]+$' -- $depth
            echo "Error: depth must be a positive integer"
            return 1
        end
    end

    if test (count $argv) -lt 1
        echo "Usage: ctx ask [-d depth] Your prompt here"
        return 1
    end

    set -l subcmd $argv[1]
    set argv $argv[2..-1]

    if test "$subcmd" != "ask"
        echo "Unsupported ctx command: $subcmd"
        echo "Usage: ctx ask [-d depth] Your prompt here"
        return 1
    end

    set -l prompt "$argv"
    if test -z "$prompt"
        echo "Usage: ctx ask [-d depth] Your prompt here"
        return 1
    end

    set -l tree_output (find . -maxdepth $depth -mindepth 1 -print | sort | sed 's#^\./##')
    if test -z "$tree_output"
        set tree_output "(no files found within depth $depth)"
    end

    set -l context "Directory contents (depth $depth):\n$tree_output\n\nUse the current directory structure to answer the prompt. You may provide a command if appropriate, but do not return only the command. Give a helpful response.\n\n$prompt"
    talk "$context"
end

function _fix_offline_suggestion --description "Suggest fix command from failed output (internal)"
    set -l output "$argv[2]"

    if string match -qr '(?i)(torchvision::nms|operator torchvision|does not exist|incompatible.*torch|cannot import name.*torchvision)' "$output"
        echo uv pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
        return 0
    end

    set -l mod (string match -r "(?i)ModuleNotFoundError: No module named '([^']+)'" -- "$output")
    if test (count $mod) -ge 2
        echo uv pip install $mod[2]
        return 0
    end

    set -l mod2 (string match -r "(?i)ImportError: No module named '([^']+)'" -- "$output")
    if test (count $mod2) -ge 2
        echo uv pip install $mod2[2]
        return 0
    end

    return 1
end

function fix --description "Automatically send last command and its error to AI for correction"
    # Get the last executed command from history
    set -l last_cmd $history[1]
    
    # Ensure there is a command to fix
    if test -z "$last_cmd"
        echo "No command history found."
        return 1
    end

    echo "Analyzing last command: $last_cmd"

    # Capture both stdout and stderr of the last command safely
    set -l cmd_output (eval $last_cmd 2>&1)

    set -l suggestion (_fix_offline_suggestion "$last_cmd" "$cmd_output")
    if test $status -eq 0; and test -n "$suggestion"
        printf '%s%s%s\n' (set_color green) "💡 Suggested fix:" (set_color normal)
        echo "$suggestion"
        if command -v xclip >/dev/null
            echo "$suggestion" | xclip -selection clipboard
            echo (set_color brblack)"  (copied to clipboard)"(set_color normal)
        end
        return 0
    end

    set -l prompt "The command '$last_cmd' failed with output:\n$cmd_output\n\nProvide the corrected command to fix it. Respond with ONLY the command."
    
    ask "$prompt"
end

function _agent_tts_parler_needed --description "True if Indic Parler-TTS daemon should run (internal)"
    if set -q AGENT_TTS
        switch $AGENT_TTS
            case parler indic local
                return 0
            case '*'
                return 1
        end
    end
    return 1
end

function _agent_tts_parler_start --description "Start Indic Parler-TTS daemon (internal)"
    if not _agent_tts_parler_needed
        return 0
    end
    python3 (_arka_py_script indic_tts.py) start 2>/dev/null
end

function _agent_tts_parler_stop --description "Stop Indic Parler-TTS daemon (internal)"
    python3 (_arka_py_script indic_tts.py) stop 2>/dev/null
end

function _arka_speak_lang --description "Set or list Arka voice language (internal)"
    if test (count $argv) -eq 0
        python3 (_arka_py_script indic_tts.py) langs
        echo ""
        set -l cur en-IN
        if set -q SPEAK_LANG
            set cur $SPEAK_LANG
        end
        echo "Current: $cur"
        echo "Usage: arka speak-lang hi-IN   (aliases: hi, ta, en, ...)"
        return 0
    end
    set -l code (python3 (_arka_py_script indic_tts.py) resolve-lang $argv[1] 2>/dev/null)
    if test -z "$code"
        echo (set_color red)"Unknown language: $argv[1]"(set_color normal)
        echo "Run: arka speak-lang   for supported codes"
        return 1
    end
    set -gx SPEAK_LANG $code
    set -gx SARVAM_TTS_LANG $code
    if test -f $_ARKA_CFG/.env
        set -l env_content (cat $_ARKA_CFG/.env | grep -v '^SPEAK_LANG=')
        printf "%s\n" $env_content > $_ARKA_CFG/.env
    end
    echo "SPEAK_LANG=$code" >> $_ARKA_CFG/.env
    echo (set_color green)"Arka voice language: $code"(set_color normal)
end

function _arka_speak_voice --description "Set or list Arka neural voice (internal)"
    if test (count $argv) -eq 0
        python3 (_arka_py_script edge_speak.py) voices
        return 0
    end
    set -l voice $argv[1]
    set -gx SPEAK_VOICE $voice
    if test -f $_ARKA_CFG/.env
        set -l env_content (cat $_ARKA_CFG/.env | grep -v '^SPEAK_VOICE=')
        printf "%s\n" $env_content > $_ARKA_CFG/.env
    end
    echo "SPEAK_VOICE=$voice" >> $_ARKA_CFG/.env
    echo (set_color green)"Arka voice: $voice"(set_color normal)
    speak_aloud "Hello, this is how I sound now."
end

function _arka_usage_autostart_ensure --description "Install autostart for usage tracker on login (internal)"
    if set -q USAGE_TRACK
        test "$USAGE_TRACK" = 0 -o "$USAGE_TRACK" = false; and return 0
    end
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_usage.py)
    if _arka_is_macos
        set -l label com.arka.usage
        set -l plist ~/Library/LaunchAgents/$label.plist
        mkdir -p ~/Library/LaunchAgents
        printf '%s\n' \
            '<?xml version="1.0" encoding="UTF-8"?>' \
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
            '<plist version="1.0">' \
            '<dict>' \
            '  <key>Label</key><string>'$label'</string>' \
            '  <key>ProgramArguments</key>' \
            '  <array>' \
            '    <string>'$py'</string>' \
            '    <string>'$script'</string>' \
            '    <string>track</string>' \
            '  </array>' \
            '  <key>RunAtLoad</key><true/>' \
            '  <key>KeepAlive</key><true/>' \
            '  <key>StandardOutPath</key><string>'$HOME'/.cache/fish-agent/arka_usage.log</string>' \
            '  <key>StandardErrorPath</key><string>'$HOME'/.cache/fish-agent/arka_usage.log</string>' \
            '</dict>' \
            '</plist>' \
            > $plist
        launchctl bootout gui/(id -u) $plist 2>/dev/null
        launchctl bootstrap gui/(id -u) $plist 2>/dev/null; or launchctl load $plist 2>/dev/null
        return 0
    end
    if not _arka_is_linux
        return 0
    end
    set -l dir ~/.config/autostart
    set -l desktop $dir/arka-usage.desktop
    mkdir -p $dir
    printf '%s\n' \
        '[Desktop Entry]' \
        'Type=Application' \
        'Name=Arka usage tracker' \
        'Comment=App and website time tracking for Arka' \
        "Exec=$py $script start" \
        'Hidden=false' \
        'NoDisplay=true' \
        'X-GNOME-Autostart-enabled=true' \
        'X-GNOME-Autostart-Phase=Applications' \
        > $desktop
end

function _arka_remind_autostart_ensure --description "Install autostart for reminder daemon on login (internal)"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_remind.py)
    if _arka_is_macos
        set -l label com.arka.remind
        set -l plist ~/Library/LaunchAgents/$label.plist
        mkdir -p ~/Library/LaunchAgents
        printf '%s\n' \
            '<?xml version="1.0" encoding="UTF-8"?>' \
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
            '<plist version="1.0">' \
            '<dict>' \
            '  <key>Label</key><string>'$label'</string>' \
            '  <key>ProgramArguments</key>' \
            '  <array>' \
            '    <string>'$py'</string>' \
            '    <string>'$script'</string>' \
            '    <string>start</string>' \
            '  </array>' \
            '  <key>RunAtLoad</key><true/>' \
            '  <key>StandardOutPath</key><string>'$HOME'/.cache/fish-agent/arka_remind.log</string>' \
            '  <key>StandardErrorPath</key><string>'$HOME'/.cache/fish-agent/arka_remind.log</string>' \
            '</dict>' \
            '</plist>' \
            > $plist
        launchctl bootout gui/(id -u) $plist 2>/dev/null
        launchctl bootstrap gui/(id -u) $plist 2>/dev/null; or launchctl load $plist 2>/dev/null
        return 0
    end
    if not _arka_is_linux
        return 0
    end
    set -l dir ~/.config/autostart
    set -l desktop $dir/arka-remind.desktop
    mkdir -p $dir
    printf '%s\n' \
        '[Desktop Entry]' \
        'Type=Application' \
        'Name=Arka reminders' \
        'Comment=Background reminder daemon for Arka' \
        "Exec=$py $script start" \
        'Hidden=false' \
        'NoDisplay=true' \
        'X-GNOME-Autostart-enabled=true' \
        > $desktop
end

function _arka_usage_status --description "App/website usage tracker status (internal)"
    set -l pidfile ~/.cache/fish-agent/arka_usage.pid
    set -l logfile ~/.cache/fish-agent/arka_usage.log
    if test -f $pidfile
        set -l pid (cat $pidfile 2>/dev/null)
        if test -n "$pid"; and kill -0 $pid 2>/dev/null
            set -l mode "app + website"
            if set -q WEB_TRACK; and test "$WEB_TRACK" = 0 -o "$WEB_TRACK" = false
                set mode app
            end
            echo (set_color green)"Usage tracker: running ($mode, pid $pid)"(set_color normal)
            echo (set_color brblack)"  log: $logfile  |  stop: arka usage stop"(set_color normal)
            return 0
        end
    end
    echo (set_color yellow)"Usage tracker: stopped"(set_color normal)
    if _arka_is_macos
        echo "Starts on login when USAGE_TRACK=1, or: arka usage start"
    else if _arka_is_linux
        echo "Starts on login when USAGE_TRACK=1, or: arka usage start"
    else
        echo "Start manually: arka usage start"
    end
    return 1
end

function _arka_start_all --description "Start remote server + wake listener (internal)"
    set -l quiet 0
    if test (count $argv) -ge 1; and test "$argv[1]" = --quiet
        set quiet 1
    end
    if test $quiet -eq 0
        set -l call (_agent_call_name)
        echo (set_color cyan)"Starting $call ..."(set_color normal)
        bash (_arka_shell_script arka_boot.sh) start
        sleep 1
        _arka_status_all
    else
        env START_QUIET=1 bash (_arka_shell_script arka_boot.sh) start 2>/dev/null
    end
end

function _arka_stop_all --description "Stop all Arka background services (internal)"
    bash (_arka_shell_script arka_boot.sh) stop
    _agent_usage_stop
    echo (set_color green)"Stopped all Arka services"(set_color normal)
end

function _arka_status_all --description "Status of remote + wake listener (internal)"
    _agent_remote_status; or true
    echo ""
    _agent_listen_status; or true
    echo ""
    _arka_usage_status; or true
end

function _arka_autostart_install --description "Enable Arka on PC boot via systemd (internal)"
    set -l unit_dir ~/.config/systemd/user
    set -l fish_dir $_ARKA_ROOT
    set -l home $HOME
    mkdir -p $unit_dir
    chmod +x $fish_dir/arka_boot.sh

    printf '%s\n' \
        '[Unit]' \
        'Description=Arka remote server (phone STT/TTS, PC agent)' \
        'After=network-online.target' \
        'Wants=network-online.target' \
        '' \
        '[Service]' \
        "EnvironmentFile=-$fish_dir/.env" \
        "ExecStart=/usr/bin/python3 $fish_dir/arka_remote_server.py serve" \
        'Restart=on-failure' \
        'RestartSec=5' \
        '' \
        '[Install]' \
        'WantedBy=default.target' \
        > $unit_dir/arka-remote.service

    printf '%s\n' \
        '[Unit]' \
        'Description=Arka wake-word listener' \
        'After=network-online.target sound.target' \
        'Wants=network-online.target' \
        '' \
        '[Service]' \
        "EnvironmentFile=-$fish_dir/.env" \
        "ExecStartPre=$fish_dir/venv-arka/bin/python3 $fish_dir/arka_wake.py --check" \
        "ExecStart=$fish_dir/venv-arka/bin/python3 $fish_dir/arka_wake.py" \
        'Restart=on-failure' \
        'RestartSec=10' \
        '' \
        '[Install]' \
        'WantedBy=default.target' \
        > $unit_dir/arka-listen.service

    systemctl --user daemon-reload

    set -l enable_remote 1
    if set -q REMOTE_AUTO; and test "$REMOTE_AUTO" = 0 -o "$REMOTE_AUTO" = false
        set enable_remote 0
    end
    set -l enable_listen 0
    if set -q AGENT_WAKE_AUTO; and test "$AGENT_WAKE_AUTO" = 1 -o "$AGENT_WAKE_AUTO" = true
        set enable_listen 1
    end

    if test $enable_remote -eq 1
        systemctl --user enable --now arka-remote.service
    end
    if test $enable_listen -eq 1
        systemctl --user enable --now arka-listen.service
    end

    set -l enable_whatsapp 0
    if set -q WHATSAPP_AUTO; and test "$WHATSAPP_AUTO" = 1 -o "$WHATSAPP_AUTO" = true
        set enable_whatsapp 1
    end
    if test $enable_whatsapp -eq 1
        printf '%s\n' \
            '[Unit]' \
            'Description=Arka WhatsApp inbox listener' \
            'After=network-online.target graphical-session.target' \
            'Wants=network-online.target' \
            '' \
            '[Service]' \
            "EnvironmentFile=-$fish_dir/.env" \
            "ExecStart=$fish_dir/venv-arka/bin/python3 $fish_dir/arka_whatsapp_inbox.py listen" \
            'Restart=on-failure' \
            'RestartSec=15' \
            '' \
            '[Install]' \
            'WantedBy=default.target' \
            > $unit_dir/arka-whatsapp.service
        systemctl --user enable --now arka-whatsapp.service
    end

    set -l enable_usage 1
    if set -q USAGE_TRACK; and test "$USAGE_TRACK" = 0 -o "$USAGE_TRACK" = false
        set enable_usage 0
    end

    if test $enable_usage -eq 1
        set -l py (_arka_python)
        if _arka_is_linux
            printf '%s\n' \
                '[Unit]' \
                'Description=Arka app and website usage tracker' \
                'After=graphical-session.target' \
                'PartOf=graphical-session.target' \
                '' \
                '[Service]' \
                "EnvironmentFile=-$fish_dir/.env" \
                "ExecStart=$py $fish_dir/arka_usage.py track" \
                'Restart=on-failure' \
                'RestartSec=30' \
                '' \
                '[Install]' \
                'WantedBy=graphical-session.target' \
                > $unit_dir/arka-usage.service
            systemctl --user enable --now arka-usage.service
        end
        _arka_usage_autostart_ensure
    end

    loginctl enable-linger (whoami) 2>/dev/null

    echo (set_color green)"Autostart installed — Arka runs after reboot (no terminal needed)"(set_color normal)
    echo "  remote:  systemctl --user status arka-remote"
    echo "  listen:  systemctl --user status arka-listen"
    if test $enable_usage -eq 1
        echo "  usage:   systemctl --user status arka-usage"
    end
    echo "  disable: arka autostart remove"
end

function _arka_autostart_remove --description "Disable Arka systemd autostart (internal)"
    systemctl --user disable --now arka-remote.service 2>/dev/null
    systemctl --user disable --now arka-listen.service 2>/dev/null
    systemctl --user disable --now arka-usage.service 2>/dev/null
    systemctl --user disable --now arka-whatsapp.service 2>/dev/null
    rm -f ~/.config/systemd/user/arka-remote.service ~/.config/systemd/user/arka-listen.service ~/.config/systemd/user/arka-usage.service ~/.config/systemd/user/arka-whatsapp.service
    rm -f ~/.config/autostart/arka-usage.desktop
    systemctl --user daemon-reload
    echo (set_color green)"Autostart removed"(set_color normal)
end

function _arka_phone_env --description "Print Termux env file for phone (internal)"
    set -l port 8765
    if set -q REMOTE_PORT
        set port $REMOTE_PORT
    end
    set -l ip (python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except OSError:
    print('127.0.0.1')
" 2>/dev/null)
    set -l token (test -n "$REMOTE_TOKEN"; and echo $REMOTE_TOKEN; or echo $REMOTE_TOKEN)
    set -l lang hi-IN
    if set -q SPEAK_LANG
        set lang $SPEAK_LANG
    end

    echo "# Paste on Termux:  mkdir -p ~/.arka && nano ~/.arka/env"
    echo "export REMOTE_URL=\"http://$ip:$port\""
    if test -n "$token"
        echo "export REMOTE_TOKEN=\"$token\""
    end
    echo "export SPEAK_LANG=\"$lang\""
    echo ""
    echo "# One-time Termux setup:"
    echo "#   pkg install python termux-api openssh"
    echo "#   mkdir -p ~/arka && scp YOU@PC_IP:(_arka_py_script arka_phone.py) ~/arka/"
    echo "#   cp $_ARKA_ROOT/termux-boot-arka.sh ~/.termux/boot/arka.sh  # optional boot ping"
end

function _agent_remote_start --description "Start Arka remote server for phone STT/TTS (internal)"
    set -l py (_arka_python)
    set -l pidfile ~/.cache/fish-agent/arka_remote.pid
    set -l logfile ~/.cache/fish-agent/arka_remote.log

    if test -f "$pidfile"
        set -l pid (cat "$pidfile" 2>/dev/null)
        if test -n "$pid"; and kill -0 "$pid" 2>/dev/null
            _agent_remote_status
            return 0
        end
    end

    mkdir -p ~/.cache/fish-agent
    echo (set_color cyan)"Starting Arka remote server (phone STT/TTS → PC agent)..."(set_color normal)
    set -l src "$_ARKA_ROOT/src"
    if test -d "$src/arka"
        env PYTHONPATH="$src" $py -m arka.integrations.remote_server serve >>"$logfile" 2>&1 &
    else
        $py -m arka.integrations.remote_server serve >>"$logfile" 2>&1 &
    end
    disown
    sleep 2

    if test -f "$pidfile"; and kill -0 (cat "$pidfile") 2>/dev/null
        _agent_remote_status
        return 0
    end

    echo (set_color red)"Remote server failed to start. Check: $logfile"(set_color normal)
    tail -8 "$logfile" 2>/dev/null
    return 1
end

function _agent_remote_stop --description "Stop Arka remote server (internal)"
    set -l pidfile ~/.cache/fish-agent/arka_remote.pid
    python3 (_arka_py_script arka_remote_server.py) stop 2>/dev/null
    if test -f "$pidfile"
        set -l pid (cat "$pidfile" 2>/dev/null)
        kill "$pid" 2>/dev/null
        rm -f "$pidfile"
    end
    echo (set_color green)"Arka remote server stopped"(set_color normal)
end

function _agent_remote_status --description "Arka remote server status (internal)"
    set -l pidfile ~/.cache/fish-agent/arka_remote.pid
    set -l logfile ~/.cache/fish-agent/arka_remote.log
    set -l port 8765
    if set -q REMOTE_PORT
        set port $REMOTE_PORT
    end

    set -l ip (python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except OSError:
    print('127.0.0.1')
" 2>/dev/null)

    if test -f "$pidfile"
        set -l pid (cat "$pidfile" 2>/dev/null)
        if test -n "$pid"; and kill -0 "$pid" 2>/dev/null
            echo (set_color green)"Arka remote: running (pid $pid)"(set_color normal)
            echo (set_color cyan)"  Phone UI:  http://$ip:$port/"(set_color normal)
            echo (set_color brblack)"  log: $logfile  |  stop: arka remote-stop"(set_color normal)
            if set -q REMOTE_TOKEN; or set -q REMOTE_TOKEN
                set -l tok (test -n "$REMOTE_TOKEN"; and echo $REMOTE_TOKEN; or echo $REMOTE_TOKEN)
                echo (set_color brblack)"  token: $tok"(set_color normal)
            else
                echo (set_color yellow)"  token: see $logfile (auto-generated on first start)"(set_color normal)
            end
            echo ""
            echo "Termux: python arka_phone.py --url http://$ip:$port listen"
            return 0
        end
    end
    echo (set_color yellow)"Arka remote: stopped"(set_color normal)
    echo "Start with: arka serve"
    return 1
end

function arka_serve --description "Start Arka remote server (phone voice → PC agent)"
    _agent_remote_start
end

function arka_remote_stop --description "Stop Arka remote server"
    _agent_remote_stop
end

function arka_remote_status --description "Show Arka remote server URL and token"
    _agent_remote_status
end

function speak_aloud --description "Speak text aloud (Sarvam → neural edge → Parler → macOS say → system)"
    set -l py (_arka_python)
    set -l text ""
    if test (count $argv) -gt 0
        set text (string join " " $argv)
    else if not isatty stdin
        set text (cat | string join " ")
    end
    if test -z "$text"
        echo "Usage: speak_aloud <text> or echo <text> | speak_aloud"
        return 1
    end

    set -l tts auto
    if set -q AGENT_TTS
        set tts $AGENT_TTS
    end

    set -l try_sarvam 0
    set -l try_edge 0
    set -l try_parler 0
    switch $tts
        case sarvam
            set try_sarvam 1
            if test -z "$SARVAM_API_KEY"
                set try_edge 1
            end
        case edge neural
            set try_edge 1
        case parler indic local
            set try_parler 1
        case system spd espeak
            # system only
        case '*'
            if test -n "$SARVAM_API_KEY"
                set try_sarvam 1
            else
                set try_edge 1
            end
    end

    if test $try_sarvam -eq 1; and test -n "$SARVAM_API_KEY"
        $py (_arka_py_script sarvam_speak.py) "$text" 2>/dev/null
        if test $status -eq 0
            return 0
        end
        if not set -q ARKA_TTS_QUIET
            echo (set_color yellow)"Sarvam TTS failed — trying neural voice"(set_color normal) >&2
        end
        set try_edge 1
    end

    if test $try_edge -eq 1
        $py (_arka_py_script edge_speak.py) speak "$text" 2>/dev/null
        if test $status -eq 0
            return 0
        end
        if not set -q ARKA_TTS_QUIET
            echo (set_color yellow)"Neural TTS failed — trying Indic Parler"(set_color normal) >&2
        end
        set try_parler 1
    end

    if test $try_parler -eq 1
        $py (_arka_py_script indic_tts.py) speak "$text" 2>/dev/null
        if test $status -eq 0
            return 0
        end
        if not set -q ARKA_TTS_QUIET
            echo (set_color yellow)"Indic Parler-TTS failed — falling back to system voice"(set_color normal) >&2
        end
    end

    if _arka_is_macos; and command -v say >/dev/null
        # Built-in macOS speech (always available; no mpv/edge-tts required)
        set -l voice ""
        if set -q SPEAK_VOICE; and test -n "$SPEAK_VOICE"
            set voice $SPEAK_VOICE
        else if set -q SPEAK_LANG
            switch $SPEAK_LANG
                case hi hi-IN
                    set voice Veena
                case bn bn-IN
                    set voice Rishi
                case zh-CN zh zh-cn chinese
                    set voice Ting-Ting
                case ja ja-JP japanese
                    set voice Kyoko
                case ko ko-KR korean
                    set voice Yuna
                case fr fr-FR french
                    set voice Amelie
                case de de-DE german
                    set voice Anna
                case es es-ES spanish
                    set voice Monica
            end
        end
        if test -n "$voice"
            say -v "$voice" -r 190 "$text"
        else
            say -r 190 "$text"
        end
        return $status
    end

    if command -v spd-say >/dev/null
        spd-say "$text"
        return $status
    end
    if command -v espeak-ng >/dev/null
        espeak-ng -s 165 "$text"
        return $status
    end
    if command -v espeak >/dev/null
        espeak -s 165 "$text"
        return $status
    end
    echo "Error: run 'arka tts-setup', set SARVAM_API_KEY, or install mpv + spd-say."
    return 1
end

# --- Agent System ---

# Classify a command as safe (return 0) or dangerous (return 1)
function __agent_classify --description "Classify shell command safety"
    set -l cmd "$argv"
    set -l first_word (string split -f 1 " " "$cmd")

    # DANGEROUS: root privilege, deletion, destructive ops
    set -l dangerous_patterns \
        "sudo " "doas " "su " "su -" \
        " rm " " rm -" "| rm" \
        "rmdir " "unlink " \
        " mv " \
        "dd " "mkfs " "fdisk " "parted " \
        "kill " "pkill " "killall " \
        "chmod " "chown " \
        "shutdown " "reboot " "poweroff " "halt " \
        "systemctl stop" "systemctl disable" "systemctl mask" \
        "git push -f" "git push --force" "git reset --hard" "git clean -f" \
        "> /dev/" ">/dev/" \
        "sed -i" \
        ":(){" "fork bomb"

    for pattern in $dangerous_patterns
        if string match -qi -- "*$pattern*" "$cmd"
            return 1
        end
    end

    set -l dangerous_first_words rm rmdir sudo doas su mv dd mkfs kill pkill killall chmod chown shutdown reboot poweroff halt
    for word in $dangerous_first_words
        if test "$first_word" = "$word"
            return 1
        end
    end

    # Everything else is a SKILL (safe) — including installs
    return 0
end

function _arka_security_enabled --description "True when symbolic security checks are on (internal)"
    test "$SECURITY" = 0; and return 1
    return 0
end

function _arka_verify_web_query --description "Block prompt-injection in web/search queries (internal)"
    if not _arka_security_enabled
        return 0
    end
    if test "$SECURITY_WEB" = 0
        return 0
    end
    set -l q "$argv[1]"
    test -z "$q"; and return 0
    set -l py (_arka_python)
    set -l err ($py (_arka_py_script arka_security.py) verify-query (string escape --style=script -- $q) 2>&1)
    if test $status -ne 0
        echo (set_color red)"🛡 $err"(set_color normal) >&2
        return 1
    end
    return 0
end

function _arka_confirm_risky_action --description "Confirm install/delete/send/download before execution (internal)"
    argparse 'y/yes' -- $argv
    or return 1
    if not _arka_security_enabled
        return 0
    end
    if test "$SECURITY_ACTIONS" = 0
        return 0
    end
    set -l cmd (string trim -- "$argv[1]")
    test -z "$cmd"; and return 0
    set -l py (_arka_python)
    set -l line ($py (_arka_py_script arka_security.py) check-action (string escape --style=script -- $cmd) 2>/dev/null | string trim)
    test -z "$line"; and return 0
    set -l parts (string split \t "$line")
    set -l sec_level (string upper "$parts[1]")
    switch $sec_level
        case BLOCK
            echo (set_color red)"🛡 Blocked: $parts[3]"(set_color normal) >&2
            return 1
        case CONFIRM
            if set -q _flag_y
                echo (set_color yellow)"⚠ Auto-approved ($parts[2]): $cmd"(set_color normal) >&2
                return 0
            end
            echo (set_color yellow)"🛡 $parts[3]"(set_color normal) >&2
            echo (set_color brblack)"  Action: $cmd"(set_color normal) >&2
            read -P (set_color --bold cyan)"Proceed? [y/N]: "(set_color normal) -l confirm
            if string match -qi 'y*' "$confirm"
                return 0
            end
            return 1
        case OK
            return 0
    end
    return 0
end

function _arka_run_shell_string --description "Run a shell command string; apostrophe-safe for simple commands (internal)"
    set -l cmd (string trim -- "$argv[1]")
    test -z "$cmd"; and return 1
    if string match -qr '[|;&<>$`()]' -- "$cmd"
        eval $cmd
    else
        set -l tokens (string split " " -- "$cmd")
        test (count $tokens) -eq 0; and return 1
        set -l bin $tokens[1]
        set -e tokens[1]
        $bin $tokens
    end
end

function _agent_exec_shell_cmd --description "Execute shell only; prompt if __agent_classify says dangerous"
    argparse 'y/yes' -- $argv
    or return
    set -l cmd (string trim -- "$argv[1]")
    if test -z "$cmd"
        return 1
    end
    if set -q _flag_y
        if not _arka_confirm_risky_action -y "$cmd"
            return 1
        end
    else
        if not _arka_confirm_risky_action "$cmd"
            return 1
        end
    end
    if not __agent_classify "$cmd"
        if set -q _flag_y
            echo (set_color yellow)"⚠ Running dangerous command (auto-approved): $cmd"(set_color normal)
        else
            echo (set_color red)"⚠ Warning: dangerous command: $cmd"(set_color normal)
            read -P (set_color --bold cyan)"Run anyway? [y/N]: "(set_color normal) -l confirm
            if not string match -qi 'y*' "$confirm"
                return 1
            end
        end
    end
    _arka_run_shell_string "$cmd"
end

# --- Modular fallback utilities (shared by agent, media, Spotify, screenshots) ---

function _fallback_try --description "Run functions in order with shared args; stop on first success"
    set -l funcs
    set -l args
    set -l collect funcs
    for a in $argv
        if test "$a" = --
            set collect args
            continue
        end
        if test "$collect" = funcs
            set -a funcs $a
        else
            set -a args $a
        end
    end
    for fn in $funcs
        if not functions -q $fn
            continue
        end
        $fn $args
        if test $status -eq 0
            return 0
        end
    end
    return 1
end

function _cmd_chain --description "Run first shell line whose binary exists and exits 0"
    for line in $argv
        set -l bin (string split -f 1 " " -- "$line")
        if command -v $bin &>/dev/null
            eval $line
            if test $status -eq 0
                return 0
            end
        end
    end
    return 1
end

function _arka_match_third_party_skill --description "Match NL text to third-party plugin invocation (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_skills.py) match "$argv[1]" 2>/dev/null
end

function _arka_match_learned_route --description "Match NL text to user-learned route (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_route_learn.py) match "$argv[1]" 2>/dev/null | string trim
end

function _agent_is_route_learn_request --description "True if user wants to teach/list learned routes (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_route_learn.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_learn_management --description "Build route_learn management command from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_route_learn.py) route "$argv[1]" 2>/dev/null | string trim)
    echo $route
end

function _arka_is_builtin_skill --description "True if built-in fish skill name (internal)"
    contains -- "$argv[1]" (_agent_all_skills)
end

function _arka_third_party_skill_names --description "Names of installed third-party plugins (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_skills.py) list-names 2>/dev/null
end

function _arka_is_third_party_skill --description "True if installed third-party plugin (internal)"
    set -l word $argv[1]
    set -l names (_arka_third_party_skill_names)
    contains -- "$word" $names
end

function _arka_load_third_party_skills --description "Source fish-based plugin skills (internal)"
    set -l py (_arka_python)
    for f in ($py (_arka_py_script arka_skills.py) fish-sources 2>/dev/null)
        if test -f "$f"
            source "$f"
        end
    end
end

function _arka_run_third_party_skills --description "Run third-party plugin via arka_skills.py (internal)"
    set -l name $argv[1]
    set -e argv[1]
    set -l py (_arka_python)
    $py (_arka_py_script arka_skills.py) run "$name" $argv
end

function _agent_is_skill --description "True if word is a registered agent skill"
    set -l word $argv[1]
    contains -- "$word" (_agent_available_skills)
end

function _agent_shlex_split --description "Shell-safe argv split for google dispatch (internal)"
    set -l py (_arka_python)
    $py -c "import shlex,sys; print('\n'.join(shlex.split(sys.argv[1])))" (string escape --style=script -- $argv[1])
end

function _agent_strip_quotes --description "Strip wrapping single/double quotes (internal)"
    set -l t "$argv[1]"
    set t (string trim -c "'" -- "$t")
    set t (string trim -c '"' -- "$t")
    echo $t
end

function _agent_dispatch_one --description "Run one skill by name or shell via _agent_exec_shell_cmd"
    set -l cmd_trim (string trim -- "$argv[1]")
    test -z "$cmd_trim"; and return 1
    if not _arka_confirm_risky_action $argv[2..] "$cmd_trim"
        return 1
    end
    set -l tokens (string split " " -- "$cmd_trim")
    set -l cleaned
    for t in $tokens
        set -a cleaned (_agent_strip_quotes "$t")
    end
    set -l tokens $cleaned
    set -l first $tokens[1]
    if test "$first" = google
        echo (set_color cyan)"▶ Running skill: $cmd_trim"(set_color normal)
        set -lx ARKA_SKILL google
        set -l py (_arka_python)
        set -l gargv (_agent_shlex_split "$cmd_trim")
        if test (count $gargv) -lt 2
            return 1
        end
        set -e gargv[1]
        $py (_arka_py_script arka_google.py) $gargv
        return $status
    end
    if _arka_is_builtin_skill "$first"
        if test "$first" = pdf_ask
            echo (set_color brblack)"▶ "(set_color --bold cyan)"PDF ask"(set_color brblack)" — "(set_color normal)"$cmd_trim"
        else if test "$first" = describe_image
            set -l args $tokens[2..-1]
            if test (count $args) -ge 1; and test "$args[1]" = describe
                set -e args[1]
            end
            set -l src (string join " " $args | string replace -r " 'Summarize this chart\.'\$" "" | string trim)
            echo (set_color cyan)"▶ describe_image "(set_color --bold)"$src"(set_color normal)
        else
            echo (set_color cyan)"▶ Running skill: $cmd_trim"(set_color normal)
        end
        set -e tokens[1]
        set -lx ARKA_SKILL $first
        if test (count $tokens) -gt 0
            $first -- $tokens
        else
            $first
        end
        return $status
    end
    if _arka_is_third_party_skill "$first"
        echo (set_color cyan)"▶ Third-party skill: $cmd_trim"(set_color normal)
        set -e tokens[1]
        _arka_run_third_party_skills $first $tokens
        return $status
    end
    echo (set_color cyan)"▶ Running: $cmd_trim"(set_color normal)
    _agent_exec_shell_cmd "$cmd_trim"
    return $status
end

function _agent_dispatch --description "Run interpreted string: && all, || until success, or single"
    set -l interpreted (string trim -- "$argv[1]")
    test -z "$interpreted"; and return 1

    if string match -q '*&&*' -- "$interpreted"
        for cmd in (string split "&&" -- "$interpreted")
            _agent_dispatch_one (string trim -- "$cmd"); or return 1
        end
        return 0
    end

    if string match -q '*||*' -- "$interpreted"
        for cmd in (string split "||" -- "$interpreted")
            _agent_dispatch_one (string trim -- "$cmd"); and return 0
        end
        return 1
    end

    _agent_dispatch_one "$interpreted"
    return $status
end

function _agent_all_skills --description "Canonical registered agent skill names (internal)"
    printf '%s\n' \
        play_spotify spotify_control play_song stop_music play_youtube play_movie \
        weather hyperlocal_weather timer screenshot set_wallpaper system_info \
        search_web open_urls open_finance open_news git_summary disk_usage disk_breakdown \
        pdf_ask pdf_ingest pdf_ingest_dir pdf_list doc_ask doc_ingest doc_list drawing_ask describe_image describe_screen port_scan speedtest clipboard todo translate survive_lang \
        generate_password ip_info open_project create_folder list_folders show_folder \
        store_password pass \
        open_file list_files search_files find_files_by_size browse_web activate_venv create_venv fix_venv \
        write_script run_script ollama_run lint_python cheat qr_code shorten_url \
        crypto_price currency_convert convert currency kalshi pomodoro sports_score live_scores system_monitor excuse bored open_app create_skill \
        calculate_bmi send_whatsapp whatsapp_listen search_stores download_file extract_and_run \
        create_desktop_app fix_graphics_driver install_app install_apt install_brew install_flatpak \
        install_snap install_package install_uv stock_analysis stock macro emotion \
        auto_click auto_copy decrypt_pdf classify_files cleanup_downloads watch_zip monitor_x post_x \
        generate_image generate_thumbnail generate_video compose_video compose_slides convert_media pdf_tools chart ascii_art youtube_transcript youtube_download yt_download media_transcript transcribe_media summarize_url daily_brief wifi_info \
        folder_summarize playlist_summarize youtube_research yt_research find_videos codebase_ingest \
        agent_remember agent_recall agent_memory agent_trace agent_why agent_last \
        agent_resume agent_research agent_nudge agent_watch agent_routine agent_fanout \
        agent_code agent_handoff agent_browser transcript_ask media_ask \
        meeting_agent study_agent inbox_agent compare_agent product_reviewer price_check profession pr_check github_repo competitions route_learn \
        bookmarks repo_health generate_data data_gen data_ask ask_data query_data analyze_data docker_status clipboard_history mcp agent_hub gemini_cli \
        arka_ask semantic_memory supermemory speak_research voice_session handoff_notify remind routines predictions stock \
        rag_setup rag_status voice_agent wake_control \
        agent_ask web_answer deep_web_answer web_essay platform_howto calc chat_reset set_location files_preference_help google \
        select_model model_select best_model model_advisor \
        personalize \
        nearby_places map_download error_helper deep_queue app_usage internet_enhance aie \
        youtube_bulk yt_bulk
end

function _agent_available_skills --description "Registered agent skill names (internal)"
    _agent_all_skills
    _arka_third_party_skill_names
end

function _ollama_api_base --description "Ollama host for client API calls (127.0.0.1, not 0.0.0.0 bind)"
    set -l host "$OLLAMA_HOST"
    if test -z "$host"
        echo "127.0.0.1:11434"
        return
    end
    echo (string replace "0.0.0.0" "127.0.0.1" -- "$host")
end

function _ollama_chat_model --description "Preferred Ollama chat model (minimax cloud, then local)"
    set -l default $argv[1]
    test -z "$default"; and set default "minimax-m2.5:cloud"
    if test -n "$OLLAMA_CHAT_MODEL"
        echo $OLLAMA_CHAT_MODEL
        return
    end
    set -l base (_ollama_api_base)
    set -l names (curl -s --connect-timeout 2 "http://$base/api/tags" | jq -r '.models[].name' 2>/dev/null)
    for pref in minimax-m2.5:cloud minimax-m2:cloud qwen3:8b llama3.2:1b
        if string match -qr -- "$pref" $names
            echo $pref
            return
        end
    end
    set -l local_only (printf '%s\n' $names | grep -v -i ':cloud' | head -1)
    if test -n "$local_only"
        echo $local_only
    else
        set -l cloud (printf '%s\n' $names | head -1)
        test -n "$cloud"; and echo $cloud; or echo $default
    end
end

function _arka_venv_python --description "First venv-arka python with agno installed (internal)"
    set -l seen
    set -l candidates
    set -a candidates "$_ARKA_ROOT/venv-arka/bin/python3"
    set -l here $_ARKA_ROOT
    for _i in (seq 1 8)
        set -a candidates "$here/venv-arka/bin/python3"
        if test -f "$here/pyproject.toml"; and test -d "$here/src/arka"
            break
        end
        set here (path dirname $here)
        test "$here" = /; and break
    end
    set -a candidates "$HOME/.config/fish/venv-arka/bin/python3"
    if set -q CONFIG_DIR; and test -n "$CONFIG_DIR"
        set -a candidates "$CONFIG_DIR/venv-arka/bin/python3"
    end
    for vpy in $candidates
        contains -- "$vpy" $seen; and continue
        set -a seen $vpy
        test -x "$vpy"; or continue
        if $vpy -c "import agno" 2>/dev/null
            echo "$vpy"
            return
        end
    end
end

function _arka_ensure_venv --description "Create venv-arka + chat deps when agno missing (internal)"
    set -l vpy (_arka_venv_python)
    test -n "$vpy"; and return 0
    echo (set_color cyan) "→ arka setup (venv-arka + agno, ddgs, …)" (set_color normal) >&2
    set -l bootstrap python3
    if test -f "$_ARKA_ROOT/pyproject.toml"
        if not test -x "$_ARKA_ROOT/venv-arka/bin/python3"
            python3 -m venv "$_ARKA_ROOT/venv-arka" 2>/dev/null
        end
        if test -x "$_ARKA_ROOT/venv-arka/bin/python3"
            set bootstrap "$_ARKA_ROOT/venv-arka/bin/python3"
        end
    end
    $bootstrap -m arka setup 2>&1 | string match -ev \
        '^Requirement|^  |^Collecting|^Using cached|^Installing|^Successfully|^Obtaining|^Building|^Created wheel|^Stored in|^Attempting uninstall|^Found existing|^Can.t uninstall'
    set vpy (_arka_venv_python)
    if test -z "$vpy"
        echo (set_color red) "✗ Missing Python deps (agno). Run: arka setup" (set_color normal) >&2
        return 1
    end
    return 0
end

function _arka_python --description "Python interpreter for Arka agents/LLM (internal)"
    set -l vpy (_arka_venv_python)
    if test -n "$vpy"
        echo "$vpy"
        return
    end
    set -l fallback "$_ARKA_ROOT/venv-arka/bin/python3"
    if test -x "$fallback"
        echo "$fallback"
        return
    end
    echo python3
end

function _arka_llm_model_label --description "Last-used or preferred LLM provider/model (internal)"
    if set -q SHOW_MODEL; and test "$SHOW_MODEL" = 0 -o "$SHOW_MODEL" = false
        return 1
    end
    set -l py (_arka_python)
    set -l model (string trim -- ($py (_arka_py_script arka_llm.py) active-model 2>/dev/null))
    test -n "$model"; and echo "$model"
end

function _agent_is_skills_help_request --description "True if user wants Arka skill list (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    if string match -qr '(?i)^(skills|help|\?|list skills|show skills|agent skills|what can you do|what do you do)\s*$' "$clean"
        return 0
    end
    if string match -qr '(?i)(tell\s+(?:me\s+)?(?:about\s+)?(?:all\s+)?(?:your\s+)?skills?|tell\s+your\s+skills?|(list|show)\s+(?:me\s+)?(?:all\s+)?(?:your\s+)?skills?|what\s+(?:are\s+)?(?:all\s+)?your\s+skills?)' "$clean"
        return 0
    end
    return 1
end

function _arka_skills_help_show --description "Print voice-friendly skills summary + LLM model"
    set -l py (_arka_python)
    set -l help (string trim -- ($py (_arka_py_script arka_talents.py) voice-help 2>/dev/null))
    test -z "$help"; and set help "Run arka help for the full skill list."
    set -l model (_arka_llm_model_label 2>/dev/null)
    printf '%s%s%s\n' (set_color --bold green) "━━━ Arka Skills ━━━" (set_color normal)
    echo ""
    echo "  $help"
    if test -n "$model"
        echo ""
        set_color brblack
        echo "  Model for answers: $model"
        set_color normal
    end
    echo ""
    set_color brblack
    echo "  Full list: arka help"
    set_color normal
end

function _agent_clean_llm_output --description "Strip markdown fences from LLM text (internal)"
    set -l text (string trim -- "$argv[1]")
    test -z "$text"; and return
    string replace -r '^```[a-zA-Z0-9]*\n*' '' "$text" | string replace -r '\n*```$' ''
end

function _agent_llm_complete --description "LLM system+user prompt via modular auto-fallback (internal)"
    set -l system_text $argv[1]
    set -l user_text $argv[2]
    set -l temperature 0.2
    set -l task default
    set -l skill ""
    if test (count $argv) -ge 3
        set temperature $argv[3]
    end
    if test (count $argv) -ge 4
        set task $argv[4]
    end
    if test (count $argv) -ge 5
        set skill $argv[5]
    else if test -n "$ARKA_SKILL"
        set skill $ARKA_SKILL
    end
    if test -z "$system_text" -o -z "$user_text"
        return 1
    end

    set -l py (_arka_python)
    set -l cmd (_arka_py_script arka_llm.py) complete --system "$system_text" --user "$user_text" --temperature $temperature --task $task
    if test -n "$skill"
        set -a cmd --skill $skill
    end
    set -l out ($py $cmd 2>/dev/null)
    if test -n "$out"
        _agent_clean_llm_output "$out"
        return 0
    end
    return 1
end

function _arka_route_mode --description "Routing strategy: symbolic|ai|symbolic_only|ai_only (internal)"
    set -l mode (string lower (string trim -- "$ROUTE_MODE"))
    switch $mode
        case ai llm ai-first ai_first
            echo ai
        case symbolic_only offline_only offline-only offline only
            echo symbolic_only
        case ai_only llm_only ai-only llm-only
            echo ai_only
        case hybrid auto symbolic offline '' default
            echo symbolic
        case '*'
            echo symbolic
    end
end

function _agent_llm_route --description "Interpret NL command to skill/shell via Agno (internal)"
    set -l cmd "$argv[1]"
    set -l available_skills "$argv[2]"
    test -z "$cmd"; and return 1

    set -l py (_arka_python)
    set -lx ROUTE_ALIASES (alias | string join "\n")
    set -l out ($py (_arka_py_script arka_llm.py) route "$cmd" --skills "$available_skills" 2>/dev/null)
    if test -n "$out"
        _agent_clean_llm_output "$out"
        return 0
    end
    return 1
end

function _agent_loop_truncate --description "Limit output size for LLM context (internal)"
    set -l text "$argv[1]"
    set -l max 3500
    if test (string length "$text") -le $max
        printf '%s' "$text"
        return
    end
    printf '%s\n...(truncated)' (string sub -l $max "$text")
end

function _agent_loop_execute --description "Run one loop command; prints output, returns exit code"
    argparse 'y/yes' 's/safe-only' -- $argv
    or return 1
    set -l cmd (string trim -- "$argv[1]")
    test -z "$cmd"; and return 1

    set -l skills (_agent_available_skills)
    set -l first (string split -f 1 " " -- "$cmd")

    if _agent_is_skill "$first"
        if set -q _flag_y
            if not _arka_confirm_risky_action -y "$cmd"
                echo "[skipped: security confirm declined]"
                return 2
            end
        else if not _arka_confirm_risky_action "$cmd"
            echo "[skipped: security confirm declined]"
            return 2
        end
        set -l out (_arka_run_shell_string "$cmd" 2>&1)
        set -l st $status
        printf '%s' (_agent_loop_truncate "$out")
        return $st
    end

    if not __agent_classify "$cmd"
        if set -q _flag_s
            echo "[skipped: dangerous command, safe-only mode]"
            return 2
        end
        if set -q _flag_y
            set -l out (_arka_run_shell_string "$cmd" 2>&1)
            set -l st $status
            printf '%s' (_agent_loop_truncate "$out")
            return $st
        end
        set -l out (_agent_exec_shell_cmd "$cmd" 2>&1)
        set -l st $status
        printf '%s' (_agent_loop_truncate "$out")
        return $st
    end

    set -l out (_arka_run_shell_string "$cmd" 2>&1)
    set -l st $status
    printf '%s' (_agent_loop_truncate "$out")
    return $st
end

function _agent_loop_parse_step --description "Parse LLM JSON step; sets _loop_status _loop_cmd _loop_why"
    set -l raw (string trim -- "$argv[1]")
    set -g _loop_status continue
    set -g _loop_cmd ""
    set -g _loop_why ""

    set raw (string replace -r '^```[a-zA-Z0-9]*\n*' '' "$raw" | string replace -r '\n*```$' '' | string trim)

    if printf '%s' "$raw" | jq empty 2>/dev/null
        set -g _loop_status (printf '%s' "$raw" | jq -r '.status // "continue"' | string lower)
        set -g _loop_cmd (printf '%s' "$raw" | jq -r '.cmd // empty' | string trim)
        set -g _loop_why (printf '%s' "$raw" | jq -r '.why // empty' | string trim)
        return 0
    end

    set -l m (string match -r '(?i)"cmd"\s*:\s*"([^"]+)"' -- "$raw")
    if test (count $m) -ge 2
        set -g _loop_cmd $m[2]
    else
        set -g _loop_cmd (string replace -r '^[`$]+|[`$]+$' '' "$raw" | string trim)
    end
    if string match -qi '*done*' -- "$raw"
        set -g _loop_status done
    end
end

# List available agent skills
function skills --description "Show what commands the agent can auto-run"
    echo (set_color --bold blue)"Agent Skills (auto-execute, no confirmation)"(set_color normal)
    echo (set_color cyan)"────────────────────────────────────────────────"(set_color normal)
    echo (set_color green)"  File ops     "(set_color normal)"ls, eza, find, tree, cat, head, tail, wc, stat, file, touch, mkdir, cp"
    echo (set_color green)"  Search       "(set_color normal)"grep, rg, fd, ag, fzf"
    echo (set_color green)"  System info  "(set_color normal)"system_info, uname, df, uptime; Linux: lscpu/free; macOS: sysctl/sw_vers/vm_stat"
    echo (set_color green)"  Text tools   "(set_color normal)"sort, uniq, cut, tr, awk, sed (no -i), jq, echo, printf"
    echo (set_color green)"  Git (read)   "(set_color normal)"git status, git log, git diff, git branch, git show, git remote"
    echo (set_color green)"  Git (write)  "(set_color normal)"git add, git commit, git push, git pull, git checkout, git switch"
    echo (set_color green)"  Install      "(set_color normal)"pip install, npm install, apt install, uv pip install, cargo install"
    echo (set_color green)"  Run code     "(set_color normal)"python3, node, bash, sh, make, cargo run"
    echo (set_color green)"  Networking   "(set_color normal)"curl, wget, ping, ssh, scp, rsync"
    echo ""
    echo (set_color --bold blue)"Named Agent Skills (via agent / arka)"(set_color normal)
    echo (set_color cyan)"────────────────────────────────────────────────"(set_color normal)
    for skill in (_agent_available_skills)
        switch $skill
            case pdf_ingest doc_ingest
                echo (set_color green)"  pdf_ingest / doc_ingest"(set_color normal)" <path> — ingest PDF/Office/text/code"
            case pdf_ask doc_ask
                echo (set_color green)"  pdf_ask / doc_ask   "(set_color normal)"[--doc DOC] <question> — Q&A / summarize"
            case data_ask ask_data query_data analyze_data
                echo (set_color green)"  data_ask / query_data"(set_color normal)" <file|folder> [--format] [question] — Q&A over CSV/JSON/TSV"
            case drawing_ask
                echo (set_color green)"  drawing_ask     "(set_color normal)"<file.pdf|image> <question> — vision analysis (Gemini)"
            case describe_image
                echo (set_color green)"  describe_image  "(set_color normal)"<path|url> [question] — photo caption (vLLM)"
            case describe_screen
                echo (set_color green)"  describe_screen "(set_color normal)"[question] — 10s countdown, capture display, describe"
            case pdf_list doc_list
                echo (set_color green)"  pdf_list / doc_list  "(set_color normal)"List ingested documents"
            case disk_breakdown
                echo (set_color green)"  disk_breakdown "(set_color normal)"[path] — storage by videos, docs, etc."
            case web_answer
                echo (set_color green)"  web_answer     "(set_color normal)"[--deep] <q> — web answer (auto deep search when needed)"
            case deep_web_answer
                echo (set_color green)"  deep_web_answer"(set_color normal)" <q> — scrape + RAG web search"
            case calc
                echo (set_color green)"  calc           "(set_color normal)"<expr> — SymPy math + AI explanation"
            case hyperlocal_weather
                echo (set_color green)"  hyperlocal_weather"(set_color normal)" [q] — Open-Meteo + IP location"
            case chat_reset
                echo (set_color green)"  chat_reset     "(set_color normal)"Clear chat session + location context"
            case set_location
                echo (set_color green)"  set_location   "(set_color normal)"[city|PIN] — set/refresh location for search"
            case nearby_places
                echo (set_color green)"  nearby_places  "(set_color normal)"[city] — offline nearby POIs"
            case map_download
                echo (set_color green)"  map_download   "(set_color normal)"<city> — download OSM POI map"
            case error_helper
                echo (set_color green)"  error_helper   "(set_color normal)"<error text> — explain traceback/fix"
            case deep_queue
                echo (set_color green)"  deep_queue     "(set_color normal)"add|list|run|results — background deep search"
            case web_essay
                echo (set_color green)"  web_essay      "(set_color normal)"<topic> — write an essay via web + AI"
            case app_usage
                echo (set_color green)"  app_usage      "(set_color normal)"[today|week|…] — screen/app time"
            case internet_enhance aie
                echo (set_color green)"  internet_enhance / aie"(set_color normal)" [status|start|stop|cleanup] — Artificial Internet Enhancements"
            case youtube_transcript
                echo (set_color green)"  youtube_transcript"(set_color normal)" <url> [--summarize] — YouTube captions"
            case youtube_download yt_download
                echo (set_color green)"  youtube_download / yt_download"(set_color normal)" <url> [--audio] — download one YouTube video"
            case media_transcript transcribe_media
                echo (set_color green)"  media_transcript"(set_color normal)" <mp3|mp4|…> [--summarize] — transcribe (cloud + local Whisper fallback)"
            case folder_summarize
                echo (set_color green)"  folder_summarize "(set_color normal)"<dir> [-r] [-q question] — summarize all media in folder"
            case playlist_summarize
                echo (set_color green)"  playlist_summarize"(set_color normal)" --url URL | --folder DIR — digest a playlist"
            case youtube_research yt_research
                echo (set_color green)"  youtube_research "(set_color normal)"<query> [--limit N] [--focus Q] [--index] — default 2 videos; partial results on errors"
            case find_videos
                echo (set_color green)"  find_videos      "(set_color normal)"<topic> — YouTube video links (fast, no LLM)"
            case survive_lang
                echo (set_color green)"  survive_lang     "(set_color normal)"<language> [phrase] — travel survival phrases"
            case pr_check pr-check pr
                echo (set_color green)"  pr_check         "(set_color normal)"diff|summary|ci|explain|babysit — PR until merge-ready"
            case codebase_ingest
                echo (set_color green)"  codebase_ingest  "(set_color normal)"<project-dir> [-n name] — index repo for doc_ask Q&A"
            case agent_remember agent_recall agent_memory
                echo (set_color green)"  agent_remember / agent_recall"(set_color normal)" — long-term memory"
            case agent_research
                echo (set_color green)"  agent_research  "(set_color normal)"[--deep] <q> — TurboQuant + web + media research"
            case agent_trace agent_why agent_last
                echo (set_color green)"  agent_trace / agent_why"(set_color normal)" — explain last routing decision"
            case agent_resume
                echo (set_color green)"  agent_resume    "(set_color normal)"list|clear|<id> — resume agent_loop"
            case agent_handoff
                echo (set_color green)"  agent_handoff   "(set_color normal)"add|list|run — phone ↔ PC task queue"
            case agent_watch agent_routine agent_fanout agent_code agent_browser
                echo (set_color green)"  agent_watch|routine|fanout|code|browser"(set_color normal)" — agentic automation"
            case transcript_ask media_ask
                echo (set_color green)"  transcript_ask  "(set_color normal)"<file> <q> — Q&A on media transcript"
            case rag_setup rag_status
                echo (set_color green)"  rag_setup / rag_status"(set_color normal)" — TurboQuant RAG install/check"
            case voice_agent wake_control
                echo (set_color green)"  voice_agent / wake_control"(set_color normal)" start|stop|status"
            case arka_ask
                echo (set_color green)"  arka_ask         "(set_color normal)"[--deep] [--youtube] [--speak] <q> — unified brain"
            case semantic_memory
                echo (set_color green)"  semantic_memory  "(set_color normal)"remember|recall|reindex — TurboQuant memory"
            case supermemory
                echo (set_color green)"  supermemory      "(set_color normal)"remember|recall|list|status — cloud + local fallback"
            case speak_research
                echo (set_color green)"  speak_research   "(set_color normal)"<query> — YouTube research + TTS digest"
            case voice_session
                echo (set_color green)"  voice_session    "(set_color normal)"clear|status — multi-turn voice context"
            case handoff_notify
                echo (set_color green)"  handoff_notify   "(set_color normal)"list|run — phone handoff alerts"
            case remind
                echo (set_color green)"  remind           "(set_color normal)"in 30m msg | at 5pm msg | list | cancel ID"
            case routines
                echo (set_color green)"  routines         "(set_color normal)"add daily 9am \"task\" | list | install | remove"
            case predictions
                echo (set_color green)"  predictions      "(set_color normal)"[--domain antiques|stocks|strategy] [--deep] <topic>"
            case stock stock_analysis
                echo (set_color green)"  stock            "(set_color normal)"news|prices|policy|strategy|dashboard|analyze TICKER — stock_analysis project"
            case youtube_bulk yt_bulk
                echo (set_color green)"  youtube_bulk / yt_bulk"(set_color normal)" [status|start|download|library] — bulk YouTube playlist/channel downloads"
            case summarize_url
                echo (set_color green)"  summarize_url  "(set_color normal)"<url> — summarize a web page"
            case post_x
                echo (set_color green)"  post_x         "(set_color normal)"<url> [--words N] [--dry-run] [--post] — shorten URL; auto-post only with X auth"
                echo (set_color green)"  post_x install "(set_color normal)"— install @steipete/bird CLI (needed only for --post with bird cookies)"
            case daily_brief
                echo (set_color green)"  daily_brief    "(set_color normal)"Weather + news headlines (--url-limit / BRIEF_URL_LIMIT_ENABLED for excerpts)"
            case sports_score live_scores
                echo (set_color green)"  sports_score   "(set_color normal)"[ipl|nfl|nba|epl|cricket|…] — live match scores (ESPN)"
            case currency_convert convert currency
                echo (set_color green)"  currency_convert "(set_color normal)"<amount> <from> <to> — live FX rates (USD, EUR, INR, …)"
            case kalshi
                echo (set_color green)"  kalshi         "(set_color normal)"search <topic> | market <TICKER> | trending | status — Kalshi prediction odds"
            case wifi_info
                echo (set_color green)"  wifi_info      "(set_color normal)"Current Wi-Fi network + signal"
            case generate_image
                echo (set_color green)"  generate_image "(set_color normal)"<prompt> — Nano Banana (Gemini) + Pollinations nanobanana fallback"
            case generate_thumbnail
                echo (set_color green)"  generate_thumbnail "(set_color normal)"--topic 'ai' — YouTube thumbnail (Unsplash + title overlay)"
            case chart
                echo (set_color green)"  chart          "(set_color normal)"line | bar | pie | scatter — matplotlib PNG charts"
            case select_model model_select best_model model_advisor
                echo (set_color green)"  select_model   "(set_color normal)"--apply — recommend LLM profiles from PC resources"
            case ascii_art
                echo (set_color green)"  ascii_art      "(set_color normal)"<text> | --from-image photo.jpg — figlet banner / image ASCII"
            case generate_video
                echo (set_color green)"  generate_video "(set_color normal)"<prompt> — real AI video (Pollinations/Gemini; needs API key or billing)"
            case compose_video
                echo (set_color green)"  compose_video   "(set_color normal)"--topic '…' [--llm] — YouTube info video (Unsplash + ffmpeg + TTS)"
            case compose_slides
                echo (set_color green)"  compose_slides  "(set_color normal)"compose|convert — deck build/export (pptx|pdf|html|md|json|all)"
            case convert_media
                echo (set_color green)"  convert_media   "(set_color normal)"<file> --to <format> | --format all — image/video/slide conversion"
            case pdf_tools
                echo (set_color green)"  pdf_tools       "(set_color normal)"merge|split|compress|ocr|protect|… — CLI PDF toolkit"
            case agent_ask
                echo (set_color green)"  agent_ask      "(set_color normal)"<question> — advisory Q&A via shell context"
        end
    end
    echo (set_color brblack)"  Full list: agent help | grep -E 'pdf_|web_|disk_'"(set_color normal)
    echo ""
    echo (set_color --bold red)"Needs Confirmation (dangerous)"(set_color normal)
    echo (set_color cyan)"────────────────────────────────────────────────"(set_color normal)
    echo (set_color red)"  Deletion     "(set_color normal)"rm, rmdir, unlink"
    echo (set_color red)"  Move/rename  "(set_color normal)"mv (can overwrite files)"
    echo (set_color red)"  Root access  "(set_color normal)"sudo, doas, su"
    echo (set_color red)"  Permissions  "(set_color normal)"chmod, chown"
    echo (set_color red)"  Destructive  "(set_color normal)"dd, mkfs, fdisk, kill, pkill, shutdown, reboot"
    echo (set_color red)"  Git danger   "(set_color normal)"git push --force, git reset --hard, git clean -f"
    echo (set_color red)"  Edit in-place"(set_color normal)"sed -i (modifies files directly)"
end

# AI Agent — plans and executes multi-step tasks
function agent_plan --description "AI agent that plans and executes multi-step tasks"
    argparse 'd/depth=' -- $argv
    or return

    set -l goal (string join " " $argv)
    set -l depth 3
    if set -q _flag_d
        set depth $_flag_d
    end

    if test -z "$goal"
        echo "Usage: agent_plan [-d depth] <describe your goal>"
        echo ""
        echo "Examples:"
        echo "  agent_plan set up a python project with flask"
        echo "  agent_plan find all large files over 100MB"
        echo "  agent_plan -d 5 organize photos by year"
        echo ""
        echo "Run 'skills' to see safe vs dangerous commands."
        return 1
    end

    # --- Build directory context ---
    set -l cwd (pwd)
    set -l tree_out (find . -maxdepth $depth -mindepth 1 -not -path '*/\.*' -print 2>/dev/null | sort | head -100 | sed 's#^\./##')
    set -l files_out (command ls -lah 2>/dev/null | head -30)

    echo (set_color --bold yellow)"Agent thinking..."(set_color normal)

    # --- System prompt ---
    set -l aliases_list (alias | string join "\n")
    set -l plat (_arka_agent_platform_label)
    set -l plat_hint (_arka_agent_platform_hint)
    set -l system_text "You are a shell command planner on $plat (fish shell). Given a goal and directory context, return ONLY a valid JSON array of steps. Each step is an object with \"cmd\" (the shell command) and \"why\" (a brief reason). Rules: 1) Return ONLY the raw JSON array, no markdown fences, no backticks, no explanation text. 2) Use commands appropriate for the host OS. 3) One shell command per step. 4) Be minimal — fewest steps needed. 5) Commands run in fish shell, so use fish syntax (e.g. \"and\" instead of \"&&\" or use aliases). 6) Do NOT use sudo unless absolutely necessary.
$plat_hint
Available Shell Aliases:
$aliases_list
Use symbolic reasoning to prefer using the appropriate shell alias if one is available and fits the plan.
CRITICAL NOTE ON ALIASES:
- `ls` is aliased to `eza`. `eza` does NOT support standard `ls` sorting flags like `-t`, `-ltr`, or `-lt`. To sort by newest/recency, use `eza --sort newest` (or `eza -snew`). To sort by oldest, use `eza --sort oldest` (or `eza -sold`). Alternatively, bypass the alias by running standard `ls` via `command ls -lt` or `command ls -ltr`.
- `cat` is aliased to `batcat`."

    set -l user_text "GOAL: $goal
CWD: $cwd

DIRECTORY TREE (depth $depth):
$tree_out

FILE LISTING:
$files_out"

    # --- Call AI (modular auto-fallback via arka_llm) ---
    set -l plan_json (_agent_llm_complete "$system_text" "$user_text" 0.1 agent)

    if test -z "$plan_json"
        echo (set_color red)"Failed to get plan. Check API keys / connection."(set_color normal)
        return 1
    end

    # --- Parse the plan ---
    # Strip markdown fences if AI wrapped them
    set plan_json (printf '%s' "$plan_json" | string replace -r '```json\s*' '' | string replace -r '```' '' | string trim)

    # Validate JSON
    if not printf '%s' "$plan_json" | jq empty 2>/dev/null
        echo (set_color red)"AI returned invalid JSON:"(set_color normal)
        printf '%s\n' "$plan_json"
        return 1
    end

    # If AI wrapped in an object like {"steps":[...]}, unwrap to just the array
    if printf '%s' "$plan_json" | jq -e 'type == "object"' >/dev/null 2>&1
        set plan_json (printf '%s' "$plan_json" | jq '[.[] | if type == "array" then .[] else empty end]')
    end

    set -l step_count (printf '%s' "$plan_json" | jq 'length')

    if test "$step_count" = "0" -o "$step_count" = "null"
        echo (set_color yellow)"AI returned an empty plan."(set_color normal)
        return 0
    end

    # --- Display the plan ---
    echo ""
    echo (set_color --bold green)"Plan: $step_count step(s)"(set_color normal)
    echo (set_color cyan)"────────────────────────────────────────"(set_color normal)

    for i in (seq 0 (math $step_count - 1))
        set -l cmd (printf '%s' "$plan_json" | jq -r ".[$i].cmd")
        set -l why (printf '%s' "$plan_json" | jq -r ".[$i].why")
        set -l step_num (math $i + 1)

        set -l badge ""
        if __agent_classify "$cmd"
            set badge (set_color --bold green)"SKILL"(set_color normal)
        else
            set badge (set_color --bold red)"CONFIRM"(set_color normal)
        end

        echo "  [$badge] Step $step_num: "(set_color cyan)"$cmd"(set_color normal)
        echo "            "(set_color brblack)"$why"(set_color normal)
    end

    echo (set_color cyan)"────────────────────────────────────────"(set_color normal)
    echo ""

    # --- Confirm execution ---
    read -P (set_color --bold yellow)"Execute? [Y]es / [n]o / [s]afe-only: "(set_color normal) -l confirm

    set -l mode "all"
    switch $confirm
        case n N no
            echo "Aborted."
            return 0
        case s S safe
            set mode "safe-only"
    end

    echo ""

    # --- Execute steps ---
    for i in (seq 0 (math $step_count - 1))
        set -l cmd (printf '%s' "$plan_json" | jq -r ".[$i].cmd")
        set -l why (printf '%s' "$plan_json" | jq -r ".[$i].why")
        set -l step_num (math $i + 1)

        set -l is_safe yes
        if not __agent_classify "$cmd"
            set is_safe no
        end

        echo (set_color --bold blue)"━━━ Step $step_num/$step_count ━━━"(set_color normal)
        echo (set_color cyan)"\$ $cmd"(set_color normal)
        echo (set_color brblack)"  $why"(set_color normal)

        if test "$is_safe" = "no"
            if test "$mode" = "safe-only"
                echo (set_color yellow)"  Skipped (dangerous, safe-only mode)"(set_color normal)
                echo ""
                continue
            end
            read -P (set_color --bold red)"  ⚠ Dangerous — run this? [y/N]: "(set_color normal) -l step_confirm
            if not string match -qi 'y*' "$step_confirm"
                echo (set_color yellow)"  Skipped by user"(set_color normal)
                echo ""
                continue
            end
        else
            echo (set_color green)"  [auto-running skill]"(set_color normal)
        end

        # Run it
        set -l output (_arka_run_shell_string "$cmd" 2>&1)
        set -l cmd_status $status

        if test $cmd_status -eq 0
            echo (set_color green)"  ✓ OK"(set_color normal)
        else
            echo (set_color red)"  ✗ Failed (exit $cmd_status)"(set_color normal)
        end

        if test -n "$output"
            printf '%s\n' $output | head -30
            set -l total_lines (printf '%s\n' $output | wc -l)
            if test $total_lines -gt 30
                echo (set_color brblack)"  ... ($total_lines lines, showing first 30)"(set_color normal)
            end
        end
        echo ""

        # On failure, ask whether to continue
        if test $cmd_status -ne 0
            read -P (set_color yellow)"  Step failed. Continue? [y/N]: "(set_color normal) -l cont
            if not string match -qi 'y*' "$cont"
                echo (set_color red)"Agent stopped."(set_color normal)
                return 1
            end
        end
    end

    echo (set_color --bold green)"Agent finished."(set_color normal)
end

function agent_loop --description "AI feedback loop: run command → read output → correct until done"
    argparse 'n/max=' 'y/yes' 's/safe-only' 'r/resume-id=' 'v/verify' 'a/auto' -- $argv
    or return

    set -l engine (string lower (string trim -- "$GOAL_ENGINE"))
    test -z "$engine"; and set engine auto
    if not set -q _flag_r
        if test "$engine" = auto -o "$engine" = arka
            set -l gflags
            set -q _flag_y; and set -a gflags -y
            set -q _flag_v; and set -a gflags -v
            set -q _flag_s; and set -a gflags -s
            set -q _flag_n; and set -a gflags -n $_flag_n
            goal $gflags $argv
            return $status
        else if test "$engine" = butterfish
            goal --butterfish $argv
            return $status
        end
    end

    set -l goal (string join " " $argv)
    set -l max_iter 12
    if set -q _flag_n
        set max_iter $_flag_n
    end

    set -l resume_history ""
    set -l resume_iter 0
    set -l resume_cwd (pwd)
        if set -q _flag_r
        set -l state (_arka_agent loop-load $_flag_r)
        if test -n "$state"; and test "$state" != "{}"
            set goal (printf '%s' "$state" | jq -r '.goal // empty')
            set resume_history (printf '%s' "$state" | jq -r '.history // empty')
            set resume_iter (printf '%s' "$state" | jq -r '.iter // 0')
            set resume_cwd (printf '%s' "$state" | jq -r '.cwd // empty')
            test -n "$resume_cwd"; and cd "$resume_cwd" 2>/dev/null
            echo (set_color cyan)"Resuming from step $resume_iter: $goal"(set_color normal)
        end
    end

    if _agent_matches_graphics_driver "$goal"
        echo (set_color cyan)"→ Specialized skill: fix_graphics_driver (not a shell loop task)"(set_color normal)
        echo ""
        set -l routed (_agent_route_graphics_driver "$goal")
        $routed
        return $status
    end

    if test -z "$goal"
        echo "Usage: agent_loop [-n max] [-y] [-s] <goal>"
        echo "       loop <goal>   # same"
        echo ""
        echo "Runs commands in a loop: AI proposes a command, shell runs it, output is"
        echo "fed back, and the AI corrects until the goal is done or max steps reached."
        echo ""
        echo "Options:"
        echo "  -n, --max N   Maximum iterations (default: 12)"
        echo "  -y, --yes     Auto-approve dangerous shell commands"
        echo "  -s, --safe-only  Skip dangerous commands"
        echo "  -r, --resume-id ID  Resume saved loop state (agent_resume list)"
        echo "  -v, --verify  LLM verification pass when loop completes"
        echo "  -a, --auto    Auto-continue steps (AGENT_AUTO=safe|all)"
        echo ""
        echo "Examples:"
        echo "  agent_loop find why nginx fails and fix the config"
        echo "  loop -n 8 set up a venv and install requests"
        echo "  agent loop debug my python script"
        return 1
    end

    set -l cwd (pwd)
    set -l tree_out (find . -maxdepth 2 -mindepth 1 -not -path '*/\.*' -print 2>/dev/null | sort | head -40 | sed 's#^\./##')
    set -l aliases_list (alias | string join "\n")
    set -l skills_list (_agent_available_skills | string join ", ")
    set -l mem_ctx (_arka_agent memory-context "$goal" 2>/dev/null)

    set -l plat (_arka_agent_platform_label)
    set -l plat_hint (_arka_agent_platform_hint)
    set -l system_text "You are a cross-platform shell agent on $plat in a run-fix loop (fish shell).
Each turn return ONLY valid JSON (no markdown fences):
{\"status\":\"continue\"|\"done\",\"cmd\":\"one shell command or skill invocation\",\"why\":\"brief reason\"}

Rules:
- One command per turn. Use status \"done\" when the goal is fully achieved (cmd may be empty).
- Learn from HISTORY: if a command failed, diagnose output and try a corrected command.
- Prefer safe read-only checks before destructive changes.
- Commands run in fish; use fish syntax and OS-appropriate tools.
- $plat_hint
- Registered skills you may call by name: $skills_list
- Local machine specs (my pc/mac specs) -> system_info skill (not lscpu/free on macOS).
- Intel/GPU driver warning pasted from Unreal/apps (Linux): first command MUST be fix_graphics_driver (no args).
- Do NOT use sudo unless necessary."
    if test -n "$mem_ctx"
        set system_text "$system_text

$mem_ctx"
    end
    set system_text "$system_text

Aliases:
$aliases_list
- ls is eza (use eza --sort newest for time sort, or command ls -lt)
- cat is batcat"

    set -l history_text "$resume_history"
    set -l iter $resume_iter

    echo (set_color --bold yellow)"Agent loop: $goal"(set_color normal)
    echo (set_color brblack)"  cwd: $cwd | max steps: $max_iter"(set_color normal)
    echo ""

    while test $iter -lt $max_iter
        set iter (math $iter + 1)
        set -l user_text "GOAL: $goal
CWD: $cwd
DIRECTORY (depth 2):
$tree_out

HISTORY:
$history_text

Iteration $iter/$max_iter — return the NEXT command as JSON."

        echo (set_color --bold blue)"━━━ Loop $iter/$max_iter ━━━"(set_color normal)
        echo (set_color brblack)"  Thinking..."(set_color normal)

        set -l ai_raw (_agent_llm_complete "$system_text" "$user_text")
        if test $status -ne 0 -o -z "$ai_raw"
            echo (set_color red)"  LLM unavailable. Check API keys / Ollama."(set_color normal)
            return 1
        end

        _agent_loop_parse_step "$ai_raw"
        set -l step_status $_loop_status
        set -l step_cmd $_loop_cmd
        set -l step_why $_loop_why

        if test "$step_status" = done
            echo (set_color green)"  ✓ AI reports goal complete."(set_color normal)
            if test -n "$step_why"
                echo "  "(set_color brblack)$step_why(set_color normal)
            end
            if set -q _flag_v; or test "$AGENT_VERIFY" = 1 -o "$AGENT_VERIFY" = true
                set -l verify (_arka_agent loop-verify "$goal" --history "$history_text" 2>/dev/null)
                set -l vdone (printf '%s' "$verify" | jq -r '.done // false' 2>/dev/null)
                set -l vsummary (printf '%s' "$verify" | jq -r '.summary // empty' 2>/dev/null)
                if test "$vdone" = true
                    echo (set_color green)"  ✓ Verification passed: $vsummary"(set_color normal)
                else
                    echo (set_color yellow)"  ⚠ Verification uncertain: $vsummary"(set_color normal)
                end
            end
            _arka_agent loop-clear latest 2>/dev/null
            echo ""
            echo (set_color --bold green)"Loop finished in $iter step(s)."(set_color normal)
            return 0
        end

        if test -z "$step_cmd"
            if _agent_matches_graphics_driver "$goal"
                echo (set_color cyan)"  LLM returned no command — running fix_graphics_driver."(set_color normal)
                echo ""
                set -l routed (_agent_route_graphics_driver "$goal")
                $routed
                return $status
            end
            echo (set_color yellow)"  Empty command from AI; stopping."(set_color normal)
            echo (set_color brblack)"  Tip: use fix_graphics_driver or agent \"fix <paste warning>\""(set_color normal)
            return 1
        end

        echo "  "(set_color cyan)"→ $step_cmd"(set_color normal)
        if test -n "$step_why"
            echo "  "(set_color brblack)$step_why(set_color normal)
        end

        set -l exec_flags
        set -q _flag_y; and set -a exec_flags -y
        set -q _flag_s; and set -a exec_flags -s

        set -l out (_agent_loop_execute $exec_flags "$step_cmd")
        set -l exit_code $status

        if test $exit_code -eq 0
            echo (set_color green)"  ✓ exit 0"(set_color normal)
        else if test $exit_code -eq 2
            echo (set_color yellow)"  ⊘ skipped"(set_color normal)
        else
            echo (set_color red)"  ✗ exit $exit_code"(set_color normal)
        end

        if test -n "$out"
            printf '%s\n' $out | head -25 | sed 's/^/    /'
            set -l nlines (printf '%s\n' "$out" | wc -l)
            if test $nlines -gt 25
                echo (set_color brblack)"    ... ($nlines lines, showing 25)"(set_color normal)
            end
        end
        echo ""

        set history_text "$history_text
--- step $iter ---
cmd: $step_cmd
exit: $exit_code
why: $step_why
output:
$out
"

        _arka_agent loop-save "$goal" --cwd "$cwd" --history "$history_text" --iter $iter --max $max_iter 2>/dev/null

        set -l auto_continue 0
        if set -q _flag_a; or test "$AGENT_AUTO" = all -o "$AGENT_AUTO" = 1 -o "$AGENT_AUTO" = true
            set auto_continue 1
        else if test "$AGENT_AUTO" = safe; and __agent_classify "$step_cmd"
            set auto_continue 1
        end
        if test $auto_continue -eq 1; or set -q _flag_y
            continue
        end

        read -P (set_color --bold yellow)"  Continue loop? [Y/n/q]: "(set_color normal) -l cont
        switch $cont
            case q Q quit
                echo "Stopped."
                return 0
            case n N no
                echo "Stopped after step $iter."
                return 0
        end
    end

    echo (set_color yellow)"Max iterations ($max_iter) reached."(set_color normal)
    return 1
end

function _arka_ensure_butterfish --description "Install Butterfish on user confirm; prints path (internal)"
    argparse 'y/yes' -- $argv
    or return 1
    set -l py (_arka_python)
    set -l auto 0
    set -q _flag_y; and set auto 1
    $py -c "from arka.integrations.butterfish import ensure_butterfish; p=ensure_butterfish(auto_yes=bool($auto)); print(p or '')" 2>/dev/null | string trim
end

function goal --description "Autonomous multi-step agent (Arka Goal engine or Butterfish Goal Mode)"
    argparse 'n/max=' 'y/yes' 'v/verify' 'b/butterfish' 'u/unsafe' 's/safe-only' -- $argv
    or return 1

    set -l py (_arka_python)

    if set -q _flag_s
        set -lx GOAL_SAFE_ONLY 1
    end

    set -l engine (string lower (string trim -- "$GOAL_ENGINE"))
    test -z "$engine"; and set engine auto

    if set -q _flag_b; or test "$engine" = butterfish
        set -l goal_text (string join " " $argv)
        set -l bflags
        set -q _flag_y; and set -a bflags -y
        set -l bf (_arka_ensure_butterfish $bflags)
        if test -z "$bf"
            echo (set_color yellow)"Using Arka built-in goal agent (Butterfish unavailable)."(set_color normal)
            set -l flags
            set -q _flag_y; and set -a flags -y
            set -q _flag_v; and set -a flags -v
            set -q _flag_n; and set -a flags -n $_flag_n
            $py -m arka.agent.goal $flags $argv
            return $status
        end
        set -l prefix "!"
        set -q _flag_u; and set prefix "!!"
        echo (set_color cyan)"Butterfish shell — type "(set_color --bold)"$prefix"(set_color normal)(set_color cyan)" then your goal:"(set_color normal)
        echo "  $prefix$goal_text"
        exec butterfish shell
    end

    set -l flags
    set -q _flag_y; and set -a flags -y
    set -q _flag_v; and set -a flags -v
    set -q _flag_n; and set -a flags -n $_flag_n
    $py -m arka.agent.goal $flags $argv
    return $status
end

function loop --description "Alias for agent_loop (AI run/fix loop)"
    agent_loop $argv
end

# Conversational AI Wrapper (Talk)
function talk --description "Chat with AI providers with clean formatting"
    argparse 'p/provider=' 'm/model=' -- $argv
    or return

    set -l prompt "$argv"
    set -l provider_req $_flag_p
    set -l model_req $_flag_m
    
    if test -z "$prompt"
        echo "Usage: talk [-p provider] [-m model] Your question here"
        return 1
    end

    # Use preference if set and no override provided
    if test -z "$provider_req" -a -n "$AI_PREFERRED_PROVIDER"
        set provider_req "$AI_PREFERRED_PROVIDER"
    end
    if test -z "$model_req" -a -n "$AI_PREFERRED_MODEL"
        set model_req "$AI_PREFERRED_MODEL"
    end

    set -l aliases_list (alias | string join "\n")
    set -l system_prompt "You are a helpful AI collaborator. Use clean formatting. No emojis.
Available Shell Aliases:
$aliases_list
If the user asks about commands or actions that map to these aliases, use symbolic reasoning to explain or reference them.
CRITICAL NOTE ON ALIASES:
- `ls` is aliased to `eza`. `eza` does NOT support standard `ls` sorting flags like `-t`, `-ltr`, or `-lt`. To sort by newest/recency, use `eza --sort newest` (or `eza -snew`). To sort by oldest, use `eza --sort oldest` (or `eza -sold`). Alternatively, bypass the alias by running standard `ls` via `command ls -lt` or `command ls -ltr`.
- `cat` is aliased to `batcat`."

    if test -n "$provider_req" -a -n "$model_req"
        set -lx LLM_FALLBACK "$provider_req:$model_req"
    else if test -n "$provider_req"
        set -lx LLM_FALLBACK "$provider_req:gemini-2.0-flash,$provider_req:llama-3.3-70b-versatile"
    end

    set -l result (_agent_llm_complete "$system_prompt" "$prompt" 0.2 chat)
    if test -n "$result"
        set -l model (_arka_llm_model_label 2>/dev/null)
        if test -n "$model"
            echo "--- $model ---"
        end
        printf "%b\n" "$result"
        return 0
    end
    echo (set_color yellow)"⚠ No AI provider responded. Set GEMINI_API_KEY, GROQ_API_KEY, or run ollama serve."(set_color normal)
    return 1
end
fish_add_path ~/.npm-global/bin

# OpenClaw completions (optional — only if installed)
set -l _openclaw_completions "$HOME/.openclaw/completions/openclaw.fish"
if test -f "$_openclaw_completions"
    source "$_openclaw_completions"
end

# opencode
fish_add_path /home/s/.opencode/bin
export OLLAMA_HOST=0.0.0.0:11434
alias bat='batcat' # Use bat instead of batcat
alias ls='eza' # Modern ls with colors
alias ll='eza -l' # Detailed listing
alias la='eza -la' # Detailed with hidden files
alias lt='eza --tree --level 2' # Tree view
if type -q batcat
    alias cat='batcat' # Syntax-highlighted cat
end
# fzf + ripgrep integration
export FZF_DEFAULT_COMMAND='rg --files'
export FZF_DEFAULT_OPTS='--height 40% --border --reverse'
alias o='gnome-text-editor'

function ai-models --description "List available AI models, providers, and limits"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_llm.py)
    echo (set_color --bold blue)"AI Provider Reference"(set_color normal)
    echo ""
    if test -f "$script"
        $py $script providers --models 2>/dev/null | while read -l line
            set -l parts (string split \t "$line")
            if test (count $parts) -lt 2
                echo $line
                continue
            end
            if test "$parts[1]" = display_name
                echo (set_color cyan)"$line"(set_color normal)
                continue
            end
            set -l mark (set_color brblack)" "(set_color normal)
            if test "$parts[3]" = yes
                set mark (set_color green)"✓"(set_color normal)
            end
            echo "  $mark $parts[2] ($parts[1]) — default: $parts[5]"
            if test (count $parts) -ge 6 -a -n "$parts[6]"
                echo (set_color brblack)"      models: $parts[6]"(set_color normal)
            end
        end
    else
        echo "  anthropic, openai, gemini, groq, xai, deepseek, moonshot, zai,"
        echo "  minimax, venice, bedrock, azure, openrouter, mistral, cohere,"
        echo "  together, fireworks, perplexity, huggingface, litellm, ollama,"
        echo "  lmstudio, vllm, vllm-cloud"
    end
    echo ""
    echo (set_color cyan)"Chain:"(set_color normal) $py $script models"
    echo (set_color cyan)"Live lists:"(set_color normal) $py $script models --gemini-live | --groq-live | --ollama-live"
end

function ai-status --description "Show current AI provider and model in use"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_llm.py)
    echo (set_color --bold blue)"━━━ AI Status ━━━"(set_color normal)
    echo ""
    echo (set_color cyan)"  Configured providers:"(set_color normal)
    set -l configured_lines
    if test -f "$script"
        set configured_lines ($py $script providers 2>/dev/null | string match -r '\tyes\t')
    end
    if test (count $configured_lines) -eq 0
        echo (set_color red)"    None configured"(set_color normal)
        echo (set_color yellow)"    Add keys to $_ARKA_CFG/.env — run: ai-models"(set_color normal)
    else
        for line in $configured_lines
            set -l parts (string split \t "$line")
            echo (set_color green)"    ✓ $parts[2] ($parts[1]) — default $parts[4]"(set_color normal)
        end
    end
    echo ""
    echo (set_color cyan)"  Current preference:"(set_color normal)
    if test -n "$AI_PREFERRED_PROVIDER" -a -n "$AI_PREFERRED_MODEL"
        echo (set_color --bold green)"    $AI_PREFERRED_PROVIDER → $AI_PREFERRED_MODEL"(set_color normal)
    else
        echo (set_color brblack)"    Not set (using auto-fallback)"(set_color normal)
    end
    echo ""
    echo (set_color cyan)"  Active / fallback chain:"(set_color normal)
    if test -f "$script"
        $py $script models 2>/dev/null | head -8 | while read -l row
            echo (set_color brblack)"    $row"(set_color normal)
        end
    end
end

function ai-pref --description "Set preferred AI provider and model"
    set -l provider ""
    set -l model ""
    
    if test (count $argv) -eq 0
        echo "Usage: ai-pref <provider> [model]"
        echo ""
        ai-models
        echo ""
        echo (set_color cyan)"Examples:"(set_color normal)
        echo "  ai-pref openrouter anthropic/claude-3.5-sonnet"
        echo "  ai-pref anthropic claude-sonnet-4-20250514"
        echo "  ai-pref gemini gemini-2.0-flash"
        echo "  ai-pref clear"
        return 0
    end
    
    set -l arg1 (string lower $argv[1])
    if test "$arg1" = kimi
        set arg1 moonshot
    end
    if test "$arg1" = google
        set arg1 gemini
    end
    if test "$arg1" = hf
        set arg1 huggingface
    end
    
    # Clear preference
    if test "$arg1" = clear
        set -gx AI_PREFERRED_PROVIDER ""
        set -gx AI_PREFERRED_MODEL ""
        if test -f $_ARKA_CFG/.env
            set -l env_content (cat $_ARKA_CFG/.env | grep -v '^AI_PREFERRED_PROVIDER=' | grep -v '^AI_PREFERRED_MODEL=')
            printf "%s\n" $env_content > $_ARKA_CFG/.env
        end
        echo (set_color green)"✓ Preference cleared and removed from $_ARKA_CFG/.env permanently"(set_color normal)
        return 0
    end
    
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_llm.py)
    set -l def ""
    if test -f "$script"
        set -l row ($py $script providers 2>/dev/null | string match -r "^$arg1\t")
        if test -n "$row"
            set -l parts (string split \t "$row")
            if test (count $parts) -ge 4
                set provider $parts[1]
                set model $argv[2]
                test -z "$model"; and set model $parts[4]
            end
        end
    end
    if test -z "$provider"
        echo (set_color red)"Unknown provider: $arg1"(set_color normal)
        echo "Run ai-models for supported slugs."
        return 1
    end

    set -gx AI_PREFERRED_PROVIDER "$provider"
    set -gx AI_PREFERRED_MODEL "$model"

    if test -f $_ARKA_CFG/.env
        set -l env_content (cat $_ARKA_CFG/.env | grep -v '^AI_PREFERRED_PROVIDER=' | grep -v '^AI_PREFERRED_MODEL=')
        printf "%s\n" $env_content > $_ARKA_CFG/.env
        echo "AI_PREFERRED_PROVIDER=$provider" >> $_ARKA_CFG/.env
        echo "AI_PREFERRED_MODEL=$model" >> $_ARKA_CFG/.env
    else
        echo "AI_PREFERRED_PROVIDER=$provider" > $_ARKA_CFG/.env
        echo "AI_PREFERRED_MODEL=$model" >> $_ARKA_CFG/.env
    end

    echo (set_color --bold green)"✓ Preference set & saved permanently: $provider → $model"(set_color normal)
end

function ai-skill-model --description "Set or list per-skill / per-profile LLM model choices"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_llm.py)
    if test (count $argv) -eq 0
        if test -f "$script"
            $py $script skill-models list
        else
            echo "Usage: ai-skill-model <skill|profile> <provider/model>"
            echo "       ai-skill-model show <skill|profile>"
            echo "       ai-skill-model clear <skill|profile>"
            echo "       ai-skill-model profiles"
        end
        return 0
    end

    set -l arg1 (string lower $argv[1])
    if test "$arg1" = profiles
        if test -f "$script"
            $py $script skill-models list --profiles-only
        end
        return 0
    end
    if test "$arg1" = show
        if test (count $argv) -lt 2
            echo "Usage: ai-skill-model show <skill|profile>"
            return 1
        end
        $py $script skill-models show $argv[2]
        return $status
    end
    if test "$arg1" = clear
        if test (count $argv) -lt 2
            echo "Usage: ai-skill-model clear <skill|profile>"
            return 1
        end
        $py $script skill-models clear $argv[2]
        return $status
    end
    if test (count $argv) -lt 2
        echo "Usage: ai-skill-model <skill|profile> <provider/model>"
        echo "Examples:"
        echo "  ai-skill-model web_answer groq/llama-3.3-70b-versatile"
        echo "  ai-skill-model chat gemini/gemini-2.5-flash"
        echo "  ai-skill-model pdf_ask anthropic/claude-sonnet-4-20250514"
        return 1
    end
    $py $script skill-models set $argv[1] $argv[2]
end

function select_model --description "Recommend LLM models based on PC CPU, RAM, GPU, and disk"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: select_model [--apply] [--json]"
        echo "       select_model recommend [--apply]"
        echo "       select_model probe"
        echo ""
        echo "NL: arka select best model for my pc"
        echo "    arka optimize models for my hardware"
        echo "    arka apply best model for my laptop"
        return 1
    end
    $py (_arka_py_script arka_model_advisor.py) $argv
    return $status
end

function model_select --description "Alias for select_model"
    select_model $argv
end

function best_model --description "Alias for select_model"
    select_model $argv
end

function personalize --description "Onboarding wizard and skill recommendations from your interests"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_personalize.py) wizard
        return $status
    end
    $py (_arka_py_script arka_personalize.py) $argv
    return $status
end

# --- Virtual Environment Skills ---
function activate_venv --description "Activate a virtual environment in current or specified directory"
    set -l venv_path ""
    
    if test (count $argv) -gt 0
        # Use provided path
        set venv_path $argv[1]
    else
        # Look for common venv names in current directory
        set -l venv_names .venv venv env virtualenv
        for name in $venv_names
            if test -d "$name"
                set venv_path "$name"
                break
            end
        end
    end
    
    if test -z "$venv_path"
        echo (set_color red)"No virtual environment found. Usage: activate_venv [path]"(set_color normal)
        return 1
    end
    
    if test -f "$venv_path/bin/activate.fish"
        source "$venv_path/bin/activate.fish"
        echo (set_color --bold green)"✓ Activated: $venv_path"(set_color normal)
    else if test -f "$venv_path/Scripts/Activate.fish"
        source "$venv_path/Scripts/Activate.fish"
        echo (set_color --bold green)"✓ Activated: $venv_path (Windows)"(set_color normal)
    else
        echo (set_color red)"No activate.fish found in $venv_path"(set_color normal)
        return 1
    end
end

function create_venv --description "Create a new virtual environment"
    set -l venv_name ".venv"
    set -l python_cmd "python3"
    
    # Parse arguments
    if test (count $argv) -gt 0
        set venv_name $argv[1]
    end
    
    # Check if name ends with specific python version
    if string match -qr '^python[0-9]+$' -- $venv_name
        set python_cmd $venv_name
        set venv_name ".venv"
    end
    
    # Check if python is available
    if not command -v $python_cmd &>/dev/null
        echo (set_color red)"Python command '$python_cmd' not found"(set_color normal)
        return 1
    end
    
    if test -d "$venv_name"
        echo (set_color yellow)"Virtual environment '$venv_name' already exists"(set_color normal)
        echo (set_color brblack)"Use 'activate_venv $venv_name' to activate it"(set_color normal)
        return 1
    end
    
    echo (set_color cyan)"Creating virtual environment: $venv_name with $python_cmd"(set_color normal)
    $python_cmd -m venv "$venv_name"
    
    if test -d "$venv_name"
        echo (set_color --bold green)"✓ Created: $venv_name"(set_color normal)
        echo (set_color brblack)"Run 'activate_venv $venv_name' to activate"(set_color normal)
    else
        echo (set_color red)"Failed to create virtual environment"(set_color normal)
        return 1
    end
end

function fix_venv --description "Recreate a virtual environment by deleting the existing one and creating it again"
    set -l venv_name ".venv"
    set -l python_cmd "python3"
    
    # Parse arguments
    if test (count $argv) -gt 0
        set venv_name $argv[1]
    end
    if test (count $argv) -gt 1
        set python_cmd $argv[2]
    end
    
    echo (set_color cyan)"🔧 Re-creating virtual environment '$venv_name'..."
    
    if test -d "$venv_name"
        echo (set_color yellow)"  🗑️ Deleting existing virtual environment: $venv_name"
        rm -rf "$venv_name"
    end
    
    echo (set_color cyan)"  📦 Creating fresh virtual environment..."
    $python_cmd -m venv "$venv_name"
    
    if test -d "$venv_name"
        echo (set_color --bold green)"✓ Successfully recreated: $venv_name"(set_color normal)
        echo (set_color brblack)"Run 'activate_venv $venv_name' to activate"(set_color normal)
    else
        echo (set_color red)"✗ Failed to recreate virtual environment"(set_color normal)
        return 1
    end
end


# --- File & Script Management Skills ---
function create_folder --description "Create one or more directories"
    if test (count $argv) -eq 0
        echo "Usage: create_folder <folder1> [folder2] ..."
        return 1
    end

    for folder in $argv
        if test -d "$folder"
            echo (set_color yellow)"⚠ Already exists: $folder"(set_color normal)
        else
            mkdir -p "$folder"
            if test -d "$folder"
                echo (set_color --bold green)"✓ Created: $folder"(set_color normal)
            else
                echo (set_color red)"✗ Failed: $folder"(set_color normal)
            end
        end
    end
end

function _arka_downloads_dir --description "Platform Downloads folder (internal)"
    if set -q AIE_DOWNLOADS_DIR; and test -n "$AIE_DOWNLOADS_DIR"; and test -d "$AIE_DOWNLOADS_DIR"
        echo (realpath "$AIE_DOWNLOADS_DIR" 2>/dev/null; or echo "$AIE_DOWNLOADS_DIR")
        return 0
    end
    if test -d "$HOME/Downloads"
        echo (realpath "$HOME/Downloads" 2>/dev/null; or echo "$HOME/Downloads")
        return 0
    end
    if set -q USERPROFILE; and test -d "$USERPROFILE/Downloads"
        echo (realpath "$USERPROFILE/Downloads" 2>/dev/null; or echo "$USERPROFILE/Downloads")
        return 0
    end
    echo "$HOME/Downloads"
end

function _resolve_folder_path --description "Expand ~ and common folder names from a path fragment (internal)"
    set -l path (string trim -- $argv[1])
    if test -z "$path"
        echo "."
        return 0
    end
    set -l lower (string lower "$path")
    switch $lower
        case downloads download
            _arka_downloads_dir
            return 0
        case desktop
            set path Desktop
        case documents document
            set path Documents
        case pictures picture photos photo
            set path Pictures
        case videos video
            set path Videos
        case music
            set path Music
    end
    set path (string replace -a '~' "$HOME" -- $path)
    if test -d "$path"
        echo (realpath "$path" 2>/dev/null; or echo "$path")
        return 0
    end
    if test -d "$HOME/$path"
        echo (realpath "$HOME/$path" 2>/dev/null; or echo "$HOME/$path")
        return 0
    end
    if test -d "./$path"
        echo (realpath "./$path" 2>/dev/null; or echo "./$path")
        return 0
    end
    echo "$path"
end

function _parse_file_size_root --description "Extract search root from NL file-size query (internal)"
    set -l text "$argv[1]"
    set -l lower (string lower "$text")

    set -l folder_m (string match -r '(?i)\s+in\s+(?:my\s+)?(?:the\s+)?(downloads?|desktop|documents?|document|pictures?|picture|photos?|photo|videos?|video|music)\s*$' "$text")
    if test (count $folder_m) -ge 2
        _resolve_folder_path $folder_m[2]
        return 0
    end

    set -l fi_m (string match -r '(?i)\b(?:large\s+)?files?\s+in\s+(?:my\s+)?(?:the\s+)?(\S+)' "$text")
    if test (count $fi_m) -ge 2
        _resolve_folder_path $fi_m[2]
        return 0
    end

    for name in downloads download desktop documents document pictures picture photos photo videos video music
        if string match -qr "(?i)\b$name\b" "$lower"
            _resolve_folder_path $name
            return 0
        end
    end

    set -l in_m (string match -r '(?i)\s+in\s+(.+)$' "$text")
    if test (count $in_m) -ge 2
        set -l tail (string trim -- $in_m[2])
        if string match -qr '(?i)^(range|between|the\s+range)\b' "$tail"
            echo "."
            return 0
        end
        _resolve_folder_path $tail
        return 0
    end

    echo "."
end

function list_folders --description "List folder names in a directory (directories only)"
    set -l dir "."
    if test (count $argv) -ge 1
        set dir (_resolve_folder_path "$argv[1]")
    end
    if not test -d "$dir"
        printf '%s\n' (set_color red)"Not a directory: $dir"(set_color normal)
        return 1
    end
    set -l resolved (realpath "$dir" 2>/dev/null; or echo "$dir")
    printf "Folders in: %s\n" "$resolved"
    set -l count 0
    for entry in $dir/*/
        set count (math $count + 1)
        printf '  > %s\n' (basename $entry)
    end
    if test $count -eq 0
        printf '%s\n' (set_color yellow)"  (no subfolders)"(set_color normal)
    else
        printf '%s\n' (set_color brblack)"  $count folder(s)"(set_color normal)
    end
end

function show_folder --description "Show files and folders inside a directory"
    set -l dir "."
    if test (count $argv) -ge 1
        set dir (_resolve_folder_path "$argv[1]")
    end
    if not test -d "$dir"
        printf '%s\n' (set_color red)"Not a directory: $dir"(set_color normal)
        return 1
    end
    set -l resolved (realpath "$dir" 2>/dev/null; or echo "$dir")
    printf "Contents of: %s\n" "$resolved"
    if command -v eza >/dev/null
        eza -la --group-directories-first --icons "$dir"
    else
        command ls -la "$dir"
    end
end

function list_files --description "List files (not folders) in a directory"
    set -l dir "."
    set -l depth 1
    if test (count $argv) -ge 1
        set dir (_resolve_folder_path "$argv[1]")
    end
    if test (count $argv) -ge 2; and string match -qr '^[0-9]+$' -- "$argv[2]"
        set depth $argv[2]
    end
    if not test -d "$dir"
        printf '%s\n' (set_color red)"Not a directory: $dir"(set_color normal)
        return 1
    end
    set -l resolved (realpath "$dir" 2>/dev/null; or echo "$dir")
    printf "Files in: %s (depth %s)\n" "$resolved" "$depth"
    find "$dir" -mindepth 1 -maxdepth $depth -type f 2>/dev/null | while read -l f
        set -l rel (string replace "$dir/" "" "$f")
        set -l sz (du -h "$f" 2>/dev/null | cut -f1)
        printf '  %s  (%s)\n' "$rel" "$sz"
    end
end

function search_files --description "Search for files by name pattern under a directory"
    if test (count $argv) -lt 1
        echo "Usage: search_files <pattern> [directory] [max_depth]"
        echo "Example: search_files report ~/Documents 3"
        return 1
    end
    set -l pattern $argv[1]
    set -l root "."
    set -l maxdepth 5
    if test (count $argv) -ge 2
        set root (_resolve_folder_path "$argv[2]")
    end
    if test (count $argv) -ge 3; and string match -qr '^[0-9]+$' -- "$argv[3]"
        set maxdepth $argv[3]
    end
    if not test -d "$root"
        printf '%s\n' (set_color red)"Not a directory: $root"(set_color normal)
        return 1
    end
    set -l resolved (realpath "$root" 2>/dev/null; or echo "$root")
    printf "Searching for '*%s' under %s\n" "$pattern" "$resolved"
    set -l results (find "$root" -maxdepth $maxdepth -type f -iname "*$pattern*" 2>/dev/null)
    if test (count $results) -eq 0
        printf '%s\n' (set_color yellow)"  No files found."(set_color normal)
        return 1
    end
    for f in $results[1..50]
        printf '  %s\n' "$f"
    end
    if test (count $results) -gt 50
        printf '%s\n' (set_color brblack)"  ... and "(count $results)" total (showing first 50)"(set_color normal)
    end
end

function _find_size_unit --description "Map NL size unit to find -size suffix (internal)"
    set -l raw_unit (string lower "$argv[1]")
    switch $raw_unit
        case b byte bytes
            echo c
        case k kb
            echo k
        case m mb ''
            echo M
        case g gb
            echo G
    end
end

function _parse_file_size_range --description "Parse min/max from NL size range (internal)"
    set -l text "$argv[1]"
    set -l m (string match -r '(?i)(?:range\s+of|between|from)\s+(\d+(?:\.\d+)?)\s*(kb|mb|gb|bytes?|b|k|m|g)?\s+(?:to|and|-)\s+(\d+(?:\.\d+)?)\s*(kb|mb|gb|bytes?|b|k|m|g)\b' "$text")
    if test (count $m) -ge 5
        set -l u1 $m[3]
        test -z "$u1"; and set u1 $m[5]
        printf '%s\n' $m[2] $m[4] $u1 $m[5]
        return 0
    end
    set m (string match -r '(?i)(\d+(?:\.\d+)?)\s*(kb|mb|gb|bytes?|b|k|m|g)\b\s+(?:to|and|-)\s+(\d+(?:\.\d+)?)\s*(kb|mb|gb|bytes?|b|k|m|g)\b' "$text")
    if test (count $m) -ge 5
        printf '%s\n' $m[2] $m[4] $m[3] $m[5]
        return 0
    end
    set m (string match -r '(?i)between\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)\s*(kb|mb|gb|bytes?|b|k|m|g)\b' "$text")
    if test (count $m) -ge 4
        printf '%s\n' $m[2] $m[3] $m[4] $m[4]
        return 0
    end
    return 1
end

function find_files_by_size --description "Find files smaller or larger than a size threshold"
    set -l text (string join " " $argv)
    if test -z "$text"
        echo "Usage: find_files_by_size find files less than 100mb [in ~/path]"
        echo "Example: find files larger than 1gb in ~/Downloads"
        return 1
    end

    set -l clean (string lower "$text")
    set -l root (_parse_file_size_root "$text")

    if not test -d "$root"
        printf '%s\n' (set_color red)"Not a directory: $root"(set_color normal)
        return 1
    end

    set -l resolved (realpath "$root" 2>/dev/null; or echo "$root")

    set -l range (_parse_file_size_range "$text" 2>/dev/null)
    if test (count $range) -eq 4
        set -l min_num (math -s0 $range[1])
        set -l max_num (math -s0 $range[2])
        set -l min_unit (_find_size_unit $range[3])
        set -l max_unit (_find_size_unit $range[4])
        if test $min_num -gt $max_num
            set -l tmp_num $min_num
            set min_num $max_num
            set max_num $tmp_num
            set -l tmp_unit $min_unit
            set min_unit $max_unit
            set max_unit $tmp_unit
        end
        set -l min_spec "+"(math -s0 $min_num - 1)"$min_unit"
        set -l max_spec "-"(math -s0 $max_num + 1)"$max_unit"
        set -l min_label "$min_num"(string upper "$range[3]")
        set -l max_label "$max_num"(string upper "$range[4]")
        printf "Files between %s and %s under %s\n" "$min_label" "$max_label" "$resolved"

        set -l results (find "$root" -type f -size $min_spec -size $max_spec 2>/dev/null)
        if test (count $results) -eq 0
            printf '%s\n' (set_color yellow)"  No files found."(set_color normal)
            return 1
        end

        set -l sorted (du -k $results 2>/dev/null | sort -rn -k1 | cut -f2-)
        for f in $sorted[1..100]
            set -l sz (du -h "$f" 2>/dev/null | cut -f1)
            printf '  %s  (%s)\n' "$f" "$sz"
        end
        if test (count $sorted) -gt 100
            printf '%s\n' (set_color brblack)"  ... and "(count $sorted)" total (showing first 100)"(set_color normal)
        end
        return 0
    end

    set -l sign "-"
    if string match -qr '(?i)(more|greater|larger|over|above|bigger)(\s+than)?|\bover\s+\d' "$clean"
        set sign "+"
    end

    set -l sm (string match -r '(?i)(\d+(?:\.\d+)?)\s*(kb|mb|gb|bytes?|b|k|m|g)\b' "$text")
    set -l num 0
    set -l raw_unit mb
    if test (count $sm) -ge 2
        set num (math -s0 $sm[2])
        set raw_unit (string lower "$sm[3]")
    else if string match -qr '(?i)\b(large|big|huge)\b' "$clean"
        set num 100
        set raw_unit mb
    else
        echo (set_color red)"Could not parse size from: $text"(set_color normal)
        echo "Example: find files less than 100mb"
        return 1
    end
    set -l unit M
    switch $raw_unit
        case b byte bytes
            set unit c
        case k kb
            set unit k
        case m mb ''
            set unit M
        case g gb
            set unit G
    end

    set -l size_spec "$sign$num$unit"
    set -l op "smaller than"
    if test "$sign" = "+"
        set op "larger than"
    end

    printf "Files %s %s%s under %s\n" "$op" "$num" (string upper "$raw_unit") "$resolved"

    set -l results (find "$root" -type f -size $size_spec 2>/dev/null)
    if test (count $results) -eq 0
        printf '%s\n' (set_color yellow)"  No files found."(set_color normal)
        return 1
    end

    for f in $results[1..100]
        set -l sz (du -h "$f" 2>/dev/null | cut -f1)
        printf '  %s  (%s)\n' "$f" "$sz"
    end
    if test (count $results) -gt 100
        printf '%s\n' (set_color brblack)"  ... and "(count $results)" total (showing first 100)"(set_color normal)
    end
end

function open_file --description "Open a file with the default application"
    if test (count $argv) -lt 1
        echo "Usage: open_file <file> [file2 ...]"
        return 1
    end
    for f in $argv
        set -l path (_resolve_folder_path "$f")
        if not test -f "$path"
            echo (set_color red)"✗ Not a file: $path"(set_color normal)
            continue
        end
        _arka_open "$path" 2>/dev/null &
        disown 2>/dev/null
        echo (set_color green)"✓ Opened: $path"(set_color normal)
    end
end

function _launch_clapper --description "Open one or more media files in Clapper (internal)"
    set -l clapper_bin ""
    if command -v flatpak >/dev/null
        and flatpak info com.github.rafostar.Clapper &>/dev/null
        set clapper_bin flatpak
        set -l flatpak_args run com.github.rafostar.Clapper
        $clapper_bin $flatpak_args $argv &
        disown 2>/dev/null
        return 0
    end
    if command -v clapper >/dev/null
        clapper $argv &
        disown 2>/dev/null
        return 0
    end
    return 1
end

function _play_media_mpv --description "Play video with mpv (internal fallback step)"
    command -v mpv &>/dev/null; or return 1
    mpv $argv[1]
end

function _play_media_vlc --description "Play video with vlc (internal fallback step)"
    command -v vlc &>/dev/null; or return 1
    vlc $argv[1] &
    disown 2>/dev/null
end

function _play_media_clapper --description "Play video with Clapper flatpak/native (internal fallback step)"
    _launch_clapper $argv[1]
end

function _play_media_file --description "Play one video: Clapper → mpv → vlc"
    set -l file $argv[1]
    if _fallback_try _play_media_clapper _play_media_mpv _play_media_vlc -- "$file"
        return 0
    end
    printf '%s\n' (set_color red)"Install Clapper (flatpak install flathub com.github.rafostar.Clapper), mpv, or vlc."(set_color normal)
    return 1
end

function _play_query_text --description "Join play skill argv into one search string (internal)"
    if test (count $argv) -eq 0
        echo ""
        return
    end
    echo (string trim -- (string join " " $argv))
end

function _play_normalize_media_query --description "Strip play/movie/song filler from NL media requests (internal)"
    set -l q (string trim -- "$argv[1]")
    test -z "$q"; and echo ""; and return

    if string match -qr '^(\~|/|\./|\../)' "$q"
        echo "$q"
        return
    end

    set q (string replace -r -i '^(please\s+)?(can you\s+)?(i want to\s+)?(play|watch|start|open|run|show)\s+(me\s+)?' '' "$q")
    set q (string replace -r -i '^(?:the\s+)?(?:a\s+|an\s+)?' '' "$q")
    set q (string replace -r -i '^(?:movie|film|video|videos?|song|songs?|music|track|tracks?|audio)\s+' '' "$q")
    set q (string replace -r -i '\s+(?:movie|film|video|videos?|song|songs?|music|track|tracks?|audio)$' '' "$q")
    set q (string replace -r -i '\s+(?:please|now|for me)$' '' "$q")
    set q (string replace -r -i '^(?:movie|film|video|videos?|song|songs?|music|track|tracks?|audio)\s+' '' "$q")
    echo (string trim -- "$q")
end

function _agent_play_media_candidates --description "Play skills offline rules could match (internal)"
    set -l cmd "$argv[1]"
    set -l clean (string lower "$cmd")
    set -l cands

    if string match -qr '(?i)(play.*spotify|spotify)' "$clean"
        set -a cands play_spotify
    end
    if string match -qr '(?i)(play\s+.*youtube|play\s+(?:a\s+|an\s+)?(?:video|episode|anime)|watch\s+(?:a\s+|an\s+)?|watch\s+.*youtube)' "$clean"
        and not string match -qr '(?i)(summarize|summary|transcript|research|digest|caption|download|transcribe|playlist)' "$clean"
        set -a cands play_youtube
    end
    if string match -qr '(?i)(play.*song|random.*song|local.*music)' "$clean"
        set -a cands play_song
    end
    if string match -qr '(?i)(play.*movie|play.*film|play\s+(?:local\s+)?media|rplay|play\s+.+\s+(movie|film|video))' "$clean"
        set -a cands play_movie
    end
    if string match -qr '(?i)^play\s+.+\s+(from|by)\s+' "$clean"
        contains -- play_song $cands; or set -a cands play_song
    end
    if string match -qr '(?i)^play\s+\S' "$clean"
        if string match -qr '(?i)\b(song|music|track|audio)\b' "$clean"
            contains -- play_song $cands; or set -a cands play_song
        end
        if string match -qr '(?i)\bspotify\b' "$clean"
            contains -- play_spotify $cands; or set -a cands play_spotify
        end
        if string match -qr '(?i)\b(movie|film|video)\b' "$clean"
            contains -- play_movie $cands; or set -a cands play_movie
        end
    end

    set -l uniq
    for c in $cands
        contains -- $c $uniq; or set -a uniq $c
    end
    printf '%s\n' $uniq
end

function _agent_play_route_ambiguous --description "True when multiple play/media routes collide (internal)"
    set -l uniq (_agent_play_media_candidates "$argv[1]")
    test (count $uniq) -gt 1
end

function _agent_route_play_ambiguous --description "Resolve conflicting play routes via LLM or offline tie-break (internal)"
    set -l cmd "$argv[1]"
    set -l skills "$argv[2]"
    if test "$(_arka_route_mode)" != symbolic_only
        set -l llm (_agent_llm_route "$cmd" "$skills")
        if test -n "$llm"
            echo "$llm"
            return 0
        end
    end
    set -l clean (string lower "$cmd")
    set -l q (_play_normalize_media_query "$cmd")
    if string match -qr '(?i)spotify' "$clean"
        printf 'play_spotify %s\n' "$q"
        return 0
    end
    if string match -qr '(?i)youtube|\bepisode\b' "$clean"
        printf 'play_youtube %s\n' "$q"
        return 0
    end
    if string match -qr '(?i)\b(film|movie|video)\b' "$clean"; and not string match -qr '(?i)\b(song|music|track)\b' "$clean"
        printf 'play_movie %s\n' "$q"
        return 0
    end
    if string match -qr '(?i)\b(song|music|track|audio)\b' "$clean"; and not string match -qr '(?i)\b(film|movie|video)\b' "$clean"
        printf 'play_song %s\n' "$q"
        return 0
    end
    if string match -qr '(?i)\b(film|movie)\b' "$clean"
        printf 'play_movie %s\n' "$q"
        return 0
    end
    printf 'play_song %s\n' "$q"
end

function _play_search_terms --description "Search terms from play query; prefers artist after from/by (internal)"
    set -l q (_play_query_text $argv)
    set -l terms

    set -l m (string match -r '(?i)^(.+?)\s+from\s+(.+)$' -- "$q")
    if test (count $m) -ge 3
        set -a terms (string trim -- "$m[2] $m[3]")
        set -a terms (string trim -- $m[3])
    else
        set m (string match -r '(?i)^(.+?)\s+by\s+(.+)$' -- "$q")
        if test (count $m) -ge 3
            set -a terms (string trim -- "$m[2] $m[3]")
            set -a terms (string trim -- $m[3])
        end
    end

    if test (count $terms) -eq 0
        set terms $q
    end
    printf '%s\n' $terms
end

function _file_matches_query --description "True if file matches search term (all words must match path) (internal)"
    set -l f $argv[1]
    set -l term $argv[2]
    set -l haystack (basename "$f")" "(basename (dirname "$f"))
    set -l stopwords play please the a an movie film video song music track audio me my
    set -l matched 0
    for w in (string split " " -- $term)
        if test -z "$w"
            continue
        end
        if contains -- (string lower "$w") $stopwords
            continue
        end
        if not string match -qi "*$w*" -- "$haystack"
            return 1
        end
        set matched 1
    end
    test $matched -eq 1
end

function _play_media_folder --description "Play all videos in a folder with Clapper (internal)"
    set -l dir $argv[1]
    set -l files (find "$dir" -maxdepth 1 -type f \
        \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" -o -iname "*.webm" -o -iname "*.mov" \) \
        2>/dev/null | sort)
    if test (count $files) -eq 0
        printf '%s\n' (set_color yellow)"No video files in: $dir"(set_color normal)
        return 1
    end
    if not _launch_clapper $files
        set -l rplay_py /home/s/Projects/python/venv/bin/python3
        set -l rplay_script /home/s/Projects/python/medialistplay.py
        $rplay_py $rplay_script "$dir"
        return $status
    end
end

function play_movie --description "Play videos/movies by folder path or title search (Clapper)"
    set -l search_dirs "$HOME/Videos/movies" "$HOME/Videos" "$HOME/Movies" "$PWD"

    if test (count $argv) -ge 1
        set -l query (_play_normalize_media_query (_play_query_text $argv))
        set -l target (_resolve_folder_path "$query")

        if test -d "$target"
            echo (set_color cyan)"▶ Playing in Clapper: $target"(set_color normal)
            _play_media_folder "$target"
            return $status
        end
        if test -f "$target"
            echo (set_color cyan)"▶ Playing in Clapper: $target"(set_color normal)
            _play_media_file "$target"
            return $status
        end

        set -l terms (_play_search_terms $query)
        echo (set_color cyan)"Searching for video: $query"(set_color normal)
        set -l matches
        for term in $terms
            for dir in $search_dirs
                if not test -d "$dir"
                    continue
                end
                for f in (find "$dir" -maxdepth 5 -type f \
                    \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" -o -iname "*.webm" -o -iname "*.mov" \) \
                    2>/dev/null)
                    if _file_matches_query "$f" $term
                        set -a matches "$f"
                    end
                end
            end
            if test (count $matches) -gt 0
                break
            end
        end

        if test (count $matches) -eq 0
            printf '%s\n' (set_color yellow)"No video matching '$query'; trying music..."(set_color normal)
            play_song $argv
            return $status
        end

        if test (count $matches) -gt 1
            printf '%s\n' (set_color yellow)"Multiple matches:"(set_color normal)
            set -l i 1
            for m in $matches[1..10]
                printf '  %s) %s\n' $i (string replace "$HOME/" '~/' -- $m)
                set i (math $i + 1)
            end
            if test (count $matches) -gt 10
                printf '  ... and %s more\n' (math (count $matches) - 10)
            end
        end

        set -l pick $matches[1]
        echo (set_color green)"▶ Playing in Clapper: "(set_color normal)(string replace "$HOME/" '~/' -- $pick)
        _play_media_file "$pick"
        return $status
    end

    set -l search_dirs "$HOME/Videos/movies" "$HOME/Videos" "$HOME/Movies" "$PWD"
    echo (set_color cyan)"Looking for movies/videos..."(set_color normal)
    for dir in $search_dirs
        if not test -d "$dir"
            continue
        end
        set -l found (find "$dir" -maxdepth 2 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" -o -iname "*.webm" -o -iname "*.mov" \) 2>/dev/null | head -1)
        if test -n "$found"
            echo (set_color green)"✓ Found media in: $dir"(set_color normal)
            list_folders "$dir"
            echo ""
            _play_media_folder "$dir"
            return $status
        end
    end

    echo (set_color yellow)"⚠ No media files in current folder or usual locations."(set_color normal)
    echo (set_color brblack)"  Checked: $search_dirs"(set_color normal)
    echo (set_color cyan)"  Tip: play_movie ~/Videos/movies   or   list_folders ~/Videos"(set_color normal)
    return 1
end

function write_script --description "Create a Python script with the given name and optional content"
    if test (count $argv) -eq 0
        echo "Usage: write_script <filename> [content]"
        echo "Example: write_script hello.py 'print(\"Hello World\")'"
        return 1
    end

    set -l filename $argv[1]
    set -l content ""

    # If filename ends with .py, it's a Python script
    if not string match -qr '\.py$' -- $filename
        set filename "$filename.py"
    end

    # If content is provided as remaining args
    if test (count $argv) -gt 1
        set content (string join " " $argv[2..-1])
    else
        # Interactive mode - read from stdin
        echo (set_color cyan)"Enter script content (Ctrl+D to finish):"(set_color normal)
        set content (cat)
    end

    # Check if file exists
    if test -f "$filename"
        echo (set_color yellow)"⚠ File already exists: $filename"(set_color normal)
        echo -n (set_color --bold cyan)"Overwrite? (y/n): "(set_color normal)
        read -l confirm
        if not string match -qi "y*" "$confirm"
            echo "Aborted."
            return 0
        end
    end

    # Write the file
    printf '%s' "$content" > "$filename"

    if test -f "$filename"
        echo (set_color --bold green)"✓ Created: $filename"(set_color normal)
    else
        echo (set_color red)"✗ Failed to create: $filename"(set_color normal)
        return 1
    end
end

function run_script --description "Run a Python script with optional arguments"
    if test (count $argv) -eq 0
        echo "Usage: run_script <script.py> [args...]"
        echo "Example: run_script hello.py arg1 arg2"
        return 1
    end

    set -l script $argv[1]
    set -l script_args $argv[2..-1]

    # Add .py if not present
    if not string match -qr '\.py$' -- $script
        set script "$script.py"
    end

    if not test -f "$script"
        echo (set_color red)"✗ Script not found: $script"(set_color normal)
        return 1
    end

    # Check for virtual environment and use it if available
    set -l python_cmd "python3"
    if test -f "./venv/bin/python"
        set python_cmd "./venv/bin/python"
    else if test -f ".venv/bin/python"
        set python_cmd ".venv/bin/python"
    end

    echo (set_color cyan)"▶ Running: $script"(set_color normal)
    if test (count $script_args) -gt 0
        $python_cmd "$script" $script_args
    else
        $python_cmd "$script"
    end
end

function ollama_run --description "Run a local LLM using Ollama"
    if test (count $argv) -eq 0
        echo "Usage: ollama_run <model> [prompt]"
        echo "Example: ollama_run llama3.2:1b 'Hello, how are you?'"
        echo ""
        echo "Available models:"
        ollama list 2>/dev/null | head -20
        return 1
    end

    set -l model $argv[1]
    set -l prompt (string join " " $argv[2..-1])

    # Check if ollama is running
    if not curl -s http://localhost:11434/api/tags &>/dev/null
        echo (set_color yellow)"Starting Ollama service..."(set_color normal)
        ollama serve &
        sleep 3
    end

    if test -z "$prompt"
        # Interactive mode
        echo (set_color cyan)"Starting interactive chat with $model (Ctrl+C to exit)"(set_color normal)
        ollama run $model
    else
        # Single prompt mode
        echo (set_color cyan)"▶ Querying: $model"(set_color normal)
        ollama run $model "$prompt"
    end
end

function lint_python --description "Lint Python files using flake8/pylint/ruff"
    set -l target "."
    set -l tool "flake8"
    set -l verbose false

    # Parse arguments
    for arg in $argv
        switch $arg
            case -v --verbose
                set verbose true
            case -f --flake8
                set tool "flake8"
            case -p --pylint
                set tool "pylint"
            case -r --ruff
                set tool "ruff"
            case '*'
                if test -f "$arg"
                    set target "$arg"
                else if test -d "$arg"
                    set target "$arg"
                end
        end
    end

    # Check if target exists
    if not test -e "$target"
        echo (set_color red)"✗ Target not found: $target"(set_color normal)
        return 1
    end

    # Auto-detect tool if not specified (ruff → pylint → flake8)
    if test "$tool" = "flake8"
        for t in ruff pylint flake8
            if command -v $t &>/dev/null
                set tool $t
                break
            end
        end
    end

    echo (set_color cyan)"🔍 Linting $target with $tool..."(set_color normal)

    switch $tool
        case flake8
            if command -v flake8 &>/dev/null
                if test "$verbose" = "true"
                    flake8 --verbose $target
                else
                    flake8 $target
                end
            else
                echo (set_color red)"✗ flake8 not installed"(set_color normal)
                echo "Install: pip install flake8"
                return 1
            end
        case pylint
            if command -v pylint &>/dev/null
                pylint $target
            else
                echo (set_color red)"✗ pylint not installed"(set_color normal)
                echo "Install: pip install pylint"
                return 1
            end
        case ruff
            if command -v ruff &>/dev/null
                if test "$verbose" = "true"
                    ruff check $target --verbose
                else
                    ruff check $target
                end
            else
                echo (set_color red)"✗ ruff not installed"(set_color normal)
                echo "Install: pip install ruff"
                return 1
            end
    end
end

function _play_audio_mpv --description "Play audio with mpv (internal fallback step)"
    command -v mpv &>/dev/null; or return 1
    mpv --no-terminal $argv[1] &>/dev/null &
    disown 2>/dev/null
end

function _play_audio_cvlc --description "Play audio with cvlc (internal fallback step)"
    command -v cvlc &>/dev/null; or return 1
    cvlc $argv[1] 2>/dev/null
end

function _play_audio_mpg123 --description "Play audio with mpg123 (internal fallback step)"
    command -v mpg123 &>/dev/null; or return 1
    mpg123 $argv[1] 2>/dev/null
end

function _play_audio_ffplay --description "Play audio with ffplay (internal fallback step)"
    command -v ffplay &>/dev/null; or return 1
    ffplay -nodisp -autoexit $argv[1] 2>/dev/null
end

function _play_audio_file --description "Play an audio file: mpv → cvlc → mpg123 → ffplay"
    if _fallback_try _play_audio_mpv _play_audio_cvlc _play_audio_mpg123 _play_audio_ffplay -- $argv[1]
        return 0
    end
    printf '%s\n' (set_color red)"No audio player found. Install: mpv, vlc, mpg123, or ffmpeg"(set_color normal)
    return 1
end

function play_song --description "Play a song by name search, or a random track if not found"
    set -l music_dirs ~/Music ~/music ~/Documents/Music ~/.local/share/music ~/Videos/YoutubeDownloads
    set -l audio_exts \( -iname "*.mp3" -o -iname "*.flac" -o -iname "*.wav" -o -iname "*.m4a" -o -iname "*.ogg" \)
    set -l query (_play_normalize_media_query (_play_query_text $argv))

    set -l all_songs
    for dir in $music_dirs
        if test -d "$dir"
            set -a all_songs (find "$dir" -type f $audio_exts 2>/dev/null)
        end
    end

    if test (count $all_songs) -eq 0
        printf '%s\n' (set_color red)"No music found. Checked: $music_dirs"(set_color normal)
        return 1
    end

    set -l song ""

    if test -n "$query"
        set -l terms (_play_search_terms $query)
        echo (set_color cyan)"Searching music for: $query"(set_color normal)
        set -l matches
        for term in $terms
            for f in $all_songs
                if _file_matches_query "$f" $term
                    set -a matches "$f"
                end
            end
            if test (count $matches) -gt 0
                break
            end
        end
        if test (count $matches) -gt 0
            set song $matches[1]
            if test (count $matches) -gt 1
                printf '%s\n' (set_color yellow)"Multiple matches; playing first of "(count $matches)"."(set_color normal)
            end
        else
            printf '%s\n' (set_color yellow)"No song matching '$query'; picking random."(set_color normal)
        end
    end

    if test -z "$song"
        set -l random_idx (random 1 (count $all_songs))
        set song $all_songs[$random_idx]
        if test -z "$query"
            echo (set_color cyan)"Playing random song:"(set_color normal)
        end
    end

    echo (set_color --bold cyan)"▶ Playing: $(basename "$song")"(set_color normal)
    _play_audio_file "$song"
end

function stop_music --description "Stop/pause local music (mpv), Spotify, and other MPRIS players"
    set -l stopped 0

    if command -v playerctl &>/dev/null
        for p in (playerctl -l 2>/dev/null)
            set -l st (playerctl --player=$p status 2>/dev/null)
            if test "$st" = Playing; or test "$st" = Paused
                playerctl --player=$p pause 2>/dev/null
                set stopped 1
            end
        end
    end

    if pgrep -x mpv &>/dev/null
        pkill -x mpv 2>/dev/null
        set stopped 1
    end

    if test $stopped -eq 0
        echo (set_color yellow)"Nothing playing to stop."(set_color normal)
        return 1
    end

    echo (set_color --bold yellow)"⏹ Stopped music playback."(set_color normal)
end

function play_youtube --description "Search and play a video or channel on YouTube using mpv and yt-dlp"
    if test (count $argv) -eq 0
        echo "Usage: play_youtube <search_query_or_channel_and_video>"
        echo "Example: play_youtube chilledcow lofi"
        echo "Example: play_youtube play an anime on youtube"
        return 1
    end

    set -l query (string join " " $argv)
    echo (set_color cyan) "🔍 Searching YouTube for: $query..."
    echo (set_color green) "▶ Playing match in mpv. Press 'q' to quit."
    
    mpv --ytdl-raw-options=remote-components=ejs:github,js-runtimes=node "ytdl://ytsearch:$query"
end

function _spotify_normalize_query --description "Strip NL filler and fix common typos in a song query"
    set -l q (string join " " $argv)
    set q (string replace -r -i '\s+on\s+spotify\s*' ' ' "$q")
    set q (string replace -r -i '^\s*spotify\s+' '' "$q")
    set q (string replace -r -i '^\s*play\s+' '' "$q")
    set q (string replace -r -i '\s+from\s+' ' ' "$q")
    set q (string replace -r -i '\s+by\s+' ' ' "$q")
    set q (string replace -r -i '\b(song|songs|track|tracks|music|audio)\b' ' ' "$q")
    set q (string replace -r -i 'hamuman' 'hanuman' "$q")
    set q (string replace -r '  +' ' ' "$q")
    echo (string trim "$q")
end

function _spotify_desktop_cmd --description "Detect Spotify desktop: native, flatpak, snap, or macOS app"
    if _arka_is_macos
        if test -d "/Applications/Spotify.app"
            echo macos
            return 0
        end
        return 1
    end
    if command -v spotify &>/dev/null
        echo native
        return 0
    end
    if command -v flatpak &>/dev/null
        if flatpak list --app 2>/dev/null | string match -qr 'com\.spotify\.Client'
            echo flatpak
            return 0
        end
    end
    if command -v snap &>/dev/null
        if snap list 2>/dev/null | string match -qr '^spotify\s'
            echo snap
            return 0
        end
    end
    return 1
end

function _spotify_start_desktop --description "Launch Spotify desktop if not running"
    set -l kind (_spotify_desktop_cmd 2>/dev/null)
    if test -z "$kind"
        return 1
    end

    if _arka_is_macos
        pgrep -x Spotify &>/dev/null; or pgrep -if 'Spotify.app' &>/dev/null
        and return 0
    else if pgrep -x spotify &>/dev/null; or pgrep -f '[s]potify' &>/dev/null
        return 0
    end

    echo (set_color brblack)"  Launching Spotify..."(set_color normal)
    switch $kind
        case macos
            open -a Spotify >/dev/null 2>&1
        case native
            spotify &
            disown
        case flatpak
            flatpak run com.spotify.Client &
            disown
        case snap
            snap run spotify &
            disown
    end
    sleep 3
end

function _spotify_dom_available --description "True if spotify_dom.py and Playwright are installed"
    test -f "$HOME/.config/fish/spotify_dom.py"
    and python3 -c "import playwright" 2>/dev/null
end

function _spotify_resolve_track_id_dom --description "Resolve track ID via Brave/CDP search (one browser session)"
    if not _spotify_dom_available
        return 1
    end
    _spotify_prepare_brave_cdp
    set -l script "$HOME/.config/fish/spotify_dom.py"
    set -l tid (python3 "$script" resolve "$argv" 2>/dev/null | tail -1)
    if string match -qr '^[a-zA-Z0-9]{10,}$' -- "$tid"
        echo $tid
        return 0
    end
    return 1
end

function _spotify_resolve_track_id --description "Resolve query to track ID: iTunes/web first, DOM search last"
    set -l query $argv[1]
    set -l tid (python3 -c "
import urllib.request, re, urllib.parse, sys, json

query = sys.argv[1].strip()
query_clean = re.sub(r'\b(song|songs|track|tracks|music|audio)\b', ' ', query, flags=re.I)
query_clean = ' '.join(query_clean.split())
headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

def ddg_tracks(q):
    try:
        url = 'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(q)
        req = urllib.request.Request(url, headers=headers)
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', 'replace')
        return re.findall(r'open\.spotify\.com/track/([a-zA-Z0-9]{10,})', html)
    except Exception:
        return []

def itunes_songs(term, limit=5):
    url = 'https://itunes.apple.com/search?term=' + urllib.parse.quote(term) + '&entity=song&limit=' + str(limit)
    req = urllib.request.Request(url, headers=headers)
    data = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
    return [(t.get('trackName', ''), t.get('artistName', '')) for t in data.get('results', [])]

def track_title(tid):
    try:
        oembed = 'https://open.spotify.com/oembed?url=https://open.spotify.com/track/' + tid
        req = urllib.request.Request(oembed, headers=headers)
        data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
        return (data.get('title') or '').lower()
    except Exception:
        return ''

words = re.split(r'\s+', query_clean or query)
artist_bits = [w.lower() for w in words[-2:]] if len(words) >= 4 else []
seen = []
candidates = []
# DDG often 403; one attempt only (DOM resolve in fish is preferred)
for q in [
    'site:open.spotify.com/track ' + (query_clean or query),
    (query_clean or query) + ' spotify track',
]:
    for tid in ddg_tracks(q):
        if tid in seen:
            continue
        seen.append(tid)
        candidates.append(tid)
    if candidates:
        break

if not candidates:
    for term in [query_clean or query, (query_clean or query) + ' soundtrack', query + ' soundtrack']:
        term = term.strip()
        if not term:
            continue
        for track, artist in itunes_songs(term):
            if not track:
                continue
            for q in (
                'site:open.spotify.com/track ' + track + ' ' + artist,
                track + ' ' + artist + ' spotify track',
                track + ' spotify',
            ):
                for tid in ddg_tracks(q):
                    if tid in seen:
                        continue
                    seen.append(tid)
                    candidates.append(tid)
                if candidates:
                    break
            if candidates:
                break
        if candidates:
            break

if not candidates:
    sys.exit(0)

best = candidates[0]
if artist_bits:
    for tid in candidates[:8]:
        title = track_title(tid)
        if all(bit in title for bit in artist_bits):
            best = tid
            break
        if any(bit in title for bit in artist_bits):
            best = tid
print(best)
" "$query" 2>/dev/null | tail -1)
    if string match -qr '^[a-zA-Z0-9]{10,}$' -- "$tid"
        echo $tid
        return 0
    end
    set tid (_spotify_resolve_track_id_dom "$query" 2>/dev/null)
    if test -n "$tid"
        echo $tid
    end
end

function _spotify_mpris_wait_play --description "Poll MPRIS (Brave or Spotify) and send play until Playing"
    set -l max 12
    test -n "$argv[1]"; and set max $argv[1]
    if not command -v playerctl &>/dev/null
        return 1
    end
    set -l attempt 0
    while test $attempt -lt $max
        sleep 1
        set attempt (math $attempt + 1)
        for p in (playerctl -l 2>/dev/null)
            if not string match -qr '^(brave|chrome|chromium|firefox|vivaldi|edge|opera|spotify)\.' -- $p
                continue
            end
            set -l page_url (playerctl --player=$p metadata xesam:url 2>/dev/null)
            set -l title (playerctl --player=$p metadata title 2>/dev/null)
            if string match -qr 'open\.spotify' "$page_url"; or string match -qr '(?i)spotify' "$title"
                playerctl --player=$p play 2>/dev/null
                sleep 0.8
                if test (playerctl --player=$p status 2>/dev/null) = Playing
                    return 0
                end
            end
        end
    end
    return 1
end

function _spotify_desktop_play --description "Play a track in Spotify desktop via spotify: URI and playerctl"
    set -l track_id $argv[1]

    if test -z "$track_id"
        return 1
    end

    if not command -v playerctl &>/dev/null
        if _arka_is_macos
            _spotify_start_desktop
            echo (set_color brblack)"  Opening in Spotify..."(set_color normal)
            _arka_open "spotify:track:$track_id"
            echo (set_color green)"✓ Opened in Spotify — press Play if needed."(set_color normal)
            return 0
        end
        echo (set_color yellow)"⚠ playerctl required for desktop playback."(set_color normal)
        echo (set_color brblack)"  Install: sudo apt install playerctl"(set_color normal)
        return 1
    end

    _spotify_start_desktop

    echo (set_color brblack)"  Opening in Spotify..."(set_color normal)
    _arka_open "spotify:track:$track_id"

    set -l played 0
    set -l attempt 0
    while test $attempt -lt 15
        sleep 1
        set attempt (math $attempt + 1)
        if playerctl --player=spotify status &>/dev/null
            playerctl --player=spotify play 2>/dev/null
            sleep 0.8
            if test (playerctl --player=spotify status 2>/dev/null) = Playing
                set played 1
                break
            end
        end
    end

    if test $played -eq 1
        set -l title (playerctl --player=spotify metadata title 2>/dev/null)
        set -l artist (playerctl --player=spotify metadata artist 2>/dev/null)
        echo (set_color green)"✓ Playback started: $title — $artist"(set_color normal)
        return 0
    end

    echo (set_color yellow)"⚠ Track opened in Spotify — press Play if needed (log in on first launch)."(set_color normal)
    return 1
end

function _spotify_desktop_search_play --description "Open track search in Spotify desktop and press play via playerctl"
    set -l query (_spotify_normalize_query $argv)
    test -z "$query"; and return 1
    if not _spotify_desktop_cmd &>/dev/null
        return 1
    end
    if not command -v playerctl &>/dev/null
        if _arka_is_macos
            _spotify_start_desktop
            set -l encoded (python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$query")
            echo (set_color brblack)"  Opening search in Spotify app..."(set_color normal)
            _arka_open "spotify:search:$encoded"
            echo (set_color green)"✓ Opened search in Spotify — press Play on the first result."(set_color normal)
            return 0
        end
        return 1
    end
    _spotify_start_desktop
    set -l encoded (python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$query")
    echo (set_color brblack)"  Opening search in Spotify app..."(set_color normal)
    _arka_open "spotify:search:$encoded"
    sleep 2
    playerctl --player=spotify play 2>/dev/null
    if test (playerctl --player=spotify status 2>/dev/null) = Playing
        return 0
    end
    return 1
end

function _spotify_browser_start_play --description "After xdg-open: MPRIS then xdotool (modular browser play)"
    set -l wait 12
    test -n "$argv[1]"; and set wait $argv[1]
    _spotify_mpris_wait_play $wait; and return 0
    _spotify_focus_and_play 2>/dev/null
    sleep 0.6
    _spotify_mpris_wait_play 3
end

function _spotify_fb_desktop_search --description "Spotify play-search step: desktop app"
    _spotify_desktop_cmd &>/dev/null; or return 1
    _spotify_desktop_search_play $argv[1]
end

function _spotify_fb_web_track --description "Spotify play-search step: resolve ID + xdg-open track"
    set -l query $argv[1]
    set -l track_id (_spotify_resolve_track_id "$query")
    test -n "$track_id"; or return 1
    echo (set_color green)"✓ Track: $track_id"(set_color normal)
    _spotify_web_play "" $track_id
end

function _spotify_fb_web_search --description "Spotify play-search step: xdg-open search URL + MPRIS"
    set -l query $argv[1]
    set -l encoded (python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$query")
    echo (set_color brblack)"  Opening search in default browser..."(set_color normal)
    _spotify_launch_url "https://open.spotify.com/search/$encoded/tracks"
    sleep 3
    _spotify_browser_start_play 10
end

function _spotify_fb_dom_search --description "Spotify play-search step: Playwright DOM"
    _spotify_dom_available; or return 1
    echo (set_color brblack)"  Trying DOM search-play..."(set_color normal)
    _spotify_prepare_brave_cdp
    _spotify_dom_control search-play $argv[1]
end

function _spotify_fb_dom_track --description "Spotify play-track step: Playwright DOM"
    _spotify_dom_available; or return 1
    echo (set_color brblack)"  xdg-open did not start playback — trying DOM (spotify_brave_debug)"(set_color normal)
    _spotify_dom_control play $argv[1]
end

function _spotify_play_track --description "Play resolved track: desktop → xdg-open → DOM"
    set -l track_id $argv[1]
    if _spotify_desktop_cmd &>/dev/null
        _spotify_desktop_play $track_id
        return $status
    end
    _spotify_web_play "" $track_id
    if test $status -eq 0
        return 0
    end
    _spotify_fb_dom_track $track_id
    return $status
end

function _spotify_launch_url --description "Open a Spotify/web URL in default browser or app (cross-platform)"
    _arka_open $argv[1]
end

function _spotify_find_browser_window --description "Return xdotool window id for an open Spotify web tab"
    if not command -v xdotool &>/dev/null
        return 1
    end
    for pattern in Spotify Embed "open.spotify.com" "embed/track"
        set -l wid (xdotool search --name "$pattern" 2>/dev/null | tail -1)
        if test -n "$wid"
            echo $wid
            return 0
        end
    end
    for cls in brave-browser Google-chrome Chromium firefox Navigator
        set -l wid (xdotool search --class $cls 2>/dev/null | tail -1)
        if test -n "$wid"
            echo $wid
            return 0
        end
    end
    return 1
end

function _spotify_focus_and_play --description "Focus Spotify tab and send play keystrokes"
    if not command -v xdotool &>/dev/null
        return 1
    end

    set -l wid (_spotify_find_browser_window 2>/dev/null)
    if test -z "$wid"
        return 1
    end

    xdotool windowactivate --sync $wid 2>/dev/null
    sleep 0.5

    # Click center of window so keystrokes hit the player, not the address bar
    set -l geom (xdotool getwindowgeometry --shell $wid 2>/dev/null)
    if test -n "$geom"
        set -l win_x 0; set -l win_y 0; set -l win_w 800; set -l win_h 600
        for line in $geom
            if string match -q 'X=*' -- $line
                set win_x (string replace X= '' $line)
            else if string match -q 'Y=*' -- $line
                set win_y (string replace Y= '' $line)
            else if string match -q 'WIDTH=*' -- $line
                set win_w (string replace WIDTH= '' $line)
            else if string match -q 'HEIGHT=*' -- $line
                set win_h (string replace HEIGHT= '' $line)
            end
        end
        set -l cx (math "($win_w / 2) + $win_x")
        set -l cy (math "($win_h / 2) + $win_y")
        xdotool mousemove --sync $cx $cy click 1 2>/dev/null
        sleep 0.3
    end

    # Space toggles play on Spotify web/embed; try twice in case first focuses only
    xdotool key --clearmodifiers space 2>/dev/null
    sleep 0.4
    xdotool key --clearmodifiers space 2>/dev/null
    return 0
end

function _spotify_mpris_player --description "playerctl name for Spotify desktop or browser tab"
    if command -v playerctl &>/dev/null
        if playerctl --player=spotify status &>/dev/null
            echo spotify
            return 0
        end
        for p in (playerctl -l 2>/dev/null)
            if string match -qr '^(brave|chrome|chromium|firefox|vivaldi|edge|opera)\.' -- $p
                set -l title (playerctl --player=$p metadata title 2>/dev/null)
                set -l url (playerctl --player=$p metadata xesam:url 2>/dev/null)
                if string match -qr '(?i)spotify' "$title"; or string match -qr 'open\.spotify' "$url"
                    echo $p
                    return 0
                end
            end
        end
    end
    return 1
end

function _spotify_web_play --description "xdg-open Spotify in default browser, then modular MPRIS/xdotool play"
    set -l url $argv[1]
    set -l track_id $argv[2]

    if test -n "$track_id"
        set url "https://open.spotify.com/track/$track_id"
    else if test -z "$url"
        return 1
    end

    echo (set_color brblack)"  Opening in default browser..."(set_color normal)
    _spotify_launch_url "$url"

    if _spotify_browser_start_play 12
        echo (set_color green)"✓ Playback started (browser)"(set_color normal)
        return 0
    end

    echo (set_color yellow)"⚠ Opened in browser — press Play or: spotify_control play"(set_color normal)
    return 1
end

function play_spotify --description "Play on Spotify (AppleScript macOS, playerctl Linux, Web API search)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_spotify.py) control toggle
        return $status
    end
    $py (_arka_py_script arka_spotify.py) play (string join " " $argv)
    return $status
end

function _spotify_play_search --description "Play search: desktop → web track → web search → DOM"
    set -l query (_spotify_normalize_query $argv)
    test -z "$query"; and return 1
    echo (set_color brblack)"  Resolving: '$query'..."(set_color normal)
    _fallback_try _spotify_fb_desktop_search _spotify_fb_web_track _spotify_fb_web_search _spotify_fb_dom_search -- $query
end

function _brave_profile_candidates --description "Brave user-data dirs: snap revisions + deb (internal)"
    set -l out
    if test -d "$HOME/snap/brave"
        set -l snap_cur "$HOME/snap/brave/current/.config/BraveSoftware/Brave-Browser"
        if test -d "$snap_cur"
            set -a out $snap_cur
        end
        for d in $HOME/snap/brave/*/
            if string match -qr '/snap/brave/\d+/$' -- "$d"
                set -l p (string trim -r -c / -- "$d")"/.config/BraveSoftware/Brave-Browser"
                if test -d "$p"
                    contains -- "$p" $out; or set -a out $p
                end
            end
        end
        set -l snap_common "$HOME/snap/brave/common/.config/BraveSoftware/Brave-Browser"
        if test -d "$snap_common"
            contains -- "$snap_common" $out; or set -a out $snap_common
        end
    end
    set -l deb "$HOME/.config/BraveSoftware/Brave-Browser"
    contains -- "$deb" $out; or set -a out $deb
    printf '%s\n' $out
end

function _brave_active_profile --description "Snap/deb profile dir with SingletonLock, if running"
    for p in (_brave_profile_candidates)
        # Snap: SingletonLock is a symlink; test -f fails if target does not resolve
        if test -e "$p/SingletonLock"; or test -L "$p/SingletonLock"
            echo "$p"
            return 0
        end
    end
    return 1
end

function _brave_is_running --description "True if snap or native Brave is running"
    _brave_active_profile >/dev/null; and return 0
    pgrep -f '/snap/brave/.*brave' >/dev/null 2>&1; and return 0
    pgrep -x brave >/dev/null 2>&1
end

function _spotify_prepare_brave_cdp --description "Point SPOTIFY_CDP_URL at running Brave if debug port is open"
    if test -n "$SPOTIFY_CDP_URL"
        return 0
    end
    for p in (_brave_profile_candidates)
        set -l port_file "$p/DevToolsActivePort"
        if test -f "$port_file"
            set -l port (head -1 "$port_file" | string trim)
            if string match -qr '^[0-9]+$' -- "$port"
                set -gx SPOTIFY_CDP_URL "http://127.0.0.1:$port"
                echo (set_color brblack)"  CDP from $port_file"(set_color normal)
                return 0
            end
        end
    end
    if curl -s --connect-timeout 1 http://127.0.0.1:9222/json/version >/dev/null 2>&1
        set -gx SPOTIFY_CDP_URL http://127.0.0.1:9222
    end
end

function spotify_brave_debug --description "Start Brave so play_spotify can reuse your open session"
    set -l brave (command -v brave 2>/dev/null; or command -v brave-browser 2>/dev/null)
    if test -z "$brave"
        echo (set_color red)"brave not found (install: snap install brave)"(set_color normal)
        return 1
    end
    set -l port 9222
    if test -n "$argv[1]"
        set port $argv[1]
    end
    if _brave_is_running
        set -l prof (_brave_active_profile)
        if test -f "$prof/DevToolsActivePort"
            set -l p (head -1 "$prof/DevToolsActivePort" | string trim)
            set -gx SPOTIFY_CDP_URL "http://127.0.0.1:$p"
            echo (set_color green)"Brave already has debug port $p — use play_spotify now"(set_color normal)
            echo (set_color brblack)"  Profile: $prof"(set_color normal)
            return 0
        end
        echo (set_color yellow)"Snap Brave is running but has no debug port."(set_color normal)
        echo "  Close all Brave windows, then run: spotify_brave_debug"
        echo (set_color brblack)"  Profile: $prof"(set_color normal)
        return 1
    end
    echo (set_color cyan)"Starting Brave ($brave) with remote debugging on port $port..."(set_color normal)
    echo (set_color brblack)"  Log into Spotify once, then: play_spotify <song>"(set_color normal)
    set -gx SPOTIFY_CDP_URL "http://127.0.0.1:$port"
    exec $brave --remote-debugging-port=$port $argv[2..-1]
end

function _spotify_dom_control --description "Control Spotify web player via Playwright DOM clicks"
    _spotify_prepare_brave_cdp
    set -l script "$HOME/.config/fish/spotify_dom.py"
    if not test -f "$script"
        echo (set_color red)"✗ spotify_dom.py not found at $script"(set_color normal)
        return 1
    end
    if not python3 -c "import playwright" 2>/dev/null
        echo (set_color yellow)"⚠ Playwright not installed. Run: install_skill_deps"(set_color normal)
        return 1
    end
    python3 "$script" $argv
end

function spotify_control --description "Control Spotify playback (AppleScript macOS, playerctl Linux)"
    set -l py (_arka_python)
    set -l action $argv[1]
    test -z "$action"; and set action status

    if test "$action" = dom
        set -l target $argv[2]
        if test -z "$target"
            _spotify_dom_control dom
        else if string match -qr '^[a-zA-Z0-9]{22}$' -- "$target"
            _spotify_dom_control dom "$target"
        else
            _spotify_dom_control dom "$target"
        end
        return $status
    end

    if test "$action" = play; and test (count $argv) -ge 2
        play_spotify $argv[2..-1]
        return $status
    end

    $py (_arka_py_script arka_spotify.py) control $action
    return $status
end

function weather --description "Get current weather or N-day forecast (Open-Meteo)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_chat.py) weather
        return $status
    end
    $py (_arka_py_script arka_chat.py) weather $argv
end

function timer --description "Countdown timer (e.g. timer 60 or timer 5m)"
    set -l input $argv[1]
    if test -z "$input"
        echo "Usage: timer <seconds>  or  timer 5m  or  timer 1h"
        return 1
    end

    # Parse time: support 30, 5m, 1h, 90s
    set -l seconds 0
    if string match -qr '^([0-9]+)h$' -- $input
        set seconds (math (string replace 'h' '' $input) \* 3600)
    else if string match -qr '^([0-9]+)m$' -- $input
        set seconds (math (string replace 'm' '' $input) \* 60)
    else if string match -qr '^([0-9]+)s?$' -- $input
        set seconds (string replace 's' '' $input)
    else
        echo (set_color red)"✗ Invalid format. Use: 30, 90s, 5m, 1h"(set_color normal)
        return 1
    end

    echo (set_color --bold cyan)"⏱ Timer: $seconds seconds"(set_color normal)
    if _agent_voice_enabled
        set -l mins (math "floor($seconds / 60)")
        set -l secs (math "$seconds % 60")
        if test $mins -gt 0
            speak_aloud "Timer set for $mins minutes." 2>/dev/null &
        else
            speak_aloud "Timer set for $secs seconds." 2>/dev/null &
        end
    end
    for i in (seq $seconds -1 1)
        set -l mins (math "floor($i / 60)")
        set -l secs (math "$i % 60")
        printf "\r  "(set_color --bold yellow)"⏱ %02d:%02d"(set_color normal) $mins $secs
        sleep 1
    end
    printf "\r"
    echo (set_color --bold green)"⏰ Time's up!                "(set_color normal)
    if _agent_voice_enabled
        speak_aloud "Time's up." 2>/dev/null
    end
    # Bell sound
    printf '\a'
end

function set_wallpaper --description "Set GNOME desktop wallpaper from an image file"
    set -l path "$argv[1]"
    if test -z "$path"
        echo "Usage: set_wallpaper <image-path>"
        echo "Example: set_wallpaper ~/Pictures/wallpapers/wallpaper_3.jpg"
        return 1
    end

    set path (eval echo $path)
    if command -v realpath &>/dev/null
        set path (realpath -e "$path" 2>/dev/null)
    else
        set path (readlink -f "$path" 2>/dev/null)
    end
    if test -z "$path"; or not test -f "$path"
        echo (set_color red)"✗ Image not found: $argv[1]"(set_color normal)
        return 1
    end

    set -l uri "file://$path"
    if not command -v gsettings &>/dev/null
        echo (set_color red)"✗ gsettings not found (GNOME settings)"(set_color normal)
        return 1
    end

    set -l err 0
    gsettings set org.gnome.desktop.background picture-uri "$uri" 2>/dev/null; or set err 1
    gsettings set org.gnome.desktop.background picture-uri-dark "$uri" 2>/dev/null; or set err 1
    gsettings set org.gnome.desktop.background picture-options zoom 2>/dev/null

    if test $err -eq 0
        echo (set_color --bold green)"✓ Wallpaper set: $path"(set_color normal)
        if command -v notify-send &>/dev/null
            notify-send "Wallpaper updated" (basename "$path") -i "$path" 2>/dev/null
        end
        return 0
    end

    echo (set_color yellow)"⚠ Could not update wallpaper (gsettings failed)"(set_color normal)
    echo (set_color brblack)"  URI: $uri"(set_color normal)
    return 1
end

function _screenshot_gnome --description "Screenshot via gnome-screenshot (internal fallback step)"
    command -v gnome-screenshot &>/dev/null; or return 1
    gnome-screenshot -f $argv[1] 2>/dev/null
end

function _screenshot_scrot --description "Screenshot via scrot (internal fallback step)"
    command -v scrot &>/dev/null; or return 1
    scrot $argv[1] 2>/dev/null
end

function _screenshot_import --description "Screenshot via ImageMagick import (internal fallback step)"
    command -v import &>/dev/null; or return 1
    import -window root $argv[1] 2>/dev/null
end

function _screenshot_maim --description "Screenshot via maim (internal fallback step)"
    command -v maim &>/dev/null; or return 1
    maim $argv[1] 2>/dev/null
end

function screenshot --description "Take a screenshot and save to Pictures"
    set -l timestamp (date +%Y%m%d_%H%M%S)
    set -l filename ~/Pictures/screenshot_$timestamp.png
    mkdir -p ~/Pictures

    if not _fallback_try _screenshot_gnome _screenshot_scrot _screenshot_import _screenshot_maim -- "$filename"
        echo (set_color red)"✗ No screenshot tool found. Install: sudo apt install gnome-screenshot"(set_color normal)
        return 1
    end

    if test -f "$filename"
        echo (set_color --bold green)"✓ Screenshot saved: $filename"(set_color normal)
    else
        echo (set_color red)"✗ Screenshot failed"(set_color normal)
        return 1
    end
end

function _arka_bytes_hr --description "Format byte count as human-readable (internal)"
    set -l b $argv[1]
    if test $b -ge 1099511627776
        printf "%.1fTiB" (math "$b / 1099511627776")
    else if test $b -ge 1073741824
        printf "%.1fGiB" (math "$b / 1073741824")
    else if test $b -ge 1048576
        printf "%.1fMiB" (math "$b / 1048576")
    else if test $b -ge 1024
        printf "%.1fKiB" (math "$b / 1024")
    else
        echo "$b B"
    end
end

function _arka_sys_os --description "OS name/version (macOS/Linux, internal)"
    if _arka_is_macos
        echo (sw_vers -productName) (sw_vers -productVersion)
    else
        lsb_release -ds 2>/dev/null; or grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"'
    end
end

function _arka_sys_cpu --description "CPU model string (macOS/Linux, internal)"
    if _arka_is_macos
        sysctl -n machdep.cpu.brand_string 2>/dev/null
    else
        grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | string trim
    end
end

function _arka_vm_pages --description "Parse vm_stat page count by label (macOS, internal)"
    set -l label $argv[1]
    for line in (vm_stat 2>/dev/null)
        if string match -q "*$label:*" -- "$line"
            string replace -r '.*:\s+' '' "$line" | string replace -r '\.$' ''
            return
        end
    end
end

function _arka_sys_ram --description "RAM used/total human-readable (macOS/Linux, internal)"
    if _arka_is_macos
        set -l page_size (sysctl -n hw.pagesize 2>/dev/null)
        set -l total (sysctl -n hw.memsize 2>/dev/null)
        set -l active (_arka_vm_pages "Pages active")
        set -l wired (_arka_vm_pages "Pages wired down")
        set -l compressed (_arka_vm_pages "Pages occupied by compressor")
        set -l used_bytes (math "($active + $wired + $compressed) * $page_size")
        echo (_arka_bytes_hr $used_bytes)"/"(_arka_bytes_hr $total)
    else
        free -h 2>/dev/null | awk '/Mem:/ {print $3 "/" $2}'
    end
end

function _arka_sys_ip --description "Primary local IP (macOS/Linux, internal)"
    if _arka_is_macos
        for iface in en0 en1 en2
            set -l ip (ipconfig getifaddr $iface 2>/dev/null)
            if test -n "$ip"
                echo $ip
                return
            end
        end
    else
        hostname -I 2>/dev/null | awk '{print $1}'
    end
end

function _arka_sys_gpu --description "GPU / graphics card summary (macOS/Linux, internal)"
    if _arka_is_macos
        set -l sp (system_profiler SPDisplaysDataType 2>/dev/null)
        set -l gpu_m (string match -r 'Chipset Model:\s+(.+?)\s+Type:' "$sp")
        set -l cores_m (string match -r 'Total Number of Cores:\s+(\d+)' "$sp")
        set -l metal_m (string match -r 'Metal Support:\s+(.+?)\s+Displays:' "$sp")
        set -l gpu ""
        set -l cores ""
        set -l metal ""
        if test (count $gpu_m) -ge 2
            set gpu (string trim -- $gpu_m[2])
        end
        if test (count $cores_m) -ge 2
            set cores $cores_m[2]
        end
        if test (count $metal_m) -ge 2
            set metal (string trim -- $metal_m[2])
        end
        if test -n "$gpu"
            if test -n "$cores"
                echo "$gpu ($cores cores, $metal)"
            else
                echo "$gpu"
            end
        end
    else
        if command -v nvidia-smi >/dev/null
            set -l nv (nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | string trim)
            if test -n "$nv"
                echo $nv
                return
            end
        end
        lspci 2>/dev/null | string match -r 'VGA|3D|Display' | head -1 | string replace -r '.*: ' ''
    end
end

function system_info --description "Show a quick system overview (optional: gpu cpu ram disk os ip kernel)"
    if test (count $argv) -ge 1
        set -l comp (string lower "$argv[1]")
        switch $comp
            case gpu graphics
                echo (set_color cyan)"  GPU:    "(set_color normal)(_arka_sys_gpu)
                return 0
            case cpu processor
                echo (set_color cyan)"  CPU:    "(set_color normal)(_arka_sys_cpu)
                return 0
            case ram memory
                echo (set_color cyan)"  RAM:    "(set_color normal)(_arka_sys_ram)
                return 0
            case disk storage
                echo (set_color cyan)"  Disk:   "(set_color normal)(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')
                return 0
            case os
                echo (set_color cyan)"  OS:     "(set_color normal)(_arka_sys_os)
                return 0
            case ip
                echo (set_color cyan)"  IP:     "(set_color normal)(_arka_sys_ip)
                return 0
            case kernel
                echo (set_color cyan)"  Kernel: "(set_color normal)(uname -r)
                return 0
        end
    end
    echo (set_color --bold blue)"━━━ System Info ━━━"(set_color normal)
    echo (set_color cyan)"  OS:     "(set_color normal)(_arka_sys_os)
    echo (set_color cyan)"  Kernel: "(set_color normal)(uname -r)
    echo (set_color cyan)"  Uptime: "(set_color normal)(uptime -p 2>/dev/null; or uptime)
    echo (set_color cyan)"  CPU:    "(set_color normal)(_arka_sys_cpu)
    echo (set_color cyan)"  GPU:    "(set_color normal)(_arka_sys_gpu)
    echo (set_color cyan)"  RAM:    "(set_color normal)(_arka_sys_ram)
    echo (set_color cyan)"  Disk:   "(set_color normal)(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')
    echo (set_color cyan)"  IP:     "(set_color normal)(_arka_sys_ip)
end

function search_web --description "Open a web search in the browser"
    set -l query (string join "+" $argv)
    if test -z "$query"
        echo "Usage: search_web <query>"
        return 1
    end
    _arka_open "https://www.google.com/search?q=$query" 2>/dev/null
    echo (set_color --bold green)"🔍 Searching: $argv"(set_color normal)
end

function _agent_is_usage_question --description "True if user asks about their app/screen time (internal)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)(screen\s*time|app\s*usage|usage\s*stats|time\s*spent|which\s+apps|what\s+apps|apps\s+i\s+(used|use)|how\s+long\s+(did\s+i|have\s+i|was\s+i)\s+(use|on|spent)|how\s+much\s+time\s+(on|in|using)|time\s+on\s+\w+|most\s+used\s+app|website\s*time|web\s*sites|sites\s+i\s+(visited|used|browse)|which\s+sites|browsing\s*time|time\s+on\s+(youtube|reddit|github|twitter|facebook))' "$clean"
        return 0
    end
    return 1
end

function _agent_is_platform_howto_question --description "True for local OS/app UI how-to (close tab, shortcuts) (internal)"
    set -l py (_arka_python)
    $py -c "
from arka.routing.platform_howto import is_platform_howto_question
import sys
sys.exit(0 if is_platform_howto_question(sys.argv[1]) else 1)
" (string escape --style=script -- $argv[1])
end

function _agent_parse_usage_period --description "Parse today/week from usage question (internal)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)(yesterday|last\s+night)' "$clean"
        echo yesterday
    else if string match -qr '(?i)(week|7\s*days|past\s+week|this\s+week)' "$clean"
        echo week
    else
        echo today
    end
end

function app_usage --description "Show which apps you used and for how long"
    set -l py (_arka_python)
    set -l period today
    if test (count $argv) -ge 1
        switch $argv[1]
            case today day
                set period today
            case week 7d
                set period week
            case yesterday
                set period yesterday
            case start
                $py (_arka_py_script arka_usage.py) start
                return $status
            case stop
                $py (_arka_py_script arka_usage.py) stop
                return $status
            case '*'
                set period $argv[1]
        end
    end
    set -l out ($py (_arka_py_script arka_usage.py) report $period 2>&1)
    if test $status -ne 0
        echo (set_color red)"$out"(set_color normal)
        return 1
    end
    printf '%s%s%s\n' (set_color --bold green) "━━━ Answer ━━━" (set_color normal)
    printf '%s\n' "$out"
end

function _agent_usage_start --description "Start app + website usage tracker (internal)"
    if set -q USAGE_TRACK
        test "$USAGE_TRACK" = 0 -o "$USAGE_TRACK" = false; and return 0
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_usage.py) start 2>/dev/null
end

function _agent_usage_stop --description "Stop app usage tracker (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_usage.py) stop 2>/dev/null
end

function open_urls --description "Open one or more URLs in the browser"
    if test (count $argv) -eq 0
        echo "Usage: open_urls <url1> [url2] [url3] ..."
        return 1
    end

    set -l opened 0
    for url in $argv
        # Add https:// if no protocol specified
        if not string match -qr '^https?://' -- "$url"
            set url "https://$url"
        end
        _arka_open "$url" 2>/dev/null
        set opened (math $opened + 1)
        echo (set_color --bold green)"  ▶ Opened: $url"(set_color normal)
        # Small delay so the browser doesn't choke on rapid opens
        if test $opened -lt (count $argv)
            sleep 0.3
        end
    end
    echo (set_color --bold cyan)"🌐 Opened $opened site(s)"(set_color normal)
end

function _parse_whatsapp_nl --description "Parse natural-language WhatsApp send (target, message) (internal)"
    set -l cmd (string trim -- $argv[1])
    set -l rest ""

    set -l m (string match -r '(?i)^send\s+(?:an?\s+)?(?:a\s+)?(?:whatsapp\s+)?(?:message\s+)?to\s+(.+)$' -- "$cmd")
    if test (count $m) -ge 2
        set rest (string trim -- $m[2])
    else
        set m (string match -r '(?i)^(?:send\s+)?(?:a\s+)?whatsapp(?:\s+message)?\s+to\s+(.+)$' -- "$cmd")
        if test (count $m) -ge 2
            set rest (string trim -- $m[2])
        end
    end

    if test -z "$rest"
        echo ""
        echo ""
        return 1
    end

    set -l target ""
    set -l msg ""

    if string match -q '*:*' -- "$rest"
        set -l parts (string split -m 1 ":" "$rest")
        set target (string trim -- $parts[1])
        set msg (string trim -- $parts[2])
    else
        set -l pm (string match -r '^(\+?[0-9][0-9\s-]{6,}[0-9])\s+(.+)$' -- "$rest")
        if test (count $pm) -ge 3
            set target (string replace -r '\s' '' -- $pm[2])
            set msg (string trim -- $pm[3])
        else
            set -l words (string split " " -- "$rest")
            if test (count $words) -ge 2
                set msg $words[-1]
                set target (string join " " $words[1..-2])
            else
                set target $rest
            end
        end
    end

    echo $target
    echo $msg
end

function _arka_whatsapp_dir --description "Bundled WhatsApp automation directory (internal)"
    if test -n "$WHATSAPP_DIR"; and test -d "$WHATSAPP_DIR"
        echo "$WHATSAPP_DIR"
        return
    end
    if test -d "$_ARKA_ROOT/whatsapp"
        echo "$_ARKA_ROOT/whatsapp"
        return
    end
    if test -d "$HOME/Projects/python/products/automation"
        echo "$HOME/Projects/python/products/automation"
        return
    end
    echo "$_ARKA_ROOT/whatsapp"
end

function _send_whatsapp_browser --description "Send via WhatsApp Web with fuzzy contact search (internal)"
    set -l target $argv[1]
    set -l message $argv[2]
    echo (set_color cyan)"▶ WhatsApp Web: fuzzy search for '$target'..."(set_color normal)
    browse_web "Go to https://web.whatsapp.com/ and wait until the page is fully loaded. Click the chat search or 'Search name or number' field. Type '$target' (partial name is OK). Wait 2 seconds for results. Click the best matching contact from the list (fuzzy match). Click the message input. Type this message exactly: $message. Press Enter to send."
end

function send_whatsapp --description "Send WhatsApp via bundled automation or browser fallback"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_whatsapp_inbox.py)

    if test (count $argv) -eq 1; and string match -qr '(?i)whatsapp|message.*to' -- "$argv[1]"
        set -l parsed (_parse_whatsapp_nl "$argv[1]")
        if test (count $parsed) -lt 2; or test -z "$parsed[1]"
            echo "Usage: send_whatsapp <name_or_number> <message>"
            return 1
        end
        set argv $parsed[1] $parsed[2]
    end

    if test (count $argv) -lt 2
        echo "Usage: send_whatsapp <name_or_number> <message>"
        echo "Example: send_whatsapp +919876543210 hi"
        echo "Example: send_whatsapp Mom Hello!"
        echo "Inbox listener: arka whatsapp inbox  |  whatsapp_listen status"
        return 1
    end

    set -l target (string trim -c "'\"" $argv[1])
    set -l message (string join " " $argv[2..-1])
    $py "$script" send "$target" "$message"
    return $status
end

function whatsapp_listen --description "Watch WhatsApp inbox → Arka (native desktop on macOS, Web elsewhere)"
    set -l script (_arka_py_script arka_whatsapp_inbox.py)
    set -l py (_arka_python)
    if not test -f "$script"
        echo (set_color red)"Missing $script"(set_color normal)
        return 1
    end
    if test (count $argv) -ge 1
        switch $argv[1]
            case status
                $py "$script" status
                return $status
            case stop
                $py "$script" stop
                return $status
            case fg foreground
                $py "$script" listen
                return $status
            case log
                tail -30 ~/.cache/fish-agent/whatsapp_debug.log 2>/dev/null; or echo "No debug log yet"
                return $status
            case debug
                if test -f ~/.cache/fish-agent/whatsapp_debug.log
                    tail -f ~/.cache/fish-agent/whatsapp_debug.log
                else
                    echo "No debug log yet. Run: whatsapp_listen fg"
                end
                return $status
        end
    end
    set -l pidfile ~/.cache/fish-agent/arka_whatsapp.pid
    set -l logfile ~/.cache/fish-agent/arka_whatsapp.log
    if test -f "$pidfile"
        set -l pid (cat "$pidfile" 2>/dev/null)
        if test -n "$pid"; and kill -0 "$pid" 2>/dev/null
            echo (set_color green)"WhatsApp inbox listener already running (pid $pid)"(set_color normal)
            echo "  log: $logfile  |  debug: ~/.cache/fish-agent/whatsapp_debug.log  |  stop: whatsapp_listen stop"
            return 0
        end
    end
    mkdir -p ~/.cache/fish-agent
    set -l from "(set WHATSAPP_FROM in .env)"
    if set -q WHATSAPP_FROM
        set from $WHATSAPP_FROM
    end
    echo (set_color cyan)"Starting WhatsApp inbox → Arka for $from (Selenium)..."(set_color normal)
    echo (set_color brblack)"Keep WhatsApp Web logged in. Log: $logfile"(set_color normal)
    nohup $py "$script" listen >>"$logfile" 2>&1 &
    disown
    sleep 2
    $py "$script" status
end

# --- Automation / AIE (bundled scripts + optional AIE_DIR override) ---

function _arka_aie_dir --description "Directory containing AIE Python scripts (internal)"
    if test -n "$AIE_DIR"; and test -d "$AIE_DIR"
        echo "$AIE_DIR"
        return
    end
    if test -d "$_ARKA_ROOT/aie"
        echo "$_ARKA_ROOT/aie"
        return
    end
    if test -d "$HOME/Projects/python/products/automation"
        echo "$HOME/Projects/python/products/automation"
        return
    end
    echo "$_ARKA_ROOT/aie"
end

function _arka_aie_run --description "Run an AIE script by filename (internal)"
    set -l script (_arka_aie_dir)/$argv[1]
    set -l py (_arka_python)
    if not test -f "$script"
        echo (set_color red)"AIE script not found: $script"(set_color normal)
        return 1
    end
    $py "$script" $argv[2..-1]
end

function auto_click --description "Monitor cursor shape changes and auto-click when cursor changes (e.g. loading spinner)"
    echo (set_color cyan)"▶ Starting auto-click monitor (Ctrl+C to stop)..."(set_color normal)
    _arka_aie_run auto_click.py
end

function auto_copy --description "Auto-copy text selections to clipboard on paste (Linux X11/Wayland)"
    echo (set_color cyan)"▶ Starting auto-copy selection monitor (Ctrl+C to stop)..."(set_color normal)
    _arka_aie_run auto_copy_selection.py
end

function decrypt_pdf --description "Decrypt password-protected PDF files"
    if test (count $argv) -lt 2
        echo "Usage: decrypt_pdf <pdf_or_directory> <password> [output_path]"
        echo "Tip: pdf_tools unlock <file.pdf> --password <pw>  (same backend)"
        return 1
    end
    set -l py (_arka_python)
    if test (count $argv) -ge 3
        $py (_arka_py_script arka_pdf_tools.py) unlock $argv[1] --password $argv[2] -o $argv[3]
    else
        $py (_arka_py_script arka_pdf_tools.py) unlock $argv[1] --password $argv[2]
    end
end

function files_preference_help --description "Explain where Arka saves images and how to change the folder"
    set -l gen_dir ~/Pictures/arka-generated
    if test -n "$IMAGE_OUTPUT_DIR"
        set gen_dir (string replace -a '~' "$HOME" -- "$IMAGE_OUTPUT_DIR")
    end
    set -l env_path "$_ARKA_CFG/.env"

    set -l body "Arka does not save generated images to your Desktop by default.

Where things go:
  • generate_image  →  $gen_dir
  • screenshot      →  ~/Pictures/screenshot_<timestamp>.png

To use a different folder for generated images, add this to $env_path:
  IMAGE_OUTPUT_DIR=$HOME/Pictures/arka-generated

Then run: arka reload

If images on your Desktop came from other apps or manual saves, move them to ~/Pictures (or any folder you prefer). For new files landing in Downloads, run: classify_files

Say \"organize my downloads\" or \"clean up desktop images\" if you want help sorting."
    _arka_ui_header "Image save locations" chat
    echo ""
    _arka_print_answer "$body"
end

function classify_files --description "Auto-classify files in Downloads by extension (images, docs, code, etc.)"
    echo (set_color cyan)"▶ Starting file classifier (Ctrl+C to stop)..."(set_color normal)
    _arka_aie_run classifier.py
end

function cleanup_downloads --description "Clean up installer/archive clutter from Downloads"
    echo (set_color cyan)"▶ Cleaning up installer files from Downloads..."(set_color normal)
    _arka_aie_run delete_useless.py
end

function watch_zip --description "Watch a folder for new .zip files and auto-extract them"
    echo (set_color cyan)"▶ Starting zip watcher (Ctrl+C to stop)..."(set_color normal)
    _arka_aie_run zip_open.py
end

function internet_enhance --description "Artificial Internet Enhancements (AIE): automate desktop/internet helpers"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_aie.py) status
        return $status
    end
    switch $argv[1]
        case help -h --help
            echo "Usage: internet_enhance [status|start|stop|stop-all|cleanup|list] [target]"
            echo "Alias: aie"
            echo ""
            echo "  status              Show running enhancers (default)"
            echo "  start [all|name]    Start background helpers (zip, classify on all platforms)"
            echo "  stop [all|name]     Stop background helpers (default: all)"
            echo "  stop-all            Stop every running AIE enhancer"
            echo "  cleanup             Remove installer junk from Downloads"
            echo "  list                List enhancer ids"
            echo ""
            echo "Examples:"
            echo "  internet_enhance start all"
            echo "  aie start zip classify"
            echo "  aie stop all"
            echo "  aie stop-all"
            return 0
        case status start stop cleanup list
            $py (_arka_py_script arka_aie.py) $argv
            return $status
        case stop-all stop_all
            $py (_arka_py_script arka_aie.py) stop-all
            return $status
        case '*'
            echo (set_color red)"Unknown subcommand: $argv[1]"(set_color normal)
            internet_enhance help
            return 1
    end
end

function aie --description "Alias for internet_enhance (Artificial Internet Enhancements)"
    internet_enhance $argv
end

function youtube_bulk --description "Bulk download YouTube playlists/channels (yt-dlp + web UI)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_youtube_bulk.py) status
        return $status
    end
    switch $argv[1]
        case help -h --help
            echo "Usage: youtube_bulk [status|start|stop|open|download|library|logs] …"
            echo "Alias: yt_bulk"
            echo ""
            echo "  status                    Server + download progress (default)"
            echo "  start | stop | open       Manage web UI at http://localhost:5000"
            echo "  download <url> [opts]     Bulk download playlist or channel"
            echo "  library                   List downloaded folders/files"
            echo ""
            echo "Download options:"
            echo "  --channel                 Channel URL or @handle"
            echo "  --audio                   MP3 instead of video"
            echo "  --quality 1080|720|480"
            echo "  --limit N                 First N items (or use --start/--end/--range)"
            echo "  --start N                 First playlist index (1-based, inclusive)"
            echo "  --end N                   Last playlist index (1-based, inclusive)"
            echo "  --range A-B               Playlist slice, e.g. 6-9"
            echo "  --wait                    Block until finished"
            echo ""
            echo "Examples:"
            echo "  youtube_bulk download 'https://youtube.com/playlist?list=PLxxx' --wait"
            echo "  youtube_bulk download PLxxx --range 6-9 --wait"
            echo "  yt_bulk download @mkbhd --channel --limit 5 --audio"
            echo "  youtube_bulk open"
            return 0
        case status start stop open download library logs
            $py (_arka_py_script arka_youtube_bulk.py) $argv
            return $status
        case '*'
            echo (set_color red)"Unknown subcommand: $argv[1]"(set_color normal)
            youtube_bulk help
            return 1
    end
end

function yt_bulk --description "Alias for youtube_bulk"
    youtube_bulk $argv
end

function youtube_download --description "Download a single YouTube video or shorts link (yt-dlp)"
    if test (count $argv) -lt 1
        echo "Usage: youtube_download <url|video-id> [--audio] [--quality 1080|720|480|best] [-o dir]"
        echo "Alias: yt_download"
        echo "Example: youtube_download 'https://youtube.com/watch?v=dQw4w9WgXcQ'"
        echo "Example: youtube_download youtu.be/abc123 --audio"
        echo "Saves to ~/Videos/YoutubeDownloads/Singles/ by default"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_youtube.py) download $argv
end

function yt_download --description "Alias for youtube_download"
    youtube_download $argv
end

function _arka_parse_media_file_from_args --description "Extract media file path from arg list (internal)"
    set -l rest $argv
    set -l joined (string join " " $rest)
    set -l ext '(?:mp3|mp4|m4a|wav|ogg|opus|webm|mkv|mov|aac|flac)'
    set -l qm (string match -r "(?i)['\"]([^'\"]+\\.$ext)['\"]" "$joined")
    if test (count $qm) -ge 2
        echo $qm[2]
        return
    end
    set -l abs (string match -r -a "(?i)(/[^\n\"]+\\.$ext)" "$joined")
    if test (count $abs) -ge 1
        echo $abs[-1]
        return
    end
    for a in $rest
        if string match -qr '^-' "$a"
            continue
        end
        set -l p (string replace -r '^~' "$HOME" -- $a)
        if test -f "$p"; and string match -qr '(?i)\.(mp3|mp4|m4a|wav|ogg|opus|webm|mkv|mov|aac|flac)$' "$p"
            echo "$p"
            return
        end
    end
end

function _arka_try_summarize_youtube --description "Route YouTube URL/id in summarize args to transcript or playlist digest"
    set -l custom_q ""
    set -l limit ""
    set -l rest
    set -l i 1
    while test $i -le (count $argv)
        switch $argv[$i]
            case -q --question --focus
                if test $i -lt (count $argv)
                    set custom_q $argv[(math $i + 1)]
                    set i (math $i + 2)
                    continue
                end
            case '-q=*' '--question=*' '--focus=*'
                set custom_q (string split -m 1 = -- $argv[$i])[2]
                set i (math $i + 1)
                continue
            case --limit -n
                if test $i -lt (count $argv)
                    set limit $argv[(math $i + 1)]
                    set i (math $i + 2)
                    continue
                end
            case '--limit=*'
                set limit (string split -m 1 = -- $argv[$i])[2]
                set i (math $i + 1)
                continue
        end
        set -a rest $argv[$i]
        set i (math $i + 1)
    end
    set -l target ""
    for a in $rest
        if string match -qr '(?i)(^https?://.*(youtube\.com|youtu\.be)|^PL[\w-]+$|^[\w-]{11}$)' "$a"
            set target "$a"
            break
        end
    end
    if test -z "$target"
        return 1
    end
    set -l url "$target"
    if string match -qr '^PL[\w-]+$' "$target"
        set url "https://www.youtube.com/playlist?list=$target"
    else if string match -qr '^[\w-]{11}$' "$target"
        set url "https://www.youtube.com/watch?v=$target"
    end
    if string match -qr '(?i)playlist\?list=|/playlist' "$url"
        set -l pl_args --url $url
        if test -n "$limit"
            set -a pl_args --limit $limit
        end
        if test -n "$custom_q"
            set -a pl_args -q "$custom_q"
        end
        playlist_summarize $pl_args
        return $status
    end
    if string match -qr '(?i)youtube\.com|youtu\.be' "$url"
        _arka_youtube_tools_ready; or return 1
        set -l yt_args --summarize
        if test -n "$custom_q"
            set -a yt_args -q "$custom_q"
        end
        set -a yt_args "$target"
        youtube_transcript $yt_args
        return $status
    end
    return 1
end

function _arka_parse_summary_focus --description "User summary instructions from NL args (internal)"
    set -l joined (string join " " $argv)
    set -l file "$argv[-1]"
    set -l focus $joined
    if test -n "$file"
        set focus (string replace "$file" '' "$focus")
    end
    set focus (string replace -r -i '^(?:for\s+)?(?:please\s+)?(?:summarize|summary|tldr|overview|brief)\s*' '' "$focus")
    set focus (string replace -r -i '^\s*for\s+' '' "$focus")
    set focus (string trim -- "$focus")
    set -l wc (string match -r '(?i)(\d+)\s*words?' "$focus")
    if test (count $wc) -ge 2
        set focus (string replace -r -i '(?i)\d+\s*words?\s*' '' "$focus" | string trim)
    end
    set focus (string replace -r -i '^(?:about|on|regarding|covering|focus(?:ing)?\s+on)\s+' '' "$focus")
    set focus (string trim -- "$focus")
    if test (count $wc) -ge 2
        if test -n "$focus"
            echo "Keep it to about $wc[2] words. $focus"
        else
            echo "Summarize in about $wc[2] words. Cover the main plot and key events."
        end
        return
    end
    if test -n "$focus"
        echo "$focus"
        return
    end
    echo "Summarize the entire video from start to finish — all major plot beats and the ending — in a short, concise way."
end

function _arka_summarize_media --description "Transcribe + summarize a local media file (internal)"
    if _arka_try_summarize_youtube $argv
        return $status
    end
    set -l custom_q ""
    set -l rest
    set -l i 1
    while test $i -le (count $argv)
        switch $argv[$i]
            case -q --question --focus
                if test $i -lt (count $argv)
                    set custom_q $argv[(math $i + 1)]
                    set i (math $i + 2)
                    continue
                end
            case '-q=*' '--question=*' '--focus=*'
                set custom_q (string split -m 1 = -- $argv[$i])[2]
                set i (math $i + 1)
                continue
            case -u --youtube-url
                if test $i -lt (count $argv)
                    set -g _arka_sum_yt_url $argv[(math $i + 1)]
                    set i (math $i + 2)
                    continue
                end
            case '-u=*' '--youtube-url=*'
                set -g _arka_sum_yt_url (string split -m 1 = -- $argv[$i])[2]
                set i (math $i + 1)
                continue
        end
        set -a rest $argv[$i]
        set i (math $i + 1)
    end
    set -l file (_arka_parse_media_file_from_args $rest)
    if test -z "$file"; or not test -f "$file"
        echo "Usage: arka summarize [instructions] [for N words] <file>"
        echo "       arka summarize -q \"what happens to the princess?\" video.mp4"
        echo "       arka summarize <youtube-url|video-id|PLid> [--limit N]"
        echo ""
        echo "Examples:"
        echo "  arka summarize for 100 words ~/Videos/lecture.mp4"
        echo "  arka summarize focus on the villain's plan in 150 words \"/path/with spaces/video.mp4\""
        echo "  arka summarize \"/path/video.mp4\"   # default: entire video, short & concise"
        echo "  arka summarize -q \"list the main characters and their roles\" podcast.mp3"
        echo "  arka summarize 'https://youtube.com/watch?v=abc123'"
        echo "  arka summarize youtube PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige --limit 5"
        echo ""
        echo "Tell the agent what you want: length, focus, questions, bullet format, etc."
        return 1
    end
    set -l q $custom_q
    if test -z "$q"
        set q (_arka_parse_summary_focus $rest "$file")
    end
    set -l py (_arka_python)
    set -l yt_args
    if set -q _arka_sum_yt_url; and test -n "$_arka_sum_yt_url"
        set yt_args -u "$_arka_sum_yt_url"
        set -e _arka_sum_yt_url
    end
    $py (_arka_py_script arka_media.py) summarize "$file" -q "$q" --save $yt_args
end

function monitor_x --description "Monitor a Twitter/X profile for new tweets and notify"
    if test (count $argv) -lt 1
        echo "Usage: monitor_x <twitter_handle>"
        echo "Example: monitor_x elonmusk"
        return 1
    end
    set -l automation_py /home/s/Projects/python/products/automation/.venv/bin/python3
    if not test -x "$automation_py"
        echo (set_color red)"Automation venv not found at $automation_py"(set_color normal)
        return 1
    end
    $automation_py -c "
import sys
sys.path.insert(0, '/home/s/Projects/python/products/automation')
from x_notify import start_monitor
start_monitor('$argv[1]')
"
end

function generate_image --description "Generate images via Google Nano Banana (Gemini API) or Pollinations"
    set -l prompt_parts
    set -l flags
    set -l i 1
    set -l argc (count $argv)
    while test $i -le $argc
        switch $argv[$i]
            case -o --output -a --aspect -m --model
                set -a flags $argv[$i]
                set i (math $i + 1)
                if test $i -le $argc
                    set -a flags $argv[$i]
                end
            case '-*'
                set -a flags $argv[$i]
            case '*'
                set -a prompt_parts $argv[$i]
        end
        set i (math $i + 1)
    end
    if test (count $prompt_parts) -eq 0
        echo "Usage: generate_image <prompt> [-o/--output <path>] [-a/--aspect <ratio>]"
        echo "Example: generate_image 'a futuristic city at sunset'"
        echo "Example: generate_image 'a cute kitten' -o cat.png -a 16:9"
        echo ""
        echo "Nano Banana = Google Gemini image models (same as AI Studio API, not the website UI)."
        echo "  GEMINI_API_KEY  → gemini-3.1-flash-image, gemini-2.5-flash-image, …"
        echo "  POLLINATIONS_API_KEY → nanobanana model (Google via Pollinations proxy)"
        echo "  IMAGE_BACKEND=auto|nano-banana|pollinations"
        echo "  IMAGE_OUTPUT_DIR=~/Pictures/arka-generated  (default save folder)"
        return 1
    end
    set -l prompt (string join ' ' -- $prompt_parts)
    set -l py (_arka_python)
    $py (_arka_py_script arka_generate_image.py) $flags -- "$prompt"
end

function generate_thumbnail --description "YouTube thumbnail — Unsplash photo + title overlay"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: generate_thumbnail generate --topic 'ai' [--title 'What is AI?'] [-o out.png]"
        echo "       generate_thumbnail check"
        echo ""
        echo "NL: arka generate thumbnail for ai video"
        echo ""
        echo "Requires: UNSPLASH_ACCESS_KEY + Pillow"
        return 1
    end
    $py (_arka_py_script arka_generate_thumbnail.py) $argv
end

function chart --description "Draw line, bar, pie, scatter, histogram, or pareto charts (matplotlib → PNG)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: chart line TICKER [TICKER...] [--range 3mo]"
        echo "       chart bar --data 'Apple:230,Samsung:210' [--title 'Phone sales']"
        echo "       chart pie --data 'Organic:400,Direct:300' [--title 'Traffic sources']"
        echo "       chart scatter --data '100:200,120:190' [--xlabel Spend --ylabel Revenue]"
        echo "       chart histogram --data '12,15,18,22,25' [--title 'Response times']"
        echo "       chart pareto --data 'Scratches:45,Dents:28' [--title 'Defect causes']"
        echo ""
        echo "NL: arka chart TSLA and NVDA last 3 months"
        echo "    arka pie chart market share Apple 40 Samsung 30"
        echo "    arka scatter ad spend vs revenue 100 200 120 190 170 280"
        echo "    arka histogram response times 12 15 18 22 25 28 30"
        echo "    arka pareto defects Scratches:45 Dents:28 Cracks:15"
        echo ""
        echo "Requires: pip install matplotlib"
        echo "  Saves to ~/Pictures/arka-generated/ (or CHART_OUTPUT_DIR / IMAGE_OUTPUT_DIR)"
        return 1
    end
    $py (_arka_py_script arka_chart.py) $argv
    return $status
end

function ascii_art --description "Render text or images as ASCII art (figlet / pyfiglet)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: ascii_art <text> [--font standard] [-o path.txt]"
        echo "       ascii_art --from-image photo.jpg [--width 80]"
        echo ""
        echo "NL: arka make ascii art of HELLO"
        echo "    arka ascii banner welcome"
        echo "    arka ascii art from logo.png"
        echo ""
        echo "Optional: pip install pyfiglet  |  brew install figlet"
        return 1
    end
    $py (_arka_py_script arka_ascii_art.py) $argv
    return $status
end

function drawing_ask --description "Vision analysis for blueprints, drawings, scanned specs (Gemini)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: drawing_ask ask <file.pdf|image> <question>"
        echo "       drawing_ask <file> <question>   # shorthand"
        echo ""
        echo "Examples:"
        echo "  drawing_ask plan.pdf extract door schedule and room dimensions"
        echo "  drawing_ask --pages 1-3 specs.pdf summarize payment terms"
        echo "  drawing_ask floor-plan.png list all room names and areas"
        echo ""
        echo "NL: arka analyze blueprint.pdf extract grid lines and dimensions"
        echo "    arka review scanned contract.pdf payment terms and parties"
        echo ""
        echo "Requires: GEMINI_API_KEY + pip install Pillow pymupdf"
        echo "  PDF pages: --pages 1,3,5 or 1-4 (default first 8 pages)"
        return 1
    end
    $py (_arka_py_script arka_drawing.py) $argv
    return $status
end

function describe_image --description "Describe a photo/image via local vLLM vision model"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: describe_image <path|url> [question]"
        echo ""
        echo "Examples:"
        echo "  describe_image photo.jpg"
        echo "  describe_image https://example.com/cat.png what breed is this"
        echo "  describe_image ~/Pictures/screenshot.png describe visible text"
        echo ""
        echo "NL: arka describe photo.jpg"
        echo "    arka what's in ~/Downloads/image.png"
        echo ""
        echo "Requires: pip install Pillow; OCR: brew install tesseract"
        echo "Charts: .json sidecar + structured visual (exact colors, no LLM guess)"
        echo "  Auto-starts vLLM when needed, stops when done (LLM_AUTO_START/STOP_SERVERS)"
        return 1
    end
    $py (_arka_py_script arka_describe_image.py) $argv
    return $status
end

function describe_screen --description "10s countdown, capture display, describe via vision"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_screen.py) capture
        return $status
    end
    switch $argv[1]
        case help -h --help
            echo "Usage: describe_screen [question]"
            echo ""
            echo "Examples:"
            echo "  describe_screen"
            echo "  describe_screen what app is in focus"
            echo ""
            echo "NL: arka what is on my screen"
            echo "    arka screen"
            echo "    arka describe screen"
            echo ""
            echo "Shows a 10-second countdown, captures the display, then describes it."
            return 0
        case capture
            $py (_arka_py_script arka_screen.py) $argv
            return $status
        case '*'
            $py (_arka_py_script arka_screen.py) capture $argv
            return $status
    end
end

function generate_video --description "Generate real AI video (Pollinations or Gemini Veo — no fake slideshows)"
    set -l prompt_parts
    set -l flags
    set -l i 1
    set -l argc (count $argv)
    while test $i -le $argc
        switch $argv[$i]
            case -o --output -a --aspect -d --duration -m --model
                set -a flags $argv[$i]
                set i (math $i + 1)
                if test $i -le $argc
                    set -a flags $argv[$i]
                end
            case --no-audio
                set -a flags $argv[$i]
            case '-*'
                set -a flags $argv[$i]
            case '*'
                set -a prompt_parts $argv[$i]
        end
        set i (math $i + 1)
    end
    if test (count $prompt_parts) -eq 0
        echo "Usage: generate_video <prompt> [-o/--output <path>] [-a/--aspect 16:9|9:16|1:1] [-d/--duration 5]"
        echo "Example: generate_video 'a queen walking in a garden'"
        echo ""
        echo "Requires real AI video API (no photo slideshows):"
        echo "  POLLINATIONS_API_KEY=pk_...  → free at https://enter.pollinations.ai/"
        echo "  or Gemini Veo with GCP billing on GEMINI_API_KEY"
        echo ""
        echo "For still images: generate_image 'a queen'"
        return 1
    end
    set -l prompt (string join ' ' -- $prompt_parts)
    set -l py (_arka_python)
    $py (_arka_py_script arka_generate_video.py) $flags -- "$prompt"
end

function compose_video --description "Compose YouTube/info videos — Unsplash images, ffmpeg, edge-tts narration"
    if test (count $argv) -eq 0
        echo "Usage: compose_video compose --topic 'Python asyncio' [--llm]"
        echo "       compose_video compose --script scenes.json [-o out.mp4]"
        echo "       compose_video check"
        echo ""
        echo "NL: arka make youtube video about Rust memory safety"
        echo "    arka compose video on Kubernetes with llm"
        echo ""
        echo "Requires: ffmpeg, Pillow, UNSPLASH_ACCESS_KEY, edge-tts (optional TTS)"
        echo "Fonts: VIDEO_FONT / VIDEO_FONT_PATH in ~/.config/arka/.env"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_compose_video.py) $argv
end

function compose_slides --description "Compose presentation slide decks — stock photos, charts, LLM scripts"
    if test (count $argv) -eq 0
        echo "Usage: compose_slides compose --topic 'Python asyncio' [--llm] [-f pptx|pdf|html|md|json|all]"
        echo "       compose_slides compose --script scenes.json [-o out.pptx] [-f format]"
        echo "       compose_slides convert input.pptx -o output.pdf"
        echo "       compose_slides convert input.html --format markdown"
        echo "       compose_slides convert deck.pptx --format all"
        echo "       compose_slides check"
        echo ""
        echo "NL: arka make slides about Rust memory safety"
        echo "    arka convert slides.pptx to pdf"
        echo "    arka convert deck.html to markdown"
        echo ""
        echo "Formats: pptx (default), pdf, html, md (Marp), json, all"
        echo "Requires: Pillow; python-pptx for pptx; pymupdf optional for PDF input"
        echo "Optional: LibreOffice (soffice) for direct pptx↔pdf"
        echo "Output: ~/Documents/arka-slides/ by default (SLIDES_OUTPUT_DIR)"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_compose_slides.py) $argv
end

function convert_media --description "Convert images, video/audio, and slide decks between formats"
    if test (count $argv) -eq 0
        echo "Usage: convert_media photo.png --to webp"
        echo "       convert_media clip.mp4 --to gif"
        echo "       convert_media deck.pptx --to pdf"
        echo "       convert_media input.png --format all"
        echo "       convert_media check"
        echo ""
        echo "NL: arka convert video.mp4 to gif"
        echo "    arka convert image.png to webp"
        echo "    arka convert deck.pptx to pdf"
        echo ""
        echo "Images: png, jpg, webp, gif, bmp, tiff, ico (Pillow; HEIC/SVG optional)"
        echo "Video: mp4, webm, mov, avi, mkv, gif, mp3, wav, aac (ffmpeg)"
        echo "Slides: pptx, pdf, html, md, json (python-pptx, pymupdf optional)"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_convert_media.py) $argv
end

function pdf_tools --description "PDF toolkit — merge, split, compress, OCR, protect, convert, …"
    if test (count $argv) -eq 0
        echo "Usage: pdf_tools <command> [args]"
        echo ""
        echo "Commands:"
        echo "  merge <a.pdf> <b.pdf> … [-o out.pdf]"
        echo "  split <file.pdf> [--pages-per-file N]"
        echo "  compress <file.pdf>"
        echo "  edit <file.pdf> --text 'Note'"
        echo "  sign <file.pdf> --image sig.png"
        echo "  convert <doc.docx> [--to pdf|docx|png]"
        echo "  images-to-pdf <img1.png> [img2.jpg …]"
        echo "  pdf-to-images <file.pdf> [--format png] [--dpi 150]"
        echo "  extract-images <file.pdf>"
        echo "  protect <file.pdf> --password secret"
        echo "  unlock <file.pdf> --password secret"
        echo "  rotate <file.pdf> --degrees 90 [--pages 1,3-5]"
        echo "  remove-pages <file.pdf> --pages 2,5-7"
        echo "  extract-pages <file.pdf> --pages 1,3"
        echo "  rearrange <file.pdf> --order 3,1,2"
        echo "  webpage-to-pdf <url>"
        echo "  ocr <file.pdf> [--language eng]"
        echo "  watermark <file.pdf> --text DRAFT"
        echo "  page-numbers <file.pdf>"
        echo "  overlay <base.pdf> <overlay.pdf>"
        echo "  compare <a.pdf> <b.pdf>"
        echo "  web-optimize <file.pdf>"
        echo "  redact <file.pdf> --text 'secret'"
        echo "  create [--text 'Hello'] [--html-file page.html]"
        echo "  check                           (operations + backends)"
        echo ""
        echo "NL: arka merge these pdfs a.pdf and b.pdf"
        echo "    arka compress report.pdf"
        echo "    arka pdf to images scan.pdf"
        echo "    arka protect pdf with password secret"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_pdf_tools.py) $argv
end

function youtube_transcript --description "Fetch or summarize a YouTube video transcript"
    if test (count $argv) -lt 1
        echo "Usage: youtube_transcript <url|video-id> [--summarize] [-q question]"
        echo "Example: youtube_transcript 'https://youtube.com/watch?v=abc123'"
        echo "Example: youtube_transcript abc123 --summarize"
        echo "No captions? Prompts to download audio + transcribe (or --yes-transcribe)"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_youtube.py) $argv
end

function media_transcript --description "Transcribe or summarize local mp3/mp4/audio/video"
    if test (count $argv) -lt 1
        echo "Usage: media_transcript <file.mp3|mp4|wav> [--summarize] [-q question] [-o out.txt] [--save]"
        echo "       media_transcript --setup-local"
        echo "Example: media_transcript ~/Videos/lecture.mp4 --summarize -q \"who is the villain?\""
        echo "Example: media_transcript podcast.mp3 -o podcast.txt"
        echo "Uses GROQ/SARVAM when keys set; local faster-whisper fallback (MEDIA_STT=local|auto)"
        echo "Setup offline STT: media_transcript --setup-local"
        return 1
    end
    if test "$argv[1]" = --setup-local
        set -l py (_arka_python)
        $py (_arka_py_script arka_media.py) setup-local
        return $status
    end
    set -l py (_arka_python)
    set -l action transcript
    set -l args
    for a in $argv
        switch $a
            case --summarize -s
                set action summarize
            case '*'
                set -a args $a
        end
    end
    if test (count $args) -eq 0
        echo "Usage: media_transcript <file.mp3|mp4|wav> [--summarize] [-q question] [-o out.txt] [--save]"
        return 1
    end
    if test "$action" = summarize
        $py (_arka_py_script arka_media.py) summarize $args
    else
        $py (_arka_py_script arka_media.py) transcript $args
    end
end

function transcribe_media --description "Alias for media_transcript"
    media_transcript $argv
end

function folder_summarize --description "Summarize all media files in a folder into one digest"
    if test (count $argv) -eq 0
        echo "Usage: folder_summarize <directory> [-r] [--limit N] [-q question]"
        echo "Example: folder_summarize ~/Videos/YoutubeDownloads/Singles"
        echo "Example: folder_summarize ~/Podcasts -r --limit 10"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_batch_summarize.py) folder $argv
end

function playlist_summarize --description "Summarize a YouTube playlist URL or local playlist folder"
    if test (count $argv) -eq 0
        echo "Usage: playlist_summarize --url <playlist-url> [--limit N] [-q question]"
        echo "       playlist_summarize --folder <downloaded-playlist-dir>"
        echo "Example: playlist_summarize --url 'https://youtube.com/playlist?list=...'"
        echo "Example: arka youtube playlist_summarize PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige --limit 5"
        echo "Example: arka summarize youtube PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige --limit 5"
        echo "Captions first; asks before download + local transcribe when missing"
        echo "Example: playlist_summarize --folder ~/Videos/YoutubeDownloads/MySeries"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_batch_summarize.py) playlist $argv
end

function _arka_youtube_tools_ready --description "Ensure yt-dlp is available for YouTube skills (internal)"
    if command -v yt-dlp >/dev/null
        return 0
    end
    set -l py (_arka_python)
    set -l pip (dirname $py)/pip
    test -x $pip; or set pip (dirname $py)/pip3
    if test -x $pip
        echo (set_color yellow)"Installing yt-dlp into Arka venv…"(set_color normal)
        $pip install -q yt-dlp
        command -v yt-dlp >/dev/null; and return 0
        test -x (dirname $py)/yt-dlp; and return 0
    end
    if _arka_is_macos; and command -v brew >/dev/null
        echo (set_color yellow)"yt-dlp not found — install with: brew install yt-dlp"(set_color normal)
    else
        echo (set_color yellow)"yt-dlp not found — install with: pip install yt-dlp"(set_color normal)
    end
    return 1
end

function youtube_research --description "Search YouTube, summarize all result transcripts into one research brief"
    if test (count $argv) -eq 0
        echo "Usage: youtube_research <search query> [--limit N] [--focus question] [--index] [--show-items]"
        echo "Default: 2 videos (override with --limit N or 'analyze N videos on …')"
        echo "Example: youtube_research \"how to fix hair loss\" --limit 5"
        echo "Example: youtube_research \"analyze 3 videos on python asyncio\""
        echo "Example: youtube_research \"python asyncio tutorial\" --focus \"best practices for beginners\""
        echo "Example: youtube_research \"IPL 2025 highlights\" --index --ask \"who scored most runs\""
        echo ""
        echo "  youtube_research list          — saved sessions"
        echo "  youtube_research ask <id> <q>  — follow-up on indexed session"
        return 1
    end
    set -l py (_arka_python)
    if test "$argv[1]" = list
        $py (_arka_py_script arka_youtube_research.py) list
        return $status
    end
    if contains -- check verify test -- "$argv[1]"
        _arka_local_test $_ARKA_ROOT/local/tests/test_youtube_pipeline.py
        return $status
    end
    if test "$argv[1]" = ask
        if test (count $argv) -lt 3
            echo "Usage: youtube_research ask <session-id> <question>"
            return 1
        end
        $py (_arka_py_script arka_youtube_research.py) ask $argv[2] $argv[3..-1]
        return $status
    end
    _arka_youtube_tools_ready; or return 1
    $py (_arka_py_script arka_youtube_research.py) search $argv
end

function yt_research --description "Alias for youtube_research"
    youtube_research $argv
end

function find_videos --description "Search YouTube and list video links (fast, no LLM)"
    if test (count $argv) -eq 0
        echo "Usage: find_videos <topic>"
        echo "Example: find_videos swimming tutorial"
        echo "NL: arka videos to learn swimming"
        return 1
    end
    set -l py (_arka_python)
    set -l out (_arka_capture_output $py (_arka_py_script arka_youtube_research.py) links $argv)
    if test -z "$out"
        echo (set_color red)"No videos found (install yt-dlp: brew install yt-dlp)"(set_color normal)
        return 1
    end
    _arka_ui_header "YouTube videos" query
    echo ""
    _arka_print_answer "$out"
end

function summarize_url --description "Summarize a web page or article URL"
    if test (count $argv) -lt 1
        echo "Usage: summarize_url <url> [-q question]"
        echo "Example: summarize_url https://example.com/article"
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_summarize.py) $argv
end

function post_x --description "Fetch a URL, shorten to <=40 words; post to X only when auth is configured"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_x_post.py)
    if test (count $argv) -eq 1; and string match -qr '(?i)(post|share|tweet|shorten|linkedin|twitter|\bx\b)' -- "$argv[1]"
        set -l parsed (_agent_build_post_x_cmd "$argv[1]")
        if test -n "$parsed"
            set argv (string split " " -- $parsed)
            set -e argv[1]
        end
    end
    if test (count $argv) -lt 1
        echo "Usage: post_x <url> [--words N] [--dry-run] [--post]"
        echo "       post_x --from-session [--words N] [--dry-run] [--post]"
        echo "Example: post_x https://www.linkedin.com/posts/... --words 40"
        echo "NL: arka post this https://linkedin.com/... on my x"
        echo "Default: draft only (copy/paste). Auto-post needs X_AUTH_TOKEN + X_CT0 or TWITTER_* API keys."
        echo "Use --post to force publish when credentials are configured."
        return 1
    end
    $py "$script" $argv
end

function _agent_is_daily_brief_request --description "True if user wants a daily/morning/tech brief (internal)"
    set -l clean (string lower "$argv[1]")
    string match -qr '(?i)\b(?:(?:daily|morning|news)\s+brief|today.?s\s+(?:tech\s+)?brief|(?:daily|morning|news|today.?s)\s+tech\s+brief|tech\s+brief(?:\s+(?:personalized(?:\s+for\s+me)?|for\s+me))?|personalized\s+(?:tech\s+)?brief)\b' "$clean"
end

function daily_brief --description "Morning brief: local weather + top news headlines"
    if not _arka_ensure_venv
        return 1
    end
    set -l args $argv
    set -l url_limit ""
    while test (count $args) -gt 0
        switch $args[1]
            case --url-limit
                set url_limit 1
                set args $args[2..-1]
            case --no-url-limit
                set url_limit 0
                set args $args[2..-1]
            case -h --help
                echo "Usage: daily_brief [--url-limit|--no-url-limit] [tech] [personalized]"
                echo "  --url-limit      Include a short excerpt under each headline (BRIEF_URL_WORDS, default 30)"
                echo "  --no-url-limit   Headlines only: - Title — URL (no excerpt)"
                echo "Env: BRIEF_URL_LIMIT_ENABLED=1|0  BRIEF_URL_WORDS=30"
                return 0
            case '*'
                break
        end
    end
    set -l query (string join " " $args)
    set -l clean (string lower "$query")
    set -l tech_focus 0
    set -l personalized 0
    if string match -qr '(?i)\btech\b' "$clean"
        set tech_focus 1
    end
    if string match -qr '(?i)\b(personalized|for\s+me|my\s+interests)\b' "$clean"
        set personalized 1
    end

    if test $tech_focus -eq 1
        _arka_ui_header "Tech Brief" info
    else
        _arka_ui_header "Daily Brief" info
    end
    echo ""
    if test $tech_focus -ne 1
        _arka_ui_header "Weather" section
        hyperlocal_weather
        echo ""
    end
    _arka_ui_header "Headlines" section

    set -l mem_ctx ""
    if test $personalized -eq 1
        set -l py (_arka_python)
        set mem_ctx ($py (_arka_py_script arka_daily_brief.py) mem-ctx "tech interests and career" 2>/dev/null | string trim)
    end

    set -l py (_arka_python)
    set -l prompt_args prompt
    test $tech_focus -eq 1; and set -a prompt_args --tech-focus
    if test -n "$mem_ctx"
        set -a prompt_args --mem-ctx "$mem_ctx"
    end
    set -l prompt ($py (_arka_py_script arka_daily_brief.py) $prompt_args 2>/dev/null | string trim)
    if test -z "$prompt"
        if test $tech_focus -eq 1
            set prompt "Give 5-7 concise tech news headlines for today in bullet points covering AI, startups, developer tools, and major tech industry news. For each bullet include the source URL after an em dash."
            if test -n "$mem_ctx"
                set prompt "$prompt Personalize headline selection to: $mem_ctx"
            end
        else if test -n "$mem_ctx"
            set prompt "Give 5 brief top news headlines for today in bullet points, India and world mix. Personalize to: $mem_ctx. For each bullet include the source URL after an em dash."
        else
            set prompt "Give 5 brief top news headlines for today in bullet points, India and world mix. For each bullet include the source URL after an em dash."
        end
    end
    if test -n "$url_limit"
        set -lx BRIEF_URL_LIMIT_ENABLED $url_limit
    end
    web_answer --no-session "$prompt"
end

function _arka_wifi_iface --description "Wi-Fi device name (macOS, internal)"
    set -l want 0
    for line in (networksetup -listallhardwareports 2>/dev/null)
        if string match -q "Hardware Port: Wi-Fi" -- "$line"
            set want 1
            continue
        end
        if test $want -eq 1
            set -l dev (string match -r 'Device:\s+(\S+)' "$line")
            if test (count $dev) -ge 2
                echo $dev[2]
                return
            end
        end
    end
    echo en0
end

function _arka_macos_wifi_profiler --description "Wi-Fi details from system_profiler JSON (macOS, internal)"
    set -l iface $argv[1]
    set -l py (_arka_python)
    $py -c '
import json, subprocess, sys
iface = sys.argv[1]
proc = subprocess.run(
    ["system_profiler", "SPAirPortDataType", "-json"],
    capture_output=True, text=True, timeout=30,
)
if proc.returncode != 0 or not proc.stdout.strip():
    sys.exit(1)
data = json.loads(proc.stdout)
sec_labels = {
    "spairport_security_mode_wpa2_personal": "WPA2 Personal",
    "spairport_security_mode_wpa3_personal": "WPA3 Personal",
    "spairport_security_mode_wpa2_enterprise": "WPA2 Enterprise",
    "spairport_security_mode_wpa_personal": "WPA Personal",
    "spairport_security_mode_wep": "WEP",
    "spairport_security_mode_none": "Open",
}
for item in data.get("SPAirPortDataType", []):
    for wi in item.get("spairport_airport_interfaces", []):
        if wi.get("_name") != iface:
            continue
        cur = wi.get("spairport_current_network_information")
        if not isinstance(cur, dict) or not cur.get("_name"):
            sys.exit(1)
        ssid = cur.get("_name", "")
        sig = cur.get("spairport_signal_noise", "")
        rssi = noise = ""
        if sig:
            parts = sig.replace(" dBm", "").split(" / ")
            if len(parts) == 2:
                rssi, noise = parts
        channel = cur.get("spairport_network_channel", "")
        sec = sec_labels.get(
            cur.get("spairport_security_mode", ""),
            str(cur.get("spairport_security_mode", "")).replace("spairport_security_mode_", "").replace("_", " ").title(),
        )
        print("\t".join([ssid, rssi, noise, channel, sec]))
        sys.exit(0)
sys.exit(1)
' $iface 2>/dev/null
end

function _arka_macos_wifi_info --description "Current Wi-Fi on macOS (internal)"
    set -l iface (_arka_wifi_iface)
    set -l airport /System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport
    set -l ssid ""
    set -l rssi ""
    set -l noise ""
    set -l channel ""
    set -l security ""

    if test -x $airport
        for line in (string split \n ($airport -I 2>/dev/null))
            if string match -qr '^\s*SSID:\s+' "$line"
                set ssid (string replace -r '^\s*SSID:\s+' '' "$line" | string trim)
            else if string match -qr '^\s*agrCtlRSSI:\s+' "$line"
                set rssi (string replace -r '^\s*agrCtlRSSI:\s+' '' "$line" | string trim)
            else if string match -qr '^\s*agrCtlNoise:\s+' "$line"
                set noise (string replace -r '^\s*agrCtlNoise:\s+' '' "$line" | string trim)
            else if string match -qr '^\s*channel:\s+' "$line"
                set channel (string replace -r '^\s*channel:\s+' '' "$line" | string trim)
            else if string match -qr '^\s*link auth:\s+' "$line"
                set security (string replace -r '^\s*link auth:\s+' '' "$line" | string trim)
            end
        end
    end

    if test -z "$ssid"
        set -l netline (networksetup -getairportnetwork $iface 2>/dev/null | string trim)
        if string match -qr '^Current Wi-Fi Network:\s+' "$netline"
            set ssid (string replace -r '^Current Wi-Fi Network:\s+' '' "$netline" | string trim)
        end
    end

    if test -z "$ssid"; or test -z "$rssi"
        set -l prow (_arka_macos_wifi_profiler $iface)
        if test (count $prow) -ge 1; and test -n "$prow[1]"
            set -l parts (string split \t "$prow[1]")
            if test -z "$ssid"; and test (count $parts) -ge 1
                set ssid $parts[1]
            end
            if test -z "$rssi"; and test (count $parts) -ge 2; and test -n "$parts[2]"
                set rssi $parts[2]
            end
            if test -z "$noise"; and test (count $parts) -ge 3; and test -n "$parts[3]"
                set noise $parts[3]
            end
            if test -z "$channel"; and test (count $parts) -ge 4; and test -n "$parts[4]"
                set channel $parts[4]
            end
            if test -z "$security"; and test (count $parts) -ge 5; and test -n "$parts[5]"
                set security $parts[5]
            end
        end
    end

    if test -z "$ssid"
        echo "Not connected to Wi-Fi (interface $iface)"
        return 1
    end

    echo (set_color --bold blue)"━━━ Wi-Fi ━━━"(set_color normal)
    echo "  Interface: $iface"
    echo "  Network:   $ssid"
    if test -n "$rssi"
        echo "  Signal:    $rssi dBm"
    end
    if test -n "$noise"
        echo "  Noise:     $noise dBm"
    end
    if test -n "$channel"
        echo "  Channel:   $channel"
    end
    if test -n "$security"
        echo "  Security:  $security"
    end
    set -l ip (ipconfig getifaddr $iface 2>/dev/null)
    if test -n "$ip"
        echo "  IP:        $ip"
    end
    return 0
end

function wifi_info --description "Show current Wi-Fi network and signal strength"
    if _arka_is_macos
        _arka_macos_wifi_info
        return $status
    end
    if command -v nmcli >/dev/null
        set -l line (nmcli -t -f ACTIVE,SSID,SIGNAL,SECURITY dev wifi | string match -r '^yes:.*' | head -1)
        if test -n "$line"
            set -l parts (string split ":" "$line")
            echo (set_color --bold blue)"━━━ Wi-Fi ━━━"(set_color normal)
            echo "  Network:  $parts[2]"
            echo "  Signal:   $parts[3]%"
            echo "  Security: $parts[4]"
            return 0
        end
        echo (set_color yellow)"Not connected to Wi-Fi (or nmcli has no active AP)"(set_color normal)
        nmcli dev status 2>/dev/null
        return 1
    end
    if test -f /proc/net/wireless
        echo (set_color --bold blue)"━━━ Wireless interfaces ━━━"(set_color normal)
        cat /proc/net/wireless
        return 0
    end
    echo (set_color red)"Wi-Fi info unavailable (install NetworkManager/nmcli on Linux)"(set_color normal)
    return 1
end

function open_finance --description "Open top financial websites"
    echo (set_color --bold blue)"━━━ Opening Financial Sites ━━━"(set_color normal)
    open_urls \
        "https://finance.yahoo.com" \
        "https://www.bloomberg.com" \
        "https://www.moneycontrol.com" \
        "https://www.tradingview.com" \
        "https://economictimes.indiatimes.com/markets"
end

function open_news --description "Open top news websites"
    echo (set_color --bold blue)"━━━ Opening News Sites ━━━"(set_color normal)
    open_urls \
        "https://news.google.com" \
        "https://www.reuters.com" \
        "https://www.bbc.com/news" \
        "https://indianexpress.com" \
        "https://timesofindia.indiatimes.com"
end

# --- DevOps & Engineering Skills (inspired by claude-skills repo) ---

function git_summary --description "Show a quick git project overview"
    if not test -d .git
        echo (set_color red)"✗ Not a git repository"(set_color normal)
        return 1
    end

    echo (set_color --bold blue)"━━━ Git Summary ━━━"(set_color normal)
    echo (set_color cyan)"  Repo:     "(set_color normal)(basename (pwd))
    echo (set_color cyan)"  Branch:   "(set_color normal)(git branch --show-current 2>/dev/null)
    echo (set_color cyan)"  Remote:   "(set_color normal)(git remote get-url origin 2>/dev/null; or echo "none")
    echo (set_color cyan)"  Commits:  "(set_color normal)(git rev-list --count HEAD 2>/dev/null)
    echo (set_color cyan)"  Authors:  "(set_color normal)(git shortlog -sn --no-merges 2>/dev/null | wc -l | string trim)
    echo ""
    echo (set_color --bold yellow)"  Recent commits:"(set_color normal)
    git log --oneline -5 --decorate 2>/dev/null | while read -l line
        echo "    $line"
    end
    echo ""
    set -l modified (git status --porcelain 2>/dev/null | wc -l | string trim)
    if test "$modified" -gt 0
        echo (set_color --bold red)"  ⚠ $modified uncommitted change(s)"(set_color normal)
    else
        echo (set_color --bold green)"  ✓ Working tree clean"(set_color normal)
    end
end

function pr_check --description "PR diff, CI status, explain failures, babysit until merge-ready"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_pr_check.py)
    if test (count $argv) -eq 0
        echo "Usage: pr_check <diff|summary|ci|explain|babysit> [options]"
        echo ""
        echo "  pr_check diff [--base main]     — changes vs base branch"
        echo "  pr_check summary                — LLM summary + test plan"
        echo "  pr_check ci                     — GitHub PR checks & workflow runs"
        echo "  pr_check explain                — diagnose latest CI failure"
        echo "  pr_check babysit [--fix] [--wait] — loop until merge-ready"
        echo ""
        echo "Requires: git repo + gh auth login (for ci/explain/babysit)"
        echo "NL: arka why did ci fail  |  arka babysit my pr"
        return 0
    end
    switch $argv[1]
        case diff
            $py $script diff $argv[2..-1]
            return $status
        case summary sum
            $py $script summary $argv[2..-1]
            return $status
        case ci checks status
            $py $script ci $argv[2..-1]
            return $status
        case explain why diagnose
            set -l answer (_arka_capture_output $py $script explain $argv[2..-1])
            set -l st $status
            if test $st -ne 0
                return $st
            end
            if test -z "$answer"
                return 1
            end
            _arka_print_answer_block "$answer" "CI diagnosis"
            return 0
        case babysit babysitter merge-ready mergeready
            $py $script babysit $argv[2..-1]
            return $status
        case route match
            $py $script $argv[1] $argv[2..-1]
            return $status
        case '*'
            set -l route ($py $script route (string join " " $argv) 2>/dev/null | string trim)
            if test -n "$route"
                _agent_run_skill_line "$route"
                return $status
            end
            $py $script $argv
            return $status
    end
end

function github_repo --description "Recent GitHub repo commits and modified files"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_github_repo.py)
    if test (count $argv) -eq 0
        echo "Usage: github_repo activity owner/repo [--days N]"
        echo "NL: arka tell what files changed in 2 days for https://github.com/owner/repo"
        return 0
    end
    set -l answer (_arka_capture_output $py $script $argv)
    set -l st $status
    if test $st -ne 0
        return $st
    end
    if test -z "$answer"
        return 1
    end
    _arka_print_answer_block "$answer" "GitHub activity"
end

function competitions --description "Search hackathons and ML competitions across curated sources"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_competitions.py)
    if test (count $argv) -eq 0
        $py $script sources
        return $status
    end
    set -l answer (_arka_capture_output $py $script $argv)
    set -l st $status
    if test $st -ne 0
        return $st
    end
    if test -z "$answer"
        return 1
    end
    _arka_print_answer_block "$answer" "Competitions"
end

function route_learn --description "Teach and manage learned NL routing rules"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_route_learn.py)
    if test (count $argv) -eq 0
        $py $script list
        return $status
    end
    $py $script $argv
end

function bookmarks --description "Save, search, and recall URL bookmarks with tags"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_bookmarks.py)
    if test (count $argv) -eq 0
        $py $script list
        return $status
    end
    $py $script $argv
end

function repo_health --description "Detect and run quick lint/test checks for the current repo"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_repo_health.py)
    if test (count $argv) -eq 0
        $py $script scan
        return $status
    end
    $py $script $argv
end

function generate_data --description "Generate sample or real-world datasets (CSV, JSON, World Bank, PubMed, URL)"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_generate_data.py)
    $py $script $argv
end

function data_gen --description "Alias for generate_data — fake or real datasets"
    generate_data $argv
end

function data_ask --description "Ask questions about CSV, JSON, TSV, and other data files or folders"
    if test (count $argv) -eq 0
        echo "Usage: data_ask <file|folder> [--format csv] [--formats csv,json] [--question q] [question]"
        echo "Example: data_ask users.csv how many rows?"
        echo "Example: data_ask ./data/ --format csv average salary?"
        echo "Example: data_ask folder ./exports --question how many records total?"
        echo "NL: agent \"summarize csv files in data/\""
        return 1
    end
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_data_ask.py)
    set -l target $argv[1]
    if test -z "$target"
        echo "Usage: data_ask <file|folder> [--format csv] [question]"
        return 1
    end
    echo (set_color --bold blue)"━━━ 📊 $target ━━━"(set_color normal)
    echo "  🔍 Analyzing data…" >&2
    set -l answer ($py $script $argv | string collect)
    set -l st $status
    if test $st -ne 0
        echo (set_color red)"$answer"(set_color normal)
        return $st
    end
    echo ""
    _pdf_print_answer "$answer"
end

function ask_data --description "Alias for data_ask — Q&A over data files"
    data_ask $argv
end

function query_data --description "Alias for data_ask — query tabular or JSON data"
    data_ask $argv
end

function analyze_data --description "Alias for data_ask — summarize or analyze data files"
    data_ask $argv
end

function docker_status --description "Docker containers, images, logs, and daemon health"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_docker_status.py)
    if test (count $argv) -eq 0
        $py $script ps
        return $status
    end
    $py $script $argv
end

function clipboard_history --description "Save, list, and restore clipboard history entries"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_clipboard_history.py)
    if test (count $argv) -eq 0
        $py $script list
        return $status
    end
    $py $script $argv
end

function disk_usage --description "Analyze disk usage of current or specified directory"
    set -l target "."
    if test (count $argv) -gt 0
        set target $argv[1]
    end

    echo (set_color --bold blue)"━━━ Disk Usage: $target ━━━"(set_color normal)
    echo ""

    if command -v dust &>/dev/null
        dust -n 15 "$target" 2>/dev/null
    else
        du -sh "$target"/* 2>/dev/null | sort -rh | head -15 | while read -l line
            echo "  $line"
        end
    end

    echo ""
    echo (set_color cyan)"  Total: "(set_color normal)(du -sh "$target" 2>/dev/null | cut -f1)
    echo (set_color cyan)"  Free:  "(set_color normal)(df -h "$target" 2>/dev/null | awk 'NR==2{print $4}')
end

function _agent_is_storage_breakdown_question --description "True if user wants disk space by category (internal)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)(disk\s*space|storage|disk\s*usage|space\s*left|space\s*free|what.*taking\s+(up\s+)?space|where.*(space|storage)|how\s+(much|is)\s+(my\s+)?(disk|storage|space)|full\s+disk|running\s+out\s+of\s+space)' "$clean"
        return 0
    end
    if string match -qr '(?i)(space\s+used\s+by|storage\s+by|breakdown|by\s+category|videos?|pictures?|photos?|documents?|downloads?|music|archives?)' "$clean"
        and string match -qr '(?i)(disk|space|storage|drive|gb|megabyte|gigabyte|full|free|used)' "$clean"
        return 0
    end
    if string match -qr '(?i)^(show|check|analyze|scan)\s+(my\s+)?(disk|storage|space)' "$clean"
        return 0
    end
    return 1
end

function disk_breakdown --description "Show disk space used by videos, pictures, documents, etc."
    set -l target $HOME
    if test (count $argv) -ge 1
        set -l first $argv[1]
        if contains -- $first usage breakdown
            if test (count $argv) -ge 2
                set target $argv[2]
            end
        else
            set target $first
        end
    end
    set -l py (_arka_python)
    set -l out ($py (_arka_py_script arka_disk.py) breakdown "$target" 2>&1)
    if test $status -ne 0
        echo (set_color red)"$out"(set_color normal)
        return 1
    end
    printf '%s%s%s\n' (set_color --bold green) "━━━ Storage breakdown ━━━" (set_color normal)
    printf '%s\n' "$out"
end

function pdf_list --description "List ingested documents (filename + artifact id)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_pdf_rag.py) list
end

function doc_list --description "Alias for pdf_list — list ingested documents"
    pdf_list $argv
end

function pdf_ingest --description "Ingest a document; auto-starts PrivateGPT and Qdrant if needed"
    if test (count $argv) -eq 0
        echo "Usage: pdf_ingest <path>"
        echo "Example: pdf_ingest ~/Documents/report.pdf"
        echo "Example: doc_ingest ~/Notes/readme.md"
        echo "Formats: arka pdf formats  |  python3 (_arka_py_script arka_pdf_rag.py) formats"
        echo "Also: arka pdf ingest <path>  |  agent \"ingest document ~/path/file.docx\""
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_pdf_rag.py) ingest $argv[1]
end

function pdf_ingest_dir --description "Ingest all PDFs under a directory (recursive, default ~/Documents)"
    set -l py (_arka_python)
    set -l dir ~/Documents
    set -l extra

    for arg in $argv
        switch $arg
            case -h --help
                echo "Usage: pdf_ingest_dir [directory] [--no-recursive]"
                echo "Example: pdf_ingest_dir"
                echo "Example: pdf_ingest_dir /home/s/Documents"
                return 0
            case --no-recursive
                set -a extra --no-recursive
            case '*'
                set dir $arg
        end
    end

    set dir (realpath $dir 2>/dev/null; or echo $dir)
    echo (set_color cyan)"Ingesting PDFs from $dir …"(set_color normal)
    $py (_arka_py_script arka_pdf_rag.py) batch-ingest $extra "$dir"
end

function doc_ingest --description "Ingest any supported file (PDF, Office, text, code) into RAG"
    pdf_ingest $argv
end

function codebase_ingest --description "Index a project directory for TurboQuant Q&A"
    if test (count $argv) -eq 0
        echo "Usage: codebase_ingest <project-dir> [-n name]"
        echo "Example: codebase_ingest $_ARKA_ROOT -n fish"
        echo "Then: doc_ask --doc codebase-fish \"how does agent routing work?\""
        return 1
    end
    set -l py (_arka_python)
    $py (_arka_py_script arka_pdf_rag.py) codebase-ingest $argv
end

function _pdf_normalize_answer --description "Split inline markdown bullets onto separate lines (internal)"
    set -l text (string trim -- "$argv[1]")
    printf '%s' "$text" | string replace -a -r '\s+\*\s+' "\n* "
end

function _pdf_bullet --description "Print one PDF answer bullet line (internal)"
    set -l indent "$argv[1]"
    set -l title "$argv[2]"
    set -l body "$argv[3]"
    set_color green
    echo -n "$indent• "
    if test -n "$title"
        set_color --bold
        echo -n "$title: "
    end
    set_color normal
    echo "$body"
end

function _pdf_print_answer --description "Pretty-print PDF RAG answer for the terminal (internal)"
    set -l lines (_pdf_normalize_answer "$argv[1]")
    for line in $lines
        set -l raw "$line"
        set line (string trim -- "$line")
        if test -z "$line"
            echo ""
            continue
        end
        if string match -qr '(?i)^(based on|here .{0,60}summary|these excerpts|the document|the provided)' "$line"
            set_color brblack
            echo "  $line"
            set_color normal
            continue
        end
        set -l main (string match -r '^\*\s+\*\*(.+?)(?::\*\*|\*\*:)\s*(.*)$' "$line")
        if test (count $main) -ge 3
            _pdf_bullet "  " "$main[2]" "$main[3]"
            continue
        end
        set -l nested (string match -r '^\s+\*\s+\*\*(.+?)(?::\*\*|\*\*:)\s*(.*)$' "$raw")
        if test (count $nested) -ge 3
            _pdf_bullet "    " "$nested[2]" "$nested[3]"
            continue
        end
        set -l bul (string match -r '^\*\s+(.+)$' "$line")
        if test (count $bul) -ge 2
            set -l body "$bul[2]"
            set -l labeled (string match -r '^\*\*(.+?)(?::\*\*|\*\*:)\s*(.*)$' "$body")
            if test (count $labeled) -ge 3
                _pdf_bullet "  " "$labeled[2]" "$labeled[3]"
            else
                set -l inline (string replace -a -r '\*\*([^*]+)\*\*' '$1' "$body")
                _pdf_bullet "  " "" "$inline"
            end
            continue
        end
        set -l sub (string match -r '^\s+\*\s+(.+)$' "$raw")
        if test (count $sub) -ge 2
            set -l body (string replace -a -r '\*\*([^*]+)\*\*' '$1' "$sub[2]")
            _pdf_bullet "    " "" "$body"
            continue
        end
        echo "  $line"
    end
end

function _arka_capture_output --description "Run a command; preserve stdout newlines in one string (internal)"
    $argv | string collect
end

function _arka_normalize_answer --description "Split inline markdown lists onto separate lines (internal)"
    set -l text "$argv[1]"
    test -z "$text"; and return
    # Do not use string trim on multiline answers — fish collapses newlines to spaces.
    printf '%s' "$text" | python3 -c '
import re, sys
text = sys.stdin.read().strip()
text = re.sub(r"\s+#{2,3}\s+", r"\n\n## ", text)
text = re.sub(r"\s+---\s+", r"\n\n---\n\n", text)
text = re.sub(r"\s+•\s+", r"\n* ", text)
# Split concatenated headline bullets: "Title — URL - Next headline"
text = re.sub(
    r"(https?://\S+)(?:\.\.\.)?(?:[)\].,;]*)?\s*-\s+(?=\S)",
    r"\1\n- ",
    text,
)
text = re.sub(r"(\*\*.+?\*\*)\s+(\d+)\.", r"\1\n\2.", text)
text = re.sub(r"\.\s+(\d+)\.\s+", r".\n\1. ", text)
# Only split numbered lists at line boundaries — not "item #5" mid-sentence.
text = re.sub(r"(?<=\n)\s*(\d+)\.\s+", r"\n\1. ", text)
text = re.sub(r"(?<=\n)\s*\*\s+", r"\n* ", text)
# Detach pipe tables from preceding headings or prose.
text = re.sub(r"(#{1,6}\s[^\n|]+)\s+(\|)", r"\1\n\2", text)
# Split inlined markdown table rows (| end-of-row | start-of-next-row |).
text = re.sub(r"\|\s+\|", "|\n|", text)
lines = []
for line in text.splitlines():
    m = re.match(r"^(\d+\.\s+(?:\*\*.+?\*\*:|\*\*.+?\*\*)\s*.+?\.\s+)([A-Z].+)$", line)
    if m:
        lines.append(m.group(1).strip())
        lines.append("")
        lines.append(m.group(2).strip())
    else:
        lines.append(line)

def regroup_vertical_rank_table(src):
    out = []
    i = 0
    while i < len(src):
        if i + 3 < len(src):
            h = [src[i + j].strip() for j in range(4)]
            hl = [x.lower() for x in h]
            if hl[0] == "rank" and hl[1] == "option" and hl[2] == "risk" and hl[3] in ("strategy", "best for"):
                i += 4
                while i < len(src):
                    t = src[i].strip()
                    if not t or "---" in t or re.fullmatch(r"[\s:·\-|]+", t):
                        i += 1
                        continue
                    break
                rows = []
                while i + 3 < len(src):
                    chunk = [src[i + j].strip() for j in range(4)]
                    if re.fullmatch(r"\d+", chunk[0]) and chunk[1]:
                        rows.append(chunk)
                        i += 4
                    else:
                        break
                if rows:
                    out.append("| " + " | ".join(h) + " |")
                    for row in rows:
                        out.append("| " + " | ".join(row) + " |")
                    out.append("")
                    continue
        out.append(src[i])
        i += 1
    return out

lines = regroup_vertical_rank_table(lines)
print("\n".join(lines).strip())
'
end

function _arka_color_source --description "Orange tone for source citations (internal)"
    set_color D78700
end

function _arka_strip_atx_prefix --description "Remove ATX markdown heading prefix (# .. ###### + space) (internal)"
    set -l text (string trim -- "$argv[1]")
    test -z "$text"; and return
    if string match -qr '^#{1,6}\s+\S' -- "$text"
        set text (string replace -r '^#{1,6}\s+' '' -- "$text")
    end
    echo -n "$text"
end

function _arka_is_markdown_heading --description "True for ATX markdown headings (# .. ###### + space), not #hashtags (internal)"
    set -l text (string trim -- "$argv[1]")
    test -z "$text"; and return 1
    # CommonMark ATX: 1–6 hashes, required space, then title (#health is NOT a heading).
    if not string match -qr '^#{1,6}\s+\S' -- "$text"
        return 1
    end
    set -l m (string match -r '^#{1,6}\s+(.+)$' -- "$text")
    test (count $m) -lt 2; and return 1
    set -l title (_arka_clean_markdown_stars "$m[2]")
    test -z "$title"; and return 1
    if _arka_is_source_line "$title"
        return 1
    end
    if string match -qr '(?i)^Sources?\s*:' -- "$title"
        return 1
    end
    return 0
end

function _arka_parse_markdown_heading --description "Heading title text without leading # marks (internal)"
    set -l text (string trim -- "$argv[1]")
    set -l m (string match -r '^#{1,6}\s+(.+)$' -- "$text")
    test (count $m) -lt 2; and return
    _arka_clean_markdown_stars "$m[2]"
end

function _arka_clean_markdown_stars --description "Strip *, **, *** markdown emphasis from displayed text (internal)"
    set -l text (string trim -- "$argv[1]")
    test -z "$text"; and return
    set text (string replace -a -r '\*\*\*(.+?)\*\*\*' '$1' -- "$text")
    set text (string replace -a -r '\*\*(.+?)\*\*' '$1' -- "$text")
    set text (string replace -a -r '\*(.+?)\*' '$1' -- "$text")
    set text (string replace -a '*' '' -- "$text")
    set text (string replace -a -r '(?<![A-Za-z0-9])_([^_]+)_(?![A-Za-z0-9])' '$1' -- "$text")
    set text (string trim -- "$text")
    echo -n "$text"
end

function _arka_strip_source_text --description "Plain text for source citations — no bullets or * (internal)"
    set -l text (_arka_strip_atx_prefix "$argv[1]")
    test -z "$text"; and return
    set text (_arka_clean_markdown_stars "$text")
    test -z "$text"; and return
    set text (string replace -r '^[•\-\*]\s+' '' -- "$text")
    set text (string trim -- "$text")
    echo -n "$text"
end

function _arka_print_source_line --description "Orange source / citation line (internal)"
    set -l text (_arka_strip_source_text "$argv[1]")
    test -z "$text"; and return
    set -l rest ""
    set -l m (string match -r '(?i)^([^\n]+?Sources?\s*:[^\n]+?)\s{2,}(.+)$' -- "$text")
    if test (count $m) -ge 3
        set text (string trim -- "$m[2]")
        set rest (string trim -- "$m[3]")
    end
    _arka_color_source
    echo "  $text"
    set_color normal
    if test -n "$rest"
        echo "  $rest"
    end
end

function _arka_is_source_line --description "True if line is a web/source citation (internal)"
    set -l text (_arka_strip_source_text "$argv[1]")
    test -z "$text"; and return 1
    string match -qr '(?i)^Sources?\s*:' -- "$text"; and return 0
    string match -qr '(?i)^\(Sources?\s*:' -- "$text"; and return 0
    string match -qr '(?i)via (provided )?search results' -- "$text"; and return 0
    string match -qr '(?i)via web search' -- "$text"; and return 0
    string match -qr '(?i)^according to\s' -- "$text"; and return 0
    return 1
end

function _arka_is_sources_section --description "True if line is a Sources section title (internal)"
    set -l text (_arka_clean_markdown_stars (_arka_strip_atx_prefix "$argv[1]"))
    test -z "$text"; and return 1
    string match -qr '(?i)^Sources?\s*:?\s*$' -- "$text"
end

function _arka_print_numbered --description "Print one numbered answer line (internal)"
    set -l num "$argv[1]"
    set -l title "$argv[2]"
    set -l body "$argv[3]"
    set_color green
    echo -n "  $num. "
    if test -n "$title"
        set_color --bold
        echo -n "$title: "
    end
    set_color normal
    echo "$body"
end

function _arka_print_md_table --description "Render aligned markdown pipe table (internal)"
    test (count $argv) -eq 0; and return
    printf '%s\n' $argv | python3 -c '
import re, sys

def is_sep(cells):
    return all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip())

rows = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("|"):
        continue
    cells = [re.sub(r"\*\*([^*]+)\*\*", r"\1", c.strip()) for c in line.strip("|").split("|")]
    if not cells or is_sep(cells):
        continue
    rows.append(cells)

if not rows:
    sys.exit(0)

ncols = max(len(r) for r in rows)
widths = [0] * ncols
for r in rows:
    for i, c in enumerate(r):
        if i < ncols:
            widths[i] = max(widths[i], len(c))

for r in rows:
    parts = []
    for i in range(ncols):
        cell = r[i] if i < len(r) else ""
        parts.append(cell.ljust(widths[i]))
    print("  " + "  ".join(parts))
'
end

# ── Terminal UI (consistent headers, queries, answer blocks) ──

function _arka_ui_header --description "Standard ━━━ section header (internal)"
    set -l title "$argv[1]"
    set -l kind info
    test (count $argv) -ge 2; and set kind $argv[2]
    switch $kind
        case answer research essay
            printf '%s%s%s\n' (set_color --bold green) "━━━ $title ━━━" (set_color normal)
        case info tool
            printf '%s%s%s\n' (set_color --bold blue) "━━━ $title ━━━" (set_color normal)
        case section
            echo (set_color --bold yellow) "$title" (set_color normal)
        case query
            printf '%s%s%s\n' (set_color cyan) "🔎 $title" (set_color normal) >&2
        case chat
            printf '%s%s%s\n' (set_color cyan) "💬 $title" (set_color normal) >&2
        case math
            printf '%s%s%s\n' (set_color cyan) "🧮 $title" (set_color normal) >&2
        case error
            printf '%s%s%s\n' (set_color cyan) "🔧 $title" (set_color normal) >&2
        case warn
            printf '%s%s%s\n' (set_color --bold yellow) "━━━ $title ━━━" (set_color normal)
        case '*'
            printf '%s%s%s\n' (set_color --bold green) "━━━ $title ━━━" (set_color normal)
    end
end

function _arka_ui_model --description "Model footer under answer blocks (internal)"
    if set -q SHOW_MODEL; and test "$SHOW_MODEL" = 0 -o "$SHOW_MODEL" = false
        return
    end
    set -l model (_arka_llm_model_label 2>/dev/null)
    test -z "$model"; and return
    echo ""
    set_color brblack
    echo "  Model: $model"
    set_color normal
end

function _arka_pretty_python_output --description "Format Python ━━━ blocks like web_answer (internal)"
    set -l raw "$argv[1]"
    test -z "$raw"; and return
    set -l lines (string split \n -- "$raw")
    set -l n (count $lines)
    set -l i 1
    set -l buf
    while test $i -le $n
        set -l line $lines[$i]
        set -l trimmed (string trim -- "$line")
        if string match -qr '^Searching web' "$trimmed"
            echo "$trimmed" >&2
            set i (math $i + 1)
            continue
        end
        if string match -qr '^arka_llm:' "$trimmed"
            echo "$trimmed" >&2
            set i (math $i + 1)
            continue
        end
        if string match -qr '^━━━ .+ ━━━$' "$trimmed"
            if test -n "$buf"
                printf '%s\n' $buf
                set buf
            end
            set -l title (string replace -r '^━━━ (.+) ━━━$' '$1' "$trimmed")
            set -l body_lines
            set i (math $i + 1)
            while test $i -le $n
                set -l ln $lines[$i]
                set -l tln (string trim -- "$ln")
                if string match -qr '^━━━ .+ ━━━$' "$tln"
                    break
                end
                if string match -qr '^Model:' "$tln"
                    set i (math $i + 1)
                    continue
                end
                if string match -qr '^  ' "$ln"
                    set ln (string sub -s 3 -- "$ln")
                end
                set -a body_lines "$ln"
                set i (math $i + 1)
            end
            if test "$title" = "Currency Conversion"
                printf '%s%s%s\n' (set_color --bold green) "━━━ $title ━━━" (set_color normal)
                for ln in $body_lines
                    if test -z "$ln"
                        echo ""
                    else
                        echo "  $ln"
                    end
                end
                continue
            end
            set -l joined (string join \n -- $body_lines)
            _arka_print_answer_block "$joined" "$title"
            continue
        end
        set -a buf "$line"
        set i (math $i + 1)
    end
    if test -n "$buf"
        printf '%s\n' $buf
    end
end

function _arka_print_answer --description "Pretty-print web/chat answer for the terminal (internal)"
    set -l raw "$argv[1]"
    test -z "$raw"; and return

    set -l tag ""
    if string match -qr '^\[FROM (SEARCH|MEMORY)\]' -- "$raw"
        set tag (string match -r '^\[FROM (SEARCH|MEMORY)\]' -- "$raw")[2]
        set raw (string replace -r '^\[FROM (SEARCH|MEMORY)\]\s*' '' -- "$raw")
    else if string match -qr '^FROM (SEARCH|MEMORY):' -- "$raw"
        set tag (string match -r '^FROM (SEARCH|MEMORY):' -- "$raw")[2]
        set raw (string replace -r '^FROM (SEARCH|MEMORY):\s*' '' -- "$raw")
    end
    if test -n "$tag"
        set_color brblack
        echo "  [FROM $tag]"
        set_color normal
        echo ""
    end

    set -l normalized (_arka_normalize_answer "$raw" | string collect)
    set -l lines (string split \n -- "$normalized")
    set -l n (count $lines)
    set -l pending_table
    for i in (seq 1 $n)
        set -l trimmed (string trim -- $lines[$i])
        test -z "$trimmed"; and echo ""; and continue

        if string match -qr '^\|' -- "$trimmed"
            set -a pending_table "$trimmed"
            set -l next_i (math $i + 1)
            if test $next_i -gt $n; or not string match -qr '^\|' -- (string trim -- $lines[$next_i])
                _arka_print_md_table $pending_table
                set -e pending_table
            end
            continue
        end

        set -l h2 (_arka_parse_markdown_heading "$trimmed")
        if _arka_is_markdown_heading "$trimmed"
            set_color --bold cyan
            echo "$h2"
            set_color normal
            echo ""
            continue
        end

        set -l hdr (string match -r '^\*\*(.+?)\*\*\s*$' -- "$trimmed")
        if test (count $hdr) -ge 2
            set_color --bold cyan
            echo (_arka_clean_markdown_stars "$hdr[2]")
            set_color normal
            echo ""
            continue
        end

        set -l hdr3 (_arka_clean_markdown_stars (_arka_strip_atx_prefix "$trimmed"))
        if _arka_is_sources_section "$trimmed"
            set_color --bold cyan
            echo "$hdr3"
            set_color normal
            echo ""
            continue
        end

        if _arka_is_source_line "$trimmed"
            _arka_print_source_line "$trimmed"
            continue
        end

        set -l num (string match -r '^(\d+)\.\s+\*\*(.+?)(?::\*\*|\*\*:)\s*(.*)$' -- "$trimmed")
        if test (count $num) -ge 4
            _arka_print_numbered "$num[2]" "$num[3]" "$num[4]"
            continue
        end
        set num (string match -r '^(\d+)\.\s+\*\*(.+?)\*\*\s*(.*)$' -- "$trimmed")
        if test (count $num) -ge 4
            _arka_print_numbered "$num[2]" "$num[3]" "$num[4]"
            continue
        end
        set num (string match -r '^(\d+)\.\s+(.+)$' -- "$trimmed")
        if test (count $num) -ge 3
            set -l body (string replace -a -r '\*\*([^*]+)\*\*' '$1' -- "$num[3]")
            _arka_print_numbered "$num[2]" "" "$body"
            continue
        end

        set -l main (string match -r '^\*\s+\*\*(.+?)(?::\*\*|\*\*:)\s*(.*)$' -- "$trimmed")
        if test (count $main) -ge 3
            _pdf_bullet "  " "$main[2]" "$main[3]"
            continue
        end
        set -l bul (string match -r '^\*\s+(.+)$' -- "$trimmed")
        if test (count $bul) -ge 2
            set -l body (string replace -a -r '\*\*([^*]+)\*\*' '$1' -- "$bul[2]")
            if _arka_is_source_line "$body"
                _arka_print_source_line "$body"
                continue
            end
            _pdf_bullet "  " "" "$body"
            continue
        end

        if string match -qr '^[^\s\-*].+/$' -- "$trimmed"
            set_color --bold cyan
            echo "  $trimmed"
            set_color normal
            continue
        end

        set -l ibul (string match -r '^(\s+)•\s+(.+)$' -- "$lines[$i]")
        if test (count $ibul) -ge 3
            if _arka_is_source_line "$ibul[2]"
                _arka_print_source_line "$ibul[2]"
                continue
            end
            _pdf_bullet "$ibul[1]" "" "$ibul[2]"
            continue
        end

        set -l ubul (string match -r '^•\s+(.+)$' -- "$trimmed")
        if test (count $ubul) -ge 2
            if _arka_is_source_line "$ubul[2]"
                _arka_print_source_line "$ubul[2]"
                continue
            end
            _pdf_bullet "  " "" "$ubul[2]"
            continue
        end

        set -l dbul (string match -r '^-\s+(.+)$' -- "$trimmed")
        if test (count $dbul) -ge 2
            set -l body (string replace -a -r '\*\*([^*]+)\*\*' '$1' -- "$dbul[2]")
            if _arka_is_source_line "$body"
                _arka_print_source_line "$body"
                continue
            end
            _pdf_bullet "  " "" "$body"
            continue
        end

        if string match -qr '(?i)^(based on|here .{0,60}(summary|answer|list)|these (places|cities|options)|in summary|to summarize)' -- "$trimmed"
            set_color brblack
            echo "  $trimmed"
            set_color normal
            continue
        end

        if string match -qr '^---+$' -- "$trimmed"
            echo ""
            continue
        end
        if string match -q '⚠*' -- "$trimmed"
            set -l warn (string replace -a -r '\*\*([^*]+)\*\*' '$1' -- "$trimmed")
            set_color yellow
            echo "  $warn"
            set_color normal
            continue
        end

        if _arka_is_source_line "$trimmed"
            _arka_print_source_line "$trimmed"
            continue
        end

        set -l src_tail (string match -r '(?i)^(.+?[.!?])\s+([\*_]*Sources?\s*:.+)$' -- "$trimmed")
        if test (count $src_tail) -ge 3
            set -l body (string trim -- "$src_tail[2]")
            set -l src (string trim -- "$src_tail[3]")
            set -l inline_body (string replace -a -r '\*\*([^*]+)\*\*' '$1' -- "$body")
            echo "  $inline_body"
            echo ""
            _arka_print_source_line "$src"
            continue
        end

        set -l inline (_arka_clean_markdown_stars "$trimmed")
        test -z "$inline"; and continue
        echo "  $inline"
    end
end

function _arka_print_answer_block --description "Standard answer block: header + body + model (internal)"
    set -l answer "$argv[1]"
    set -l title "$argv[2]"
    test -z "$title"; and set title "Answer"
    set -l kind answer
    switch (string lower "$title")
        case answer
            set kind answer
        case "research answer" research
            set kind research
        case essay
            set kind essay
        case "investment research" "error help" "pdf answer"
            set kind answer
        case '*'
            set kind answer
    end
    _arka_ui_header "$title" $kind
    echo ""
    _arka_print_answer "$answer"
    _arka_ui_model
end

function pdf_ask --description "Ask or summarize ingested documents; optional --doc to pick one file"
    if test (count $argv) -eq 0
        echo "Usage: pdf_ask [--doc DOCUMENT] <question>"
        echo "Example: pdf_ask --doc Profile.pdf what are the main skills?"
        echo "Example: doc_ask --doc readme.md summarize the setup steps"
        echo "NL: agent \"ask Profile.pdf about skills\"  |  summarize notes.md"
        return 1
    end
    set -l doc_flag
    set -l args $argv
    if test "$argv[1]" = --doc -o "$argv[1]" = -d
        if test (count $argv) -lt 3
            echo "Usage: pdf_ask --doc DOCUMENT <question>"
            return 1
        end
        set doc_flag --doc $argv[2]
        set args $argv[3..-1]
    end
    if test (count $args) -eq 0
        echo "Usage: pdf_ask [--doc DOCUMENT] <question>"
        return 1
    end
    set -l question (string join " " $args)
    set -l py (_arka_python)
    if test -z "$doc_flag"
        set -l parsed ($py (_arka_py_script arka_pdf_rag.py) parse-ask "$question" 2>/dev/null)
        if test $status -eq 0 -a -n "$parsed"
            set -l parts (string split \t "$parsed")
            if test (count $parts) -ge 3 -a -n "$parts[2]" -a -n "$parts[3]"
                set doc_flag --doc $parts[2]
                set question $parts[3]
            end
        end
    end
    set -l doc_label ""
    if test -n "$doc_flag"
        set doc_label $doc_flag[2]
        echo (set_color --bold blue)"━━━ 📄 $doc_label ━━━"(set_color normal)
    else
        echo (set_color --bold blue)"━━━ 📄 PDF answer ━━━"(set_color normal)
    end
    set_color brblack
    echo "  $question"
    echo "  🔍 Searching document…" >&2
    set_color normal
    set -l answer
    set -lx PDF_QUIET 1
    set -l py (_arka_python)
    if test -n "$doc_flag"
        set answer ($py (_arka_py_script arka_pdf_rag.py) ask $doc_flag $question | string collect)
    else
        set answer ($py (_arka_py_script arka_pdf_rag.py) ask $question | string collect)
    end
    set -l st $status
    if test $st -ne 0
        echo (set_color red)"$answer"(set_color normal)
        return $st
    end
    echo ""
    _pdf_print_answer "$answer"
end

function doc_ask --description "Alias for pdf_ask — Q&A over any ingested document"
    pdf_ask $argv
end

function port_scan --description "Check what ports are in use locally"
    echo (set_color --bold blue)"━━━ Open Ports ━━━"(set_color normal)
    echo ""
    if command -v ss &>/dev/null
        ss -tlnp 2>/dev/null | head -20 | while read -l line
            echo "  $line"
        end
    else
        netstat -tlnp 2>/dev/null | head -20 | while read -l line
            echo "  $line"
        end
    end
end

function speedtest --description "Quick internet speed test"
    echo (set_color --bold blue)"━━━ Internet Speed Test ━━━"(set_color normal)
    echo (set_color brblack)"  Testing download speed..."(set_color normal)

    if command -v speedtest-cli &>/dev/null
        speedtest-cli --simple 2>/dev/null
    else
        # Fallback: download a test file and measure speed
        set -l start_time (date +%s%N)
        set -l bytes (curl -s -o /dev/null -w '%{size_download}' "http://speedtest.tele2.net/1MB.zip" 2>/dev/null)
        set -l end_time (date +%s%N)
        set -l elapsed_ms (math "($end_time - $start_time) / 1000000")
        if test $elapsed_ms -gt 0
            set -l speed_mbps (math "$bytes * 8 / $elapsed_ms / 1000")
            echo (set_color --bold green)"  Download: ~$speed_mbps Mbps"(set_color normal)
        else
            echo (set_color red)"  Could not measure speed"(set_color normal)
        end
        echo (set_color brblack)"  Tip: Install speedtest-cli for accurate results"(set_color normal)
    end
end

function clipboard --description "Copy text to clipboard or show clipboard contents"
    if test (count $argv) -gt 0
        if _arka_copy_to_clipboard (string join " " $argv)
            echo (set_color --bold green)"✓ Copied to clipboard"(set_color normal)
        else
            echo (set_color red)"Clipboard copy unavailable on this platform"(set_color normal) >&2
            return 1
        end
    else if not isatty stdin
        if _arka_copy_stdin_to_clipboard
            echo (set_color --bold green)"✓ Copied from pipe to clipboard"(set_color normal)
        else
            echo (set_color red)"Clipboard copy unavailable on this platform"(set_color normal) >&2
            return 1
        end
    else
        echo (set_color --bold blue)"━━━ Clipboard ━━━"(set_color normal)
        set -l clip (_arka_paste_from_clipboard)
        if test $status -eq 0; and test -n "$clip"
            echo $clip
        else
            echo "(empty)"
        end
    end
end

function todo --description "Quick todo list manager"
    set -l todo_file ~/.local/share/agent_todos.txt
    mkdir -p (dirname $todo_file)
    touch $todo_file

    if test (count $argv) -eq 0
        # Show todos
        echo (set_color --bold blue)"━━━ Todo List ━━━"(set_color normal)
        if test -s $todo_file
            set -l i 1
            while read -l line
                echo (set_color cyan)"  $i."(set_color normal)" $line"
                set i (math $i + 1)
            end < $todo_file
        else
            echo (set_color brblack)"  No todos. Add one: todo Buy groceries"(set_color normal)
        end
        return 0
    end

    set -l action $argv[1]
    switch $action
        case done rm remove
            if test (count $argv) -lt 2
                echo "Usage: todo done <number>"
                return 1
            end
            set -l num $argv[2]
            set -l total (wc -l < $todo_file | string trim)
            if test $num -gt 0 -a $num -le $total
                set -l removed (sed -n "{$num}p" $todo_file)
                sed -i "{$num}d" $todo_file
                echo (set_color --bold green)"✓ Done: $removed"(set_color normal)
            else
                echo (set_color red)"Invalid todo number: $num"(set_color normal)
            end
        case clear
            echo -n "" > $todo_file
            echo (set_color --bold green)"✓ All todos cleared"(set_color normal)
        case '*'
            # Add a new todo
            set -l item (string join " " $argv)
            echo $item >> $todo_file
            set -l count (wc -l < $todo_file | string trim)
            echo (set_color --bold green)"✓ Added (#$count): $item"(set_color normal)
    end
end

function translate --description "Translate text using a dedicated neural translation model"
    if test (count $argv) -lt 2
        echo "Usage: translate <target_language> <text>"
        echo "Example: translate spanish Hello, how are you?"
        return 1
    end

    set -l translated (python3 -c "
import urllib.request, urllib.parse, json, sys

args = sys.argv[1:]
lang_map = {
    'afrikaans': 'af', 'albanian': 'sq', 'amharic': 'am', 'arabic': 'ar', 'armenian': 'hy', 'assamese': 'as',
    'aymara': 'ay', 'azerbaijani': 'az', 'bambara': 'bm', 'basque': 'eu', 'belarusian': 'be', 'bengali': 'bn',
    'bhojpuri': 'bho', 'bosnian': 'bs', 'bulgarian': 'bg', 'catalan': 'ca', 'cebuano': 'ceb', 'chichewa': 'ny',
    'chinese': 'zh-CN', 'mandarin': 'zh-CN', 'cantonese': 'zh-HK', 'corsican': 'co', 'croatian': 'hr', 'czech': 'cs', 'danish': 'da', 'dhivehi': 'dv',
    'dogri': 'doi', 'dutch': 'nl', 'english': 'en', 'esperanto': 'eo', 'estonian': 'et', 'ewe': 'ee',
    'filipino': 'tl', 'finnish': 'fi', 'french': 'fr', 'frisian': 'fy', 'galician': 'gl', 'georgian': 'ka',
    'german': 'de', 'greek': 'el', 'guarani': 'gn', 'gujarati': 'gu', 'haitian creole': 'ht', 'hausa': 'ha',
    'hawaiian': 'haw', 'hebrew': 'he', 'hindi': 'hi', 'hmong': 'hmn', 'hungarian': 'hu', 'icelandic': 'is',
    'igbo': 'ig', 'ilocano': 'ilo', 'indonesian': 'id', 'irish': 'ga', 'italian': 'it', 'japanese': 'ja',
    'javanese': 'jv', 'kannada': 'kn', 'kazakh': 'kk', 'khmer': 'km', 'kinyarwanda': 'rw', 'konkani': 'gom',
    'krio': 'kri', 'kurdish': 'ku', 'kyrgyz': 'ky', 'lao': 'lo', 'latin': 'la', 'latvian': 'lv',
    'lingala': 'ln', 'lithuanian': 'lt', 'luganda': 'lg', 'luxembourgish': 'lb', 'macedonian': 'mk',
    'maithili': 'mai', 'malagasy': 'mg', 'malay': 'ms', 'malayalam': 'ml', 'maltese': 'mt', 'maori': 'mi',
    'marathi': 'mr', 'meiteilon': 'mni-Mtei', 'mizo': 'lus', 'mongolian': 'mn', 'myanmar': 'my', 'burmese': 'my',
    'nepali': 'ne', 'norwegian': 'no', 'nyanja': 'ny', 'odia': 'or', 'oromo': 'om', 'pashto': 'ps',
    'persian': 'fa', 'farsi': 'fa', 'polish': 'pl', 'portuguese': 'pt', 'punjabi': 'pa', 'quechua': 'qu',
    'romanian': 'ro', 'russian': 'ru', 'samoan': 'sm', 'sanskrit': 'sa', 'scots gaelic': 'gd', 'sepedi': 'nso',
    'serbian': 'sr', 'sesotho': 'st', 'shona': 'sn', 'sindhi': 'sd', 'sinhala': 'si', 'slovak': 'sk',
    'slovenian': 'sl', 'somali': 'so', 'spanish': 'es', 'sundanese': 'su', 'swahili': 'sw', 'swedish': 'sv',
    'tajik': 'tg', 'tamil': 'ta', 'tatar': 'tt', 'telugu': 'te', 'thai': 'th', 'tigrinya:': 'ti',
    'tsonga': 'ts', 'turkish': 'tr', 'turkmen': 'tk', 'twi': 'ak', 'ukrainian': 'uk', 'urdu': 'ur',
    'uyghur': 'ug', 'uzbek': 'uz', 'vietnamese': 'vi', 'welsh': 'cy', 'xhosa': 'xh', 'yiddish': 'yi',
    'yoruba': 'yo', 'zulu': 'zu'
}

# Clean up quotes from all arguments
args = [a.strip().strip(chr(39) + chr(34)) for a in args if a.strip()]

import re

raw = ' '.join(args)
if raw.lower().startswith('translate '):
    raw = raw[len('translate '):].strip()

lang = None
text = None
for lang_name in sorted(lang_map.keys(), key=len, reverse=True):
    m = re.match(rf'(?i)^(.+?)\s+to\s+{re.escape(lang_name)}\s*\$', raw)
    if m:
        text = m.group(1).strip()
        lang = lang_name
        break

if lang is None:
    first_word = args[0].lower() if args else ''
    last_word = args[-1].lower() if args else ''
    if last_word in lang_map or last_word in lang_map.values():
        lang = args[-1]
        text = ' '.join(args[:-1])
    elif first_word in lang_map or first_word in lang_map.values():
        lang = args[0]
        text = ' '.join(args[1:])
    else:
        lang = args[0] if args else 'english'
        text = ' '.join(args[1:]) if len(args) > 1 else raw

# Drop trailing \" to\" when language was parsed from last token only
text = re.sub(r'(?i)\s+to\s*\$', '', text).strip()

target_lang = lang_map.get(lang.lower(), lang)

# Print language status to stderr so it displays but doesn't get captured in stdout
print(f'🌐 Translating to {lang.capitalize()}...', file=sys.stderr)

url = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=' + target_lang + '&dt=t&q=' + urllib.parse.quote(text)
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read().decode())
        translation = ''.join(x[0] for x in res[0] if x[0])
        print(translation)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" $argv)

    if test $status -eq 0
        echo (set_color --bold green) "✨ Translation:"
        echo (set_color yellow) "  $translated"
    else
        echo (set_color red) "✗ Failed to translate"
    end
end

function survive_lang --description "Travel survival phrases — translate basics to another language"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_survival_lang.py) --list
        echo ""
        echo "Usage: survive_lang <language> [phrase]"
        echo "Example: survive_lang japanese"
        echo "Example: survive_lang spanish \"I want to buy this\""
        echo "NL: arka teach me how to survive in french"
        echo "Set native language: ARKA_NATIVE_LANG=hindi (default: English or ARKA_SPEAK_LANG)"
        return 0
    end
    if test "$argv[1]" = list -o "$argv[1]" = --list -o "$argv[1]" = -l
        $py (_arka_py_script arka_survival_lang.py) --list
        return $status
    end
    set -l out (_arka_capture_output $py (_arka_py_script arka_survival_lang.py) $argv)
    if test -z "$out"
        echo (set_color red)"Could not build survival phrase list"(set_color normal)
        return 1
    end
    _arka_ui_header "Survival phrases" query
    echo ""
    _arka_print_answer "$out"
end

function generate_password --description "Generate secure passwords; store/retrieve by name (encrypted vault)"
    set -l py (_arka_python)
    set -l vault (_arka_py_script arka_password_vault.py)

    if test (count $argv) -eq 0
        _arka_generate_password_once 16
        return $status
    end

    switch $argv[1]
        case set put write
            if test (count $argv) -lt 3
                if test (count $argv) -lt 2
                    echo "Usage: generate_password set <name> <password>"
                    echo "       generate_password set <name>   — prompt securely (hidden)"
                    echo "Example: generate_password set wifi MyExistingSecret"
                    return 1
                end
                set -l name $argv[2]
                read -s -P "Password for '$name': " -l pwd
                echo
                if test -z "$pwd"
                    echo (set_color red)"No password entered."(set_color normal)
                    return 1
                end
            else
                set -l name $argv[2]
                set -l pwd (string join " " $argv[3..-1])
            end
            set -l out ($py $vault set $name --password "$pwd" 2>&1)
            set -l exit_st $status
            if test $exit_st -ne 0
                echo $out
                return $exit_st
            end
            echo (set_color --bold blue)"━━━ Password stored ━━━"(set_color normal)
            echo (set_color cyan)"  Name:  "(set_color normal)"$name"
            echo (set_color brblack)"  Vault: ~/.cache/fish-agent/passwords.vault.json (encrypted)"(set_color normal)
            echo (set_color brblack)"  (password not shown — use: generate_password get $name)"(set_color normal)
        case save store remember
            if test (count $argv) -lt 2
                echo "Usage: generate_password save <name> [length]"
                echo "Example: generate_password save wifi 24"
                echo "Example: generate_password save \"sumit gmail\""
                return 1
            end
            set -l name_parts $argv[2..-1]
            set -l length 16
            if test (count $name_parts) -ge 2
                set -l last $name_parts[-1]
                if string match -qr '^[0-9]+$' -- $last
                    set length $last
                    set -e name_parts[-1]
                end
            end
            set -l name (string join " " -- $name_parts)
            set -l out ($py $vault generate $name --length $length 2>&1)
            set -l exit_st $status
            if test $exit_st -ne 0
                echo $out
                return $exit_st
            end
            set -l pwd ""
            for line in $out
                if string match -qr '^__PASSWORD__=' -- $line
                    set pwd (string replace '__PASSWORD__=' '' $line)
                end
            end
            echo (set_color --bold blue)"━━━ Password saved ━━━"(set_color normal)
            echo (set_color cyan)"  Name:   "(set_color normal)"$name"
            echo (set_color --bold green)"  Secret: $pwd"(set_color normal)
            echo (set_color brblack)"  Vault:  ~/.cache/fish-agent/passwords.vault.json (encrypted)"(set_color normal)
            if _arka_copy_to_clipboard "$pwd"
                echo (set_color brblack)"  ✓ Copied to clipboard"(set_color normal)
            end
        case get show retrieve
            if test (count $argv) -lt 2
                echo "Usage: generate_password get <name>"
                return 1
            end
            set -l name (string join " " -- $argv[2..-1])
            set -l out ($py $vault get $name 2>&1)
            if test $status -ne 0
                echo $out
                return 1
            end
            set -l pwd ""
            set -l updated ""
            for line in $out
                if string match -qr '^__PASSWORD__=' -- $line
                    set pwd (string replace '__PASSWORD__=' '' $line)
                else if string match -qr '^__UPDATED__=' -- $line
                    set updated (string replace '__UPDATED__=' '' $line)
                end
            end
            echo (set_color --bold blue)"━━━ Stored password ━━━"(set_color normal)
            echo (set_color cyan)"  Name: "(set_color normal)"$name"
            echo (set_color --bold green)"  $pwd"(set_color normal)
            if test -n "$updated"
                echo (set_color brblack)"  Updated: $updated"(set_color normal)
            end
            if test -n "$pwd"; and _arka_copy_to_clipboard "$pwd"
                echo (set_color brblack)"  ✓ Copied to clipboard"(set_color normal)
            end
        case list ls
            $py $vault list
        case delete rm remove
            if test (count $argv) -lt 2
                echo "Usage: generate_password delete <name>"
                return 1
            end
            set -l name (string join " " -- $argv[2..-1])
            $py $vault delete $name
        case rotate renew
            if test (count $argv) -lt 2
                echo "Usage: generate_password rotate <name> [length]"
                return 1
            end
            set -l name_parts $argv[2..-1]
            set -l len_flag
            if test (count $name_parts) -ge 2
                set -l last $name_parts[-1]
                if string match -qr '^[0-9]+$' -- $last
                    set len_flag --length $last
                    set -e name_parts[-1]
                end
            end
            set -l name (string join " " -- $name_parts)
            set -l out ($py $vault rotate $name $len_flag 2>&1)
            if test $status -ne 0
                echo $out
                return $status
            end
            set -l pwd ""
            for line in $out
                if string match -qr '^__PASSWORD__=' -- $line
                    set pwd (string replace '__PASSWORD__=' '' $line)
                end
            end
            if test -n "$pwd"
                echo (set_color --bold green)"  New password: $pwd"(set_color normal)
                if _arka_copy_to_clipboard "$pwd"
                    echo (set_color brblack)"  ✓ Copied to clipboard"(set_color normal)
                end
            end
        case help -h --help
            echo "Usage: generate_password [length]              — one-time password (not saved)"
            echo "       generate_password save <name> [length]  — generate + store encrypted"
            echo "       generate_password set <name> <password>   — store your own password"
            echo "       generate_password get <name>            — retrieve (copies to clipboard)"
            echo "       generate_password list                    — list saved names"
            echo "       generate_password delete <name>         — remove from vault"
            echo "       generate_password rotate <name> [length]  — new password, same name"
        case '*'
            if string match -qr '^[0-9]+$' -- $argv[1]
                _arka_generate_password_once $argv[1]
            else
                echo "Unknown subcommand: $argv[1]  (try: save, set, get, list, delete, rotate)"
                return 1
            end
    end
end

function store_password --description "Alias: save generated (save) or store existing (set)"
    if test (count $argv) -eq 0
        generate_password help
        return 1
    end
    if test (count $argv) -ge 2; and not string match -qr '^[0-9]+$' -- $argv[2]
        generate_password set $argv
    else
        generate_password save $argv
    end
end

function pass --description "Alias for password vault (save/get/list)"
    if test (count $argv) -eq 0
        generate_password help
        return 0
    end
    generate_password $argv
end

function ip_info --description "Show public IP and geolocation"
    echo (set_color --bold blue)"━━━ IP Information ━━━"(set_color normal)
    set -l ip_data (curl -s "https://ipinfo.io/json" 2>/dev/null)

    if test -n "$ip_data"
        echo (set_color cyan)"  IP:       "(set_color normal)(echo $ip_data | jq -r '.ip // "N/A"')
        echo (set_color cyan)"  City:     "(set_color normal)(echo $ip_data | jq -r '.city // "N/A"')
        echo (set_color cyan)"  Region:   "(set_color normal)(echo $ip_data | jq -r '.region // "N/A"')
        echo (set_color cyan)"  Country:  "(set_color normal)(echo $ip_data | jq -r '.country // "N/A"')
        echo (set_color cyan)"  ISP:      "(set_color normal)(echo $ip_data | jq -r '.org // "N/A"')
        echo (set_color cyan)"  Timezone: "(set_color normal)(echo $ip_data | jq -r '.timezone // "N/A"')
    else
        echo (set_color red)"  ✗ Could not fetch IP info"(set_color normal)
    end
end

function _arka_stock_project_dir --description "stock_analysis project root (internal)"
    if set -q STOCK_PROJECT; and test -d "$STOCK_PROJECT"
        echo $STOCK_PROJECT
        return
    end
    set -l default ~/Projects/python/products/stock_analysis
    echo $default
end

function stock_analysis --description "Stock market intelligence (stock_analysis project)"
    set -l bridge (_arka_py_script arka_stock_bridge.py)
    set -l py (_arka_python)
    set -l stock_dir (_arka_stock_project_dir)
    if not set -q STOCK_PLAIN
        set -x STOCK_TERMINAL 1
    end
    if test (count $argv) -eq 0
        if test -d "$stock_dir"
            cd "$stock_dir"
        else
            echo (set_color yellow)"stock_analysis project not found:"(set_color normal) "$stock_dir"
            echo "Set STOCK_PROJECT in .env or clone the project there."
        end
        return
    end
    switch $argv[1]
        case cd
            if test -d "$stock_dir"
                cd "$stock_dir"
            else
                echo (set_color red)"✗ Not found:"(set_color normal) "$stock_dir"
                return 1
            end
        case news prices policy strategy volatility dashboard context path
            $py $bridge $argv[1] $argv[2..-1]
        case analyze
            if test (count $argv) -lt 2
                echo "Usage: stock_analysis analyze <TICKER>"
                return 1
            end
            $py $bridge strategy $argv[2]
        case predict
            if test (count $argv) -lt 2
                echo "Usage: stock_analysis predict <topic>"
                return 1
            end
            predictions --domain stocks $argv[2..-1]
        case compare
            set -l amt 3000
            set -l hz "1 month"
            if test (count $argv) -ge 2
                set amt $argv[2]
            end
            if test (count $argv) -ge 3
                set hz $argv[3]
            end
            $py (_arka_py_script arka_predictions.py) compare $amt --horizon "$hz"
        case macro events disaster
            $py (_arka_py_script arka_macro_events.py) --limit (test (count $argv) -ge 2; and echo $argv[2]; or echo 8)
        case funding fundings vc deals
            $py (_arka_py_script arka_competition_funding.py) --funding-limit (test (count $argv) -ge 2; and echo $argv[2]; or echo 8)
        case competition peers rivals
            set -l cf_args
            if test (count $argv) -ge 2
                set cf_args $argv[2..-1]
            end
            $py (_arka_py_script arka_competition_funding.py) $cf_args
        case fundamentals ratios metrics
            if test (count $argv) -lt 2
                echo "Usage: stock fundamentals TICKER [TICKER…]"
                echo "Example: stock fundamentals RELIANCE.NS TCS.NS INFY.NS"
                return 1
            end
            $py (_arka_py_script arka_stock_fundamentals.py) $argv[2..-1]
        case emotion sentiment mood crowd
            $py (_arka_py_script arka_market_emotion.py) --limit (test (count $argv) -ge 2; and echo $argv[2]; or echo 20)
        case invest
            if test (count $argv) -lt 2
                echo "Usage: stock invest <question>"
                echo "Example: stock invest where to invest 3000 for 1 month"
                return 1
            end
            predictions --domain stocks --deep $argv[2..-1]
        case help -h --help
            echo "Usage: stock_analysis [cd|news|prices|policy|strategy|volatility|dashboard|analyze|predict|context] ..."
            echo ""
            echo "  (no args)     cd to project"
            echo "  news          market news feeds"
            echo "  prices [T…]   live prices (default watchlist)"
            echo "  policy TICKER policy/regulatory scan"
            echo "  strategy TICKER  AI backtest + ML signal"
            echo "  analyze TICKER   alias for strategy"
            echo "  volatility T1,T2 period interval"
            echo "  dashboard     Streamlit Stock Intelligence Hub"
            echo "  predict TOPIC stocks opportunity analysis via Arka"
            echo "  invest QUESTION  where to invest ₹X for N days/months (auto deep research)"
            echo "  compare [AMT] [HORIZON]  top 5 news + data-ranked best options (no LLM)"
            echo "  macro [N]     disaster/resource/geopolitics → stock impact + duration"
            echo "  funding [N]   recent VC/PE/IPO deals + listed peer mapping"
            echo "  competition [TICKERS…]  peer scoreboard + rivalry news"
            echo "  fundamentals TICKER…  debt/equity, ROE, P/E, margins vs peers"
            echo "  emotion [N]   net news sentiment + who will buy/sell (crowd forecast)"
            echo "  context [T…]  plain-text bundle for debugging"
        case '*'
            $py $bridge $argv
    end
end

function stock --description "Alias for stock_analysis"
    stock_analysis $argv
end

function macro --description "Macro events → stock sector impact + duration"
    stock macro $argv
end

function emotion --description "Market sentiment and crowd buy/sell forecast"
    stock emotion $argv
end

function open_project --description "Quickly open a project directory in editor"
    set -l project_dirs ~/Projects ~/projects ~/Documents/Projects ~/repos ~/src
    set -l query (string join " " $argv)

    # Find project directories
    set -l found
    for base in $project_dirs
        if test -d "$base"
            for dir in (find "$base" -maxdepth 2 -type d -name ".git" 2>/dev/null)
                set -l project_dir (dirname "$dir")
                set -l project_name (basename "$project_dir")
                if test -z "$query"
                    set -a found $project_dir
                else if string match -qi "*$query*" "$project_name"
                    set -a found $project_dir
                end
            end
        end
    end

    if test (count $found) -eq 0
        if test -z "$query"
            echo (set_color yellow)"No git projects found in: $project_dirs"(set_color normal)
        else
            echo (set_color yellow)"No project matching '$query' found"(set_color normal)
        end
        return 1
    end

    if test -z "$query"
        # List all projects
        echo (set_color --bold blue)"━━━ Projects ━━━"(set_color normal)
        set -l i 1
        for p in $found
            echo (set_color cyan)"  $i."(set_color normal)" "(basename $p)" "(set_color brblack)"($p)"(set_color normal)
            set i (math $i + 1)
        end
    else if test (count $found) -eq 1
        # Open directly
        set -l dir $found[1]
        echo (set_color --bold green)"▶ Opening: "(basename $dir)(set_color normal)
        if command -v code &>/dev/null
            code "$dir" &
            disown
        else
            echo (set_color cyan)"  Path: $dir"(set_color normal)
        end
    else
        echo (set_color --bold blue)"━━━ Matching Projects ━━━"(set_color normal)
        for p in $found
            echo (set_color green)"  ▶ "(set_color normal)(basename $p)" "(set_color brblack)"($p)"(set_color normal)
        end
    end
end

function cheat --description "Quick developer cheat sheet using cht.sh"
    if test (count $argv) -eq 0
        echo "Usage: cheat <language/tool> <query>"
        echo "Example: cheat python list comprehension"
        echo "Example: cheat docker build"
        return 1
    end

    set -l query (string join "+" $argv)
    echo (set_color --bold blue)"━━━ Cheat Sheet: $argv ━━━"(set_color normal)
    echo ""
    curl -s "https://cht.sh/$query" | less -FRX
end

function qr_code --description "Generate a QR code in the terminal"
    if test (count $argv) -eq 0
        echo "Usage: qr_code <text-or-url>"
        echo "Example: qr_code https://google.com"
        return 1
    end

    set -l text (string join " " $argv)
    echo (set_color --bold blue)"━━━ QR Code Generator ━━━"(set_color normal)
    echo ""
    set -l py (_arka_python)
    set -l out ($py (_arka_py_script arka_qr.py) $argv 2>&1)
    set -l exit_st $status
    if test $exit_st -ne 0
        echo (set_color red)"✗ $out"(set_color normal)
        return $exit_st
    end
    if test -n "$out"
        echo $out
    end
end

function shorten_url --description "Shorten a URL using TinyURL"
    if test (count $argv) -eq 0
        echo "Usage: shorten_url <url>"
        return 1
    end

    set -l url $argv[1]
    if not string match -qr '^https?://' -- "$url"
        set url "https://$url"
    end

    echo (set_color --bold blue)"━━━ URL Shortener ━━━"(set_color normal)
    echo (set_color brblack)"  Shortening: $url..."(set_color normal)

    set -l short_url (curl -s "https://tinyurl.com/api-create.php?url=$url")

    if test -n "$short_url"; and string match -qr '^https?://' -- "$short_url"
        echo (set_color --bold green)"✓ Shortened: "(set_color cyan)"$short_url"(set_color normal)
        if command -v xclip &>/dev/null
            printf '%s' "$short_url" | xclip -selection clipboard
            echo (set_color brblack)"  ✓ Copied to clipboard!"(set_color normal)
        end
    else
        echo (set_color red)"✗ Failed to shorten URL. Check network or URL format."(set_color normal)
    end
end

function crypto_price --description "Show current prices for popular cryptocurrencies"
    set -l coins "BTC,ETH,SOL,ADA,DOT"
    if test (count $argv) -gt 0
        set coins (string upper (string join "," $argv))
    end

    echo (set_color --bold blue)"━━━ Crypto Prices (USD) ━━━"(set_color normal)
    
    python3 -c "
import sys, urllib.request, json

coins = sys.argv[1]
url = f'https://min-api.cryptocompare.com/data/pricemultifull?fsyms={coins}&tsyms=USD'

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    
    if 'DISPLAY' not in data:
        print(' \033[91m✗ Could not fetch data for: ' + coins + '\033[0m')
        sys.exit(1)
        
    display = data['DISPLAY']
    print('  \033[1m%-10s %-16s %-12s %-12s\033[0m' % ('Asset', 'Price', '24h Change', '24h High'))
    print('  ' + '-' * 54)
    
    for coin in coins.split(','):
        if coin in display:
            info = display[coin]['USD']
            price = info['PRICE']
            change = info['CHANGEPCT24HOUR']
            high = info['HIGH24HOUR']
            
            # Color code change
            val = float(change.replace('%','').replace('+','').replace('-','').strip())
            if '-' in change:
                color = '\033[91m' # Red
            else:
                color = '\033[92m' # Green
                change = '+' + change
                
            print('  %-10s %-16s %s%-12s\033[0m %-12s' % (coin, price, color, change + '%', high))
except Exception as e:
    print('  \033[91m✗ Error fetching crypto prices: ' + str(e) + '\033[0m')
" "$coins"
end

function _arka_currency_text_from_argv --description "Build currency NL text; recover shell-eaten \$amount (internal)"
    set -l text (string join " " $argv)
    set -l py (_arka_python)
    if test (count ($py (_arka_py_script arka_currency.py) parse (string escape --style=script -- $text) 2>/dev/null)) -gt 0
        echo $text
        return 0
    end
    if not string match -qr '^(?i)(to|in|into|ot)\s' -- "$text"
        echo $text
        return 0
    end
    for entry in (history --prefix arka --max 12 2>/dev/null)
        if string match -qr '(?i)convert\s+\$[0-9].*\b(to|in|into|ot)\s' -- "$entry"
            set -l stripped (string replace -r '^(?i).*?\bconvert\s+' '' -- "$entry" | string trim)
            if test (count ($py (_arka_py_script arka_currency.py) parse (string escape --style=script -- $stripped) 2>/dev/null)) -gt 0
                echo $stripped
                return 0
            end
        end
    end
    for entry in (history --prefix convert --max 8 2>/dev/null)
        if string match -qr '\$[0-9]' -- "$entry"
            set -l stripped (string replace -r '^(?i).*\b(convert|currency)\s+' '' -- "$entry" | string trim)
            if test (count ($py (_arka_py_script arka_currency.py) parse (string escape --style=script -- $stripped) 2>/dev/null)) -gt 0
                echo $stripped
                return 0
            end
        end
    end
    echo $text
end

function currency_convert --description "Convert amounts between currencies using live exchange rates"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: currency_convert <amount> <from> <to>"
        echo "       currency_convert convert 100 USD to INR"
        echo "       arka 'what is 500 EUR in GBP'"
        return 1
    end
    set -l text (_arka_currency_text_from_argv $argv)
    set -l out (_arka_capture_output $py (_arka_py_script arka_currency.py) convert (string escape --style=script -- $text))
    set -l st $status
    if test $st -ne 0
        echo $out >&2
        return $st
    end
    _arka_pretty_python_output "$out"
    return 0
end

function convert --description "Alias for currency_convert"
    currency_convert $argv
end

function currency --description "Alias for currency_convert"
    currency_convert $argv
end

function kalshi --description "Kalshi prediction market odds (read-only public API)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: kalshi search <keywords>"
        echo "       kalshi market <TICKER>"
        echo "       kalshi trending"
        echo "       kalshi status"
        echo "       arka 'kalshi predictions on bitcoin'"
        return 1
    end
    set -l out (_arka_capture_output $py (_arka_py_script arka_kalshi.py) $argv)
    set -l st $status
    if test $st -ne 0
        echo $out >&2
        return $st
    end
    _arka_pretty_python_output "$out"
    return 0
end

function sports_score --description "Live sports scores — IPL, cricket, NFL, NBA, soccer, F1, …"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_sports.py) live
        return $status
    end
    if test "$argv[1]" = leagues -o "$argv[1]" = list
        $py (_arka_py_script arka_sports.py) leagues
        return $status
    end
    $py (_arka_py_script arka_sports.py) live (string join " " $argv)
end

function live_scores --description "Alias for sports_score"
    sports_score $argv
end

function pomodoro --description "A simple Pomodoro timer with progress bar"
    set -l focus_time 25
    set -l break_time 5
    
    if test (count $argv) -gt 0
        set focus_time $argv[1]
    end
    if test (count $argv) -gt 1
        set break_time $argv[2]
    end

    set -l focus_sec (math "$focus_time * 60")
    set -l break_sec (math "$break_time * 60")

    echo (set_color --bold red)"🍅 Pomodoro: Focus for $focus_time minutes!"(set_color normal)
    if command -v notify-send &>/dev/null
        notify-send -u normal -t 3000 "Pomodoro" "Time to focus! 🍅 ($focus_time mins)"
    end

    for i in (seq $focus_sec -1 1)
        set -l mins (math "floor($i / 60)")
        set -l secs (math "$i % 60")
        set -l pct (math "floor((($focus_sec - $i) / $focus_sec) * 100)")
        set -l filled (math "floor($pct / 5)")
        set -l empty (math "20 - $filled")
        
        set -l bar "["
        if test $filled -gt 0
            for f in (seq 1 $filled)
                set bar "$bar█"
            end
        end
        if test $empty -gt 0
            for e in (seq 1 $empty)
                set bar "$bar░"
            end
        end
        set bar "$bar]"

        printf "\r  "(set_color red)"🍅 %02d:%02d "(set_color normal)"%-22s "(set_color yellow)"%d%%"(set_color normal) $mins $secs $bar $pct
        sleep 1
    end
    
    printf "\r"
    echo (set_color --bold green)"🎉 Focus session complete! Time for a break.                "(set_color normal)
    printf '\a'
    if command -v notify-send &>/dev/null
        notify-send -u normal -t 5000 "Pomodoro" "Great job! Take a $break_time-minute break. 🎉"
    end

    echo (set_color --bold green)"☕ Break: Relax for $break_time minutes!"(set_color normal)
    for i in (seq $break_sec -1 1)
        set -l mins (math "floor($i / 60)")
        set -l secs (math "$i % 60")
        set -l pct (math "floor((($break_sec - $i) / $break_sec) * 100)")
        set -l filled (math "floor($pct / 5)")
        set -l empty (math "20 - $filled")
        
        set -l bar "["
        if test $filled -gt 0
            for f in (seq 1 $filled)
                set bar "$bar█"
            end
        end
        if test $empty -gt 0
            for e in (seq 1 $empty)
                set bar "$bar░"
            end
        end
        set bar "$bar]"

        printf "\r  "(set_color green)"☕ %02d:%02d "(set_color normal)"%-22s "(set_color yellow)"%d%%"(set_color normal) $mins $secs $bar $pct
        sleep 1
    end

    printf "\r"
    echo (set_color --bold blue)"🔔 Break is over! Ready for another session?                "(set_color normal)
    printf '\a'
    if command -v notify-send &>/dev/null
        notify-send -u normal -t 5000 "Pomodoro" "Break over! Time to get back to work. 🍅"
    end
end

function system_monitor --description "Beautiful real-time system resource monitor"
    echo (set_color --bold blue)"━━━ Live System Monitor ━━━"(set_color normal)
    
    set -l cpu_pct (top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1}')
    if test -z "$cpu_pct"
        set cpu_pct (ps -eo pcpu | awk 'NR>1 {sum+=$1} END {print sum}')
    end
    set -l cpu_int (math "floor($cpu_pct)")

    set -l ram_info (free -m | awk '/Mem:/ {print $3, $2}')
    set -l ram_used (echo $ram_info | awk '{print $1}')
    set -l ram_total (echo $ram_info | awk '{print $2}')
    set -l ram_pct (math "floor(($ram_used / $ram_total) * 100)")

    set -l disk_pct (df -h / | awk 'NR==2 {print $5}' | tr -d '%')
    
    function _draw_bar
        set -l pct $argv[1]
        set -l color $argv[2]
        set -l filled (math "floor($pct / 10)")
        set -l empty (math "10 - $filled")
        set -l bar "["
        if test $filled -gt 0
            for f in (seq 1 $filled)
                set bar "$bar█"
            end
        end
        if test $empty -gt 0
            for e in (seq 1 $empty)
                set bar "$bar░"
            end
        end
        set bar "$bar]"
        echo -n (set_color $color)"$bar "(set_color --bold)"$pct%"(set_color normal)
    end

    set -l cpu_color green
    if test $cpu_int -gt 80; set cpu_color red; else if test $cpu_int -gt 50; set cpu_color yellow; end

    set -l ram_color green
    if test $ram_pct -gt 80; set ram_color red; else if test $ram_pct -gt 50; set ram_color yellow; end

    set -l disk_color green
    if test $disk_pct -gt 90; set disk_color red; else if test $disk_pct -gt 70; set disk_color yellow; end

    echo (set_color cyan)"  CPU:  "(set_color normal)(_draw_bar $cpu_int $cpu_color)
    echo (set_color cyan)"  RAM:  "(set_color normal)(_draw_bar $ram_pct $ram_color)" ($ram_used MB / $ram_total MB)"
    echo (set_color cyan)"  Disk: "(set_color normal)(_draw_bar $disk_pct $disk_color)" ("(df -h / | awk 'NR==2 {print $3 "/" $2}')")"
    
    echo ""
    echo (set_color brblack)"  Uptime: "(set_color normal)(uptime -p 2>/dev/null; or uptime)
    echo (set_color brblack)"  Load:   "(set_color normal)(cat /proc/loadavg 2>/dev/null | awk '{print $1, $2, $3}'; or uptime | awk -F'load average:' '{print $2}')
    
    if test -d /sys/class/power_supply/BAT0
        set -l bat_pct (cat /sys/class/power_supply/BAT0/capacity 2>/dev/null)
        set -l bat_status (cat /sys/class/power_supply/BAT0/status 2>/dev/null)
        set -l bat_color green
        if test $bat_pct -lt 20; set bat_color red; else if test $bat_pct -lt 50; set bat_color yellow; end
        echo (set_color brblack)"  Battery:"(set_color normal)" $bat_pct% ($bat_status)"
    end
end

function excuse --description "Get a funny programming excuse"
    set -l excuses \
        "It worked on my machine." \
        "That's a feature, not a bug." \
        "It's a caching issue. Just hard refresh." \
        "The third-party API must be down." \
        "I was told to write it this way." \
        "It's a known issue in the compiler." \
        "It must be a timezone issue." \
        "I haven't merged the latest master branch." \
        "The database must be locked." \
        "Did you clear your cookies?" \
        "That code was written by the previous developer." \
        "It's a hardware limitation." \
        "I think it's an Electron/Chromium bug." \
        "It's a floating point rounding error." \
        "It works 90% of the time. You must have hit the 10%." \
        "That's a weird edge case. Nobody would ever do that in real life." \
        "Our staging environment behaves differently." \
        "It was working before the Git merge." \
        "The NPM package got deprecated/deleted overnight." \
        "It's a DNS issue. It's always DNS."
    
    set -l random_idx (random 1 (count $excuses))
    set -l excuse $excuses[$random_idx]

    echo (set_color --bold red)"━━━ Programmer Excuse ━━━"(set_color normal)
    echo (set_color yellow)"  \"$excuse\""(set_color normal)
end

function bored --description "Suggest a productive or fun developer break activity"
    set -l activities \
        "Do 10 push-ups and stretch your wrists!" \
        "Drink a full glass of water. Hydrate!" \
        "Write a quick single-line script that automates something minor." \
        "Clean up 5 unused files or folders in your Downloads directory." \
        "Go read a random Wikipedia page of a computer science concept." \
        "Walk around for 2 minutes and let your eyes rest." \
        "Check out a new repo trending on GitHub." \
        "Clean your keyboard or wipe down your screen." \
        "Refactor one messy function in your current project." \
        "Review your shell history and create a new alias for your most common command."
        
    set -l random_idx (random 1 (count $activities))
    set -l act $activities[$random_idx]
    
    echo (set_color --bold green)"━━━ Developer Break Suggestion ━━━"(set_color normal)
    echo (set_color cyan)"  💡 $act"(set_color normal)
end

function open_app --description "Search and open the closest matching desktop application on Ubuntu"
    if test (count $argv) -eq 0
        echo "Usage: open_app <app-name>"
        echo "Example: open_app chrome"
        echo "Example: open_app spotify"
        return 1
    end

    set -l app_name (string join " " $argv | string lower)
    echo (set_color --bold blue)"━━━ Launching Application ━━━"(set_color normal)
    echo (set_color brblack)"  Searching for closest match to: '$app_name'..."(set_color normal)

    # Search paths for .desktop files
    set -l desktop_dirs /usr/share/applications ~/.local/share/applications /var/lib/snapd/desktop/applications /var/lib/flatpak/exports/share/applications
    set -l matches

    for dir in $desktop_dirs
        if test -d "$dir"
            # Find desktop files matching or containing the query
            set -l found (find "$dir" -name "*.desktop" 2>/dev/null)
            for f in $found
                set -l file_name (basename "$f" .desktop | string lower)
                set -l app_title (grep -m 1 "^Name=" "$f" | cut -d'=' -f2- | string lower)
                
                set -l match_all true
                for word in (string split " " "$app_name")
                    if not string match -q "*$word*" "$file_name"; and not string match -q "*$word*" "$app_title"
                        set match_all false
                        break
                    end
                end
                
                if test "$match_all" = "true"
                    set -a matches "$f"
                end
            end
        end
    end

    if test (count $matches) -eq 0
        # If no .desktop file matches, try to see if the command exists directly in PATH
        if command -v "$argv[1]" &>/dev/null
            echo (set_color green)"✓ Found executable in PATH: $argv[1]"(set_color normal)
            echo (set_color brblack)"  Launching in background..."(set_color normal)
            $argv &
            disown
            return 0
        end
        echo (set_color red)"✗ No matching application or command found for: '$app_name'"(set_color normal)
        return 1
    end

    # Remove duplicates safely
    set -l unique_matches
    for m in $matches
        if test -n "$m"; and not contains "$m" $unique_matches
            set -a unique_matches "$m"
        end
    end
    set matches $unique_matches

    # If we have matches, pick the best one
    set -l best_match ""
    
    # Priority: 
    # 1. Exact match in name
    for m in $matches
        set -l base (basename "$m" .desktop | string lower)
        if test "$base" = "$app_name"
            set best_match "$m"
            break
        end
    end

    # 2. First partial match
    if test -z "$best_match"
        set best_match $matches[1]
    end

    set -l display_name (grep -m 1 "^Name=" "$best_match" | cut -d'=' -f2-)
    set -l desktop_id (basename "$best_match")

    echo (set_color green)"✓ Found application: $display_name ($desktop_id)"(set_color normal)
    echo (set_color brblack)"  Launching in background..."(set_color normal)

    # Launch it using gtk-launch which is standard on Ubuntu
    if command -v gtk-launch &>/dev/null
        gtk-launch "$desktop_id" &>/dev/null &
        disown
    else
        # Fallback to parsing Exec line
        set -l exec_cmd (grep -m 1 "^Exec=" "$best_match" | cut -d'=' -f2- | sed 's/%[fFuU]//g' | string trim)
        eval "$exec_cmd &" &>/dev/null
        disown
    end
    return 0
end

function install_skill_deps --description "Install all system dependencies for agent skills"
    if not _arka_is_linux
        _arka_install_python_deps
        return $status
    end
    echo (set_color --bold blue)"━━━ Installing Skill Dependencies ━━━"(set_color normal)
    echo (set_color cyan)"This will install: curl, jq, xclip, git, playerctl, mpv, gnome-screenshot, scrot, speedtest-cli, iproute2, net-tools, imagemagick, lsb-release, bat, eza, qrencode, libnotify-bin"(set_color normal)
    
    sudo apt update
    sudo apt install -y curl jq xclip git playerctl mpv gnome-screenshot scrot speedtest-cli iproute2 net-tools imagemagick lsb-release bat eza qrencode libnotify-bin || sudo apt install -y batcat
    
    # Install playwright via pip if apt package missing
    python3 -m pip install playwright || pip3 install playwright
    
    # Install playwright browsers
    python3 -m playwright install chromium
    
    # Create flag file to mark setup as done
    mkdir -p $_ARKA_ROOT
    touch $_ARKA_ROOT/.skills_setup_done
    echo (set_color --bold green)"✓ Dependencies installed successfully."(set_color normal)
end

function _arka_install_python_deps --description "Install Python packages for Arka on macOS/non-Linux (internal)"
    set -l py (_arka_python)
    set -l pip (dirname $py)/pip
    if not test -x $pip
        set pip (dirname $py)/pip3
    end
    # First-run bootstrap only — skip when chat + TurboQuant are already in venv-arka.
    if $py -c "import agno, ddgs" 2>/dev/null
        if $py (_arka_py_script arka_turboquant_install.py) check 2>/dev/null
            mkdir -p $_ARKA_ROOT
            touch $_ARKA_ROOT/.skills_setup_done
            return 0
        end
    end
    echo (set_color --bold blue)"━━━ Installing Arka Python Dependencies ━━━"(set_color normal)
    if test -f (_arka_requirements)
        echo (set_color cyan)"Chat / web / LLM deps…"(set_color normal)
        $pip install -q -r (_arka_requirements)
    end
    if test -f $_ARKA_ROOT/arka_turboquant_requirements.txt
        echo (set_color cyan)"RAG numeric deps (numpy, scipy)…"(set_color normal)
        $pip install -q -r $_ARKA_ROOT/arka_turboquant_requirements.txt
    end
    echo (set_color cyan)"Neural TTS (edge-tts)…"(set_color normal)
    $pip install -q edge-tts
    echo (set_color cyan)"YouTube tools (yt-dlp)…"(set_color normal)
    $pip install -q yt-dlp
    echo (set_color cyan)"AssemblyAI STT (arka listen)…"(set_color normal)
    $pip install -q 'assemblyai>=0.64.0'
    echo (set_color cyan)"TurboQuant vector search…"(set_color normal)
    rag_setup --quiet
    mkdir -p $_ARKA_ROOT
    touch $_ARKA_ROOT/.skills_setup_done
    echo (set_color --bold green)"✓ Python dependencies installed."(set_color normal)
    echo (set_color brblack)"Optional: pip install playwright && playwright install chromium  (browse_web)"(set_color normal)
end

function browse_web --description "Automate web browser with natural language"
    if test (count $argv) -eq 0
        echo "Usage: browse_web <instruction>"
        return 1
    end
    
    set -l model_name "Local/Cloud LLM"
    if test -n "$GEMINI_API_KEY"
        set model_name "Gemini 2.0 Flash"
    else if test -n "$GROQ_API_KEY"
        set model_name "Llama 3.3 70B (Groq)"
    else if test -n "$VLLM_API_URL"
        set model_name "vLLM Cloud"
    else
        set model_name "Ollama Local Fallback"
    end

    set -l instruction (string join " " $argv)
    echo (set_color cyan)"🌐 Browsing via $model_name: $instruction"(set_color normal)
    
    python3 -c "
import sys, os, json, requests, shutil, re
from playwright.sync_api import sync_playwright

instruction = sys.argv[1]
gemini_key = os.getenv('GEMINI_API_KEY')
groq_key = os.getenv('GROQ_API_KEY')

is_dom_request = any(x in instruction.lower() for x in ['dom', 'html', 'source', 'page source'])

def clean_code(text):
    match = re.search(r'```(?:python|py)?\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip().replace('```python', '').replace('```', '').strip()

def get_code(prompt):
    if is_dom_request:
        sys_prompt = 'You are a Playwright expert. Generate ONLY Python code to load the page and save its HTML/DOM. Start with a \"page\" object already initialized. Navigate using page.goto() (use wait_until=\"networkidle\" if needed) and then write the DOM to a file \"dom.html\": with open(\"dom.html\", \"w\") as f: f.write(page.content()). Print \"DOM saved to dom.html\". Respond with ONLY CODE, no markdown.'
    else:
        sys_prompt = 'You are a Playwright expert. Generate ONLY Python code to execute the instruction. Start with a \"page\" object already initialized. Use page.goto(), page.click(), page.fill(), page.keyboard.press(\"Enter\"), etc. Respond with ONLY CODE, no markdown, no comments.'
    
    # 1. Try Gemini
    if gemini_key:
        try:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}'
            resp = requests.post(url, json={'contents': [{'parts': [{'text': prompt}]}], 'system_instruction': {'parts': [{'text': sys_prompt}]}}, timeout=10)
            return clean_code(resp.json()['candidates'][0]['content']['parts'][0]['text'])
        except: pass
        
    # 2. Try Groq
    if groq_key:
        try:
            resp = requests.post('https://api.groq.com/openai/v1/chat/completions', 
                headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
                json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role': 'system', 'content': sys_prompt}, {'role': 'user', 'content': prompt}]}, timeout=10)
            return clean_code(resp.json()['choices'][0]['message']['content'])
        except: pass

    # 3. Try vLLM
    vllm_url = os.getenv('VLLM_API_URL') or (f\"http://{os.getenv('VLLM_HOST')}\" if os.getenv('VLLM_HOST') else \"http://localhost:8000\")
    vllm_key = os.getenv('VLLM_API_KEY')
    if vllm_url:
        try:
            headers = {'Content-Type': 'application/json'}
            if vllm_key:
                headers['Authorization'] = f'Bearer {vllm_key}'
            resp = requests.post(f\"{vllm_url}/v1/chat/completions\", headers=headers,
                json={'model': 'default', 'messages': [{'role': 'system', 'content': sys_prompt}, {'role': 'user', 'content': prompt}]}, timeout=10)
            if resp.status_code == 200:
                return clean_code(resp.json()['choices'][0]['message']['content'])
        except: pass

    # 4. Try local Ollama fallback
    ollama_host = os.getenv('OLLAMA_HOST') or \"127.0.0.1:11434\"
    ollama_url = f\"http://{ollama_host}/api/chat\" if not ollama_host.startswith('http') else f\"{ollama_host}/api/chat\"
    ollama_key = os.getenv('OLLAMA_API_KEY')
    try:
        headers = {'Content-Type': 'application/json'}
        if ollama_key:
            headers['Authorization'] = f'Bearer {ollama_key}'
        
        tags_url = ollama_url.replace('/api/chat', '/api/tags')
        tags_resp = requests.get(tags_url, headers=headers, timeout=2)
        local_model = \"llama3.2:1b\"
        if tags_resp.status_code == 200:
            models = [m['name'] for m in tags_resp.json().get('models', []) if 'cloud' not in m['name'].lower()]
            if models:
                local_model = models[0]
        
        resp = requests.post(ollama_url, headers=headers,
            json={'model': local_model, 'messages': [{'role': 'system', 'content': sys_prompt}, {'role': 'user', 'content': prompt}], 'stream': False}, timeout=60)
        if resp.status_code == 200:
            return clean_code(resp.json()['message']['content'])
    except Exception as e:
        print(\"Ollama error: \" + str(e))

    return None

def run():
    code = get_code(instruction)
    if not code:
        print('Error: Could not generate automation code. Check your API keys and connection.')
        return

    user_data_dir = os.path.expanduser('~/.config/BraveSoftware/Brave-Browser')
    brave_path = '/usr/bin/brave-browser'
    lock_file = os.path.join(user_data_dir, 'SingletonLock')

    use_persistent = True
    if not is_dom_request and os.path.exists(lock_file):
        print('\n' + '!' * 40)
        print('WHY THIS HAPPENS: Brave uses a \"SingletonLock\" to prevent data corruption.')
        print('Only one instance can use your profile at a time.')
        print('!' * 40 + '\n')
        print('Brave is currently open. Choose an option:')
        print('1. Run in Isolated Mode (Fresh profile, keeps Brave open)')
        print('2. Cancel and close Brave manually')
        choice = input('Choice (1/2): ')
        if choice == '1':
            use_persistent = False
        else:
            return

    with sync_playwright() as p:
        try:
            if is_dom_request:
                # DOM request - run headless with standard Chromium for performance and sandboxing
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
            elif use_persistent:
                context = p.chromium.launch_persistent_context(user_data_dir, executable_path=brave_path, headless=False, args=['--profile-directory=Default'])
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = p.chromium.launch(executable_path=brave_path, headless=False)
                page = browser.new_page()

            print(\"--- GENERATED CODE ---\")
            print(code)
            print(\"----------------------\")
            exec(code)
            if not is_dom_request:
                input('\nAction completed. Press Enter to close...')
        except Exception as e:
            print(f'Runtime Error: {e}')
        finally:
            if 'context' in locals(): context.close()
            if 'browser' in locals(): browser.close()

if __name__ == '__main__':
    run()
" "$instruction"
end

function create_skill --description "Dynamically create a new Fish shell skill using LLMs"
    if test (count $argv) -lt 2
        echo "Usage: create_skill <name> <description_and_behavior>"
        echo "Example: create_skill calculate_bmi \"takes weight in kg and height in cm, prints the BMI\""
        return 1
    end

    set -l skill_name $argv[1]
    set -l skill_desc (string join " " $argv[2..-1])

    if test -z "$GEMINI_API_KEY" -a -z "$GROQ_API_KEY"
        echo (set_color red)"Error: GEMINI_API_KEY or GROQ_API_KEY is not set."(set_color normal)
        return 1
    end

    echo (set_color cyan)"🤖 Generating skill '$skill_name'..."(set_color normal)

    set -l system_prompt "You are a Fish Shell expert. Generate a complete, safe, and beautifully formatted Fish function called '$skill_name'.
The function should do: $skill_desc
Include a --description on the function.
Add colors and a nice banner or icons for output so it feels premium and looks amazing in the terminal.
Respond with ONLY the raw Fish shell function code. No markdown, no backticks, no explanations."

    set -l user_prompt "Create Fish function for skill \"$skill_name\" described as: $skill_desc"
    set -l code (_agent_clean_llm_output (_agent_llm_complete "$system_prompt" "$user_prompt" 0.2 agent))

    if test -z "$code"
        echo (set_color red)"✗ Failed to generate skill code. Check API keys and connection."(set_color normal)
        return 1
    end

    echo (set_color green)"✨ Generated Fish Function:"(set_color normal)
    echo (set_color yellow)"$code"(set_color normal)
    echo ""
    echo -n (set_color --bold cyan)"Do you want to install this skill? (y/n): "(set_color normal)
    read -l confirm
    if not string match -qi "y*" "$confirm"
        echo "Aborted."
        return 1
    end

    # Run Python script to modify config.fish safely
    set -lx SKILL_CODE "$code"
    python3 -c "
import sys, os

config_path = os.path.expanduser('$_ARKA_ROOT/config.fish')
skill_name = sys.argv[1]
skill_code = os.environ.get('SKILL_CODE')

if not skill_code:
    print('Error: SKILL_CODE env var is empty.')
    sys.exit(1)

if not os.path.exists(config_path):
    print(f'Error: config.fish not found at {config_path}')
    sys.exit(1)

with open(config_path, 'r') as f:
    content = f.read()

# 1. Add the function code before NemoClaw PATH setup
insert_marker = '# ' + 'NemoClaw PATH'
if insert_marker in content:
    parts = content.split(insert_marker, 1)
    new_content = parts[0] + skill_code + '\n\n' + insert_marker + parts[1]
else:
    new_content = content + '\n\n' + skill_code + '\n'

# 2. Register skill in agent available_skills and _agent_available_skills
import re

def _append_skill_line(text, prefix_pattern, skill):
    match = re.search(prefix_pattern, text)
    if not match:
        return text
    skills_list = match.group(2).split()
    if skill in skills_list:
        return text
    skills_list.append(skill)
    replacement = match.group(1) + ' '.join(skills_list)
    return text[:match.start()] + replacement + text[match.end():]

new_content = _append_skill_line(new_content, r'(set\s+-l\s+available_skills\s+)(.+)', skill_name)
new_content = _append_skill_line(new_content, r"(printf '%s\\n' )(.+ app_usage)", skill_name)
if skill_name not in new_content:
    print('Warning: could not find available_skills list in config.fish to register the skill automatically.')

with open(config_path, 'w') as f:
    f.write(new_content)

print('Skill written successfully to config.fish!')
" "$skill_name"

    if test $status -eq 0
        source $_ARKA_ROOT/config.fish
        echo (set_color green)"✓ Skill '$skill_name' is now active and registered!"(set_color normal)
    end
end

# --- Agent routing: skill vs shell vs LLM vs codegen ---
function _agent_matches_graphics_driver --description "True if text is an Intel/GPU driver warning paste"
    set -l clean (string lower "$argv[1]")
    string match -qr '(?i)(intel|graphics|gpu).*(driver|issue|problem)|driver has known|recommended:\s*[0-9]|recommended driver|installed version of the.*(graphics|intel).*driver' "$clean"
    or string match -qr '(?i)(^|\s)fix\b.*(driver|graphics|gpu|intel)' "$clean"
end

function _agent_route_graphics_driver --description "Echo fix_graphics_driver line for NL text (internal)"
    set -l text $argv[1]
    mkdir -p "$HOME/.cache/fish-agent"
    printf '%s' "$text" > "$HOME/.cache/fish-agent/last_nl.txt"
    set -l drv_url (_extract_first_url "$text")
    if test -n "$drv_url"
        echo "fix_graphics_driver $drv_url"
    else
        echo "fix_graphics_driver"
    end
end

function _extract_first_url --description "First http(s) URL in text, or empty (internal)"
    set -l m (string match -r '(https?://\S+)' "$argv[1]")
    if test (count $m) -ge 2
        echo (string trim -c '.,);]>' -- $m[2])
    end
end

function _install_target_is_package_file --description "True if install target is a local package file (internal)"
    set -l target (string trim -c "'\"" -- "$argv[1]")
    test -z "$target"; and return 1
    if string match -qr '\.(deb|rpm|AppImage|appimage|tar\.gz|tgz|zip)$' -- "$target"
        return 0
    end
    if test -f "$target"
        return 0
    end
    for dir in "$PWD" "$HOME/Downloads"
        if test -f "$dir/$target"
            return 0
        end
    end
    return 1
end

function _agent_parse_install_app_name --description "Extract app name from install NL (internal)"
    set -l cmd $argv[1]
    set -l brew_m (string match -r -i '^(?:brew|homebrew)\s+install\s+(.+)$' "$cmd")
    if test (count $brew_m) -ge 2
        echo (string trim -- "$brew_m[2]")
        return
    end
    set -l app (string replace -r -i '^(?:please\s+)?(?:install|get|setup)\s+(?:the\s+)?' '' "$cmd")
    set app (string replace -r -i '\s+(?:from|via|using|with|on)\s+(?:flatpak|flathub|snap|snapcraft|apt|apt-get|dpkg|brew|homebrew).*$' '' "$app")
    set app (string replace -r -i '\s+(?:with|via|using)\s+apt(?:-get)?\s*$' '' "$app")
    set app (string replace -r -i '\s+(?:with|via|using)\s+brew(?:\s|$)' '' "$app")
    set app (string replace -r -i '\s+(?:app|package)\s*$' '' "$app")
    echo (string trim -- "$app")
end

function _agent_parse_password_name --description "Extract vault label from NL password request (internal)"
    set -l cmd (string trim -- "$argv[1]")
    set -l name ""
    set -l m (string match -r '(?i)(?:for|as|named|to)\s+(.+)$' "$cmd")
    if test (count $m) -ge 2
        set name (string trim -- "$m[2]")
    end
    if test -z "$name"
        set m (string match -r '(?i)password\s+for\s+(.+)$' "$cmd")
        if test (count $m) -ge 2
            set name (string trim -- "$m[2]")
        end
    end
    if test -z "$name"
        return 1
    end
    # Optional trailing length: "wifi 24" -> name wifi
    set name (string replace -r '(\s+)([0-9]+)$' '' "$name")
    echo (string trim -- "$name")
end

function _agent_is_python_pip_package --description "True if name looks like a PyPI package (internal)"
    set -l first (string lower (string trim -- "$argv[1]"))
    string match -qr '^(torch|pytorch|torchvision|torchaudio|numpy|pandas|scipy|scikit-learn|sklearn|tensorflow|keras|transformers|django|flask|fastapi|requests|pytest|httpx|uvicorn|pydantic|matplotlib|seaborn|opencv-python|pillow|ipython|jupyter|notebook|streamlit|gradio|accelerate|bitsandbytes|peft|tokenizers|diffusers|xgboost|lightgbm|catboost|spacy|nltk|sympy|statsmodels|plotly|polars|pyarrow|aiohttp|beautifulsoup4|lxml|sqlalchemy|alembic|redis|celery|boto3|openai|anthropic|langchain|chromadb|faiss-cpu|faiss-gpu|huggingface-hub|sentencepiece|xformers)$' "$first"
end

function _agent_is_python_pip_install --description "True if install request is for a Python/PyPI package (internal)"
    set -l clean (string lower "$argv[1]")
    set -l raw (_agent_parse_install_app_name "$argv[1]")

    if string match -qr '(?i)(with\s+uv|via\s+uv|uv\s+pip|\bpip\s+install|python\s+package)' "$clean"
        return 0
    end
    if string match -qr '(?i)\bfor\s+(cpu|gpu)\b|\bwith\s+cuda\b' "$clean"
        and string match -qr '(?i)^(install|get|setup)\s+' "$clean"
        return 0
    end
    set -l base (string replace -r -i '\s+(for\s+)?(cpu|gpu|cuda).*$' '' "$raw" | string trim)
    for p in (string split " " -- "$base")
        if _agent_is_python_pip_package "$p"
            return 0
        end
    end
    return 1
end

function _agent_parse_install_uv --description "NL install -> install_uv command line (internal)"
    set -l cmd $argv[1]
    set -l raw (_agent_parse_install_app_name "$cmd")
    set -l flag ""
    set -l body $raw

    if string match -qr '(?i)\s+for\s+cpu\s*$' "$body"
        set flag --cpu
        set body (string replace -r -i '\s+for\s+cpu\s*$' '' "$body" | string trim)
    else if string match -qr '(?i)(\s+for\s+gpu|\s+with\s+cuda|\s+cuda)\s*$' "$body"
        set flag --cuda
        set body (string replace -r -i '(\s+for\s+gpu|\s+with\s+cuda|\s+cuda)\s*$' '' "$body" | string trim)
    end

    set body (string replace -r -i '\s+(with|via|using)\s+(uv|pip).*$' '' "$body" | string trim)
    set body (string replace -r -i '^python\s+package\s+' '' "$body" | string trim)

    set -l parts
    for p in (string split " " -- "$body")
        if test (string lower "$p") = pytorch
            set p torch
        end
        set -a parts $p
    end

    if test -n "$flag"
        echo install_uv $flag (string join " " $parts)
    else
        echo install_uv (string join " " $parts)
    end
end

function _agent_system_context --description "Brief hardware/OS summary for advisory AI answers (internal)"
    set -l cpu (_arka_sys_cpu)
    set -l cores ""
    if _arka_is_macos
        set cores (sysctl -n hw.ncpu 2>/dev/null)
    else
        set cores (grep -c '^processor' /proc/cpuinfo 2>/dev/null)
    end
    set -l ram (_arka_sys_ram)
    set -l disk (df -h / 2>/dev/null | awk 'NR==2 {print $2 " total, " $3 " used (" $5 ")"}')
    set -l os (_arka_sys_os)
    set -l gpu (_arka_sys_gpu)
    printf '%s\n' "OS: $os" "CPU: $cpu ($cores cores)" "RAM: $ram" "Disk (/): $disk" "GPU: $gpu"
end

function _agent_normalize_essay_topic --description "Strip write-essay prefixes for topic lookup (internal)"
    set -l q (string trim -- "$argv[1]")
    set q (string replace -r -i '^(write|draft|compose)\s+(an?\s+)?(short\s+|brief\s+)?(essay|article|report|summary|paragraph|piece)\s+(about|on|regarding)\s+' '' "$q")
    set q (string replace -r -i '^(write|draft|compose)\s+(about|on|regarding)\s+' '' "$q")
    set q (string replace -r -i '^please\s+' '' "$q")
    echo (string trim -- "$q")
end

function _agent_parse_media_path --description "Extract media file path from NL request (internal)"
    set -l exts 'mp3|mp4|m4a|wav|ogg|opus|webm|mkv|mov|aac|flac'
    set -l qm (string match -r "(?i)['\"]([^'\"]+\\.(?:$exts))['\"]" "$argv[1]")
    if test (count $qm) -ge 2
        echo $qm[2]
        return
    end
    set -l abs (string match -r -a "(?i)(/[^\n\"]+\\.(?:$exts))" "$argv[1]")
    if test (count $abs) -ge 1
        echo $abs[-1]
        return
    end
    set -l m (string match -r "(?i)([~./][^\s'\"]+\\.(?:$exts))\\b" "$argv[1]")
    if test (count $m) -ge 2
        echo $m[2]
        return
    end
    set -l m2 (string match -r "(?i)([^\s'\"]+\\.(?:$exts))\\b" "$argv[1]")
    if test (count $m2) -ge 2
        echo $m2[2]
    end
end

function _agent_is_file_size_find --description "True if NL is find-files-by-size (internal)"
    set -l clean (string lower "$argv[1]")
    set -l has_subject 0
    if string match -qr '(?i)(find|search|list|show)\s+.*\bfiles?\b' "$clean"
        set has_subject 1
    else if string match -qr '(?i)(find|search|list|show)\s+.*\bdownloads?\b' "$clean"
        set has_subject 1
    else if string match -qr '(?i)\bfiles?\b.*\b(downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b' "$clean"
        set has_subject 1
    else if string match -qr '(?i)\bdownloads?\b.*\b(range\s+of|between|from|\d+\s*(kb|mb|gb))\b' "$clean"
        set has_subject 1
    else if string match -qr '(?i)\bfiles?\s+in\s+(?:my\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b' "$clean"
        set has_subject 1
    else if string match -qr '(?i)\blarge\s+files?\s+in\s+(?:my\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b' "$clean"
        set has_subject 1
    else if string match -qr '(?i)\b(big|large|huge)\s+files?\b.*\b(downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b' "$clean"
        set has_subject 1
    end
    test $has_subject -eq 0; and return 1
    if string match -qr '(?i)(less|more|greater|larger|smaller|lesser|under|over|above|below|bigger)(\s+than)?|\b(?:range\s+of|between|from)\b|\d+\s*(kb|mb|gb)\b\s+(?:to|and|-)\s+\d+\s*(kb|mb|gb)\b|\d+\s*(kb|mb|gb)\b' "$clean"
        return 0
    end
    string match -qr '(?i)\b(large|big|huge)\s+files?\b' "$clean"
end

function _agent_route_file_size_find --description "Map NL to find_files_by_size (internal)"
    echo "find_files_by_size $argv[1]"
end

function _agent_route_media --description "Map media transcribe NL to media_transcript command (internal)"
    set -l cmd "$argv[1]"
    set -l path (_agent_parse_media_path "$cmd")
    test -z "$path"; and return 1
    if string match -qr '(?i)\b(summarize|summary|tldr|overview|brief)\b' "$cmd"
        set -l tail (string replace "$path" '' "$cmd" | string replace -r -i '^\s*(?:hey\s+)?(?:arka|agent)?[,:\s]*' '' | string trim)
        set tail (string replace -r -i '^(?:please\s+)?(?:summarize|summary|tldr|overview|brief)\s*' '' "$tail" | string trim)
        if test -n "$tail"
            echo "arka summarize $tail '$path'"
        else
            echo "arka summarize '$path'"
        end
    else
        echo "media_transcript '$path'"
    end
end

function _agent_is_pdf_ingest_request --description "True if user wants to ingest/upload a document (internal)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)(ingest|upload|add|index)\s+(my\s+)?(the\s+)?(pdf|document|doc|file)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)(ingest|upload|add|index)\s+.*\.(pdf|docx|doc|pptx|xlsx|xls|txt|md|csv|html|htm|py|json|yaml|yml|fish|sh|sql|eml|rtf|xml)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)(pdf|document|file)\s+(to|into)\s+(private\s?gpt|my\s+(docs?|documents?|library|pdfs?|files?))' "$clean"
        return 0
    end
    if string match -qr '(?i)^(load|import)\s+(a\s+)?(pdf|document|file)\b' "$clean"
        return 0
    end
    return 1
end

function _agent_is_codebase_ingest_request --description "True if user wants to index a codebase/repo (internal)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)(index|ingest|add)\s+(my\s+)?(the\s+)?(codebase|code base|repo|repository|project)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)(codebase|repo|repository).*(index|ingest|for\s+questions?)' "$clean"
        return 0
    end
    if string match -qr '(?i)index\s+(this|my|the)\s+(repo|project|codebase|code)\b' "$clean"
        return 0
    end
    return 1
end

function _agent_parse_codebase_path --description "Extract project path from codebase ingest NL (internal)"
    set -l m (string match -r "(?i)(['\"]?([~/][^\s'\"]+)['\"]?)" "$argv[1]")
    if test (count $m) -ge 3
        echo $m[3]
        return
    end
    set -l m2 (string match -r '(/[^\s'\'']+)' "$argv[1]")
    if test (count $m2) -ge 2
        echo $m2[2]
    end
end

function _agent_is_playlist_summarize_request --description "True if user wants playlist/series digest (internal)"
    string match -qr '(?i)(summarize|summary|digest|overview).*(playlist|series|all episodes|all videos)|playlist.*(summarize|summary|digest)' "$argv[1]"
end

function _agent_is_folder_summarize_request --description "True if user wants folder media digest (internal)"
    string match -qr '(?i)(summarize|summary|digest).*(folder|directory)|summarize\s+(everything|all)\s+in\s+(the\s+)?(folder|directory)' "$argv[1]"
end

function _agent_is_youtube_research_request --description "True if user wants YouTube search + transcript research (internal)"
    set -l cmd $argv[1]
    string match -qr '(?i)(research|search|summarize|summary|digest).*(on\s+)?youtube|youtube.*(research|search|summarize)|summarize.*youtube.*(videos?|results?|about)|yt\s+research' "$cmd"
    or string match -qr '(?i)(analyze|analyse|study|review)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(youtube\s+)?videos?' "$cmd"
    or string match -qr '(?i)\b(\d+|one|two|three|four|five)\s+(youtube\s+)?videos?\s+(on|about|for|of)\b' "$cmd"
end

function _agent_is_video_search_request --description "True if user wants YouTube video links (not full research digest)"
    if _agent_is_youtube_research_request "$argv[1]"
        return 1
    end
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)\b(videos?\s+(?:to\s+learn|for\s+learning|on|about|for|to)|video\s+tutorials?|tutorial\s+videos?|watch\s+videos?|find\s+videos?|show\s+(?:me\s+)?videos?)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\blearn\s+\S+(\s+\S+){0,4}\s+(?:from|with)\s+videos?\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(youtube\s+)?videos?\s+(?:to|for)\s+(learn|study|understand)\b' "$clean"
        return 0
    end
    return 1
end

function _agent_parse_video_search_query --description "Extract YouTube search query from NL video request (internal)"
    set -l q (string trim -- "$argv[1]")
    set q (string replace -r -i '^(?:please\s+)?(?:find|show|get|give me|search for|search)\s+' '' "$q")
    set q (string replace -r -i '^(?:\d+\s+)?(?:youtube\s+)?videos?\s+(?:to\s+learn|for\s+learning|on|about|for|to)\s+' '' "$q")
    set q (string replace -r -i '^(?:video\s+)?tutorials?\s+(?:to\s+learn|for|on|about|to)\s+' '' "$q")
    set q (string replace -r -i '^watch\s+videos?\s+(?:to\s+learn|on|about|for|to)\s+' '' "$q")
    set q (string replace -r -i '\s+(?:from|with|on)\s+youtube\s*$' '' "$q")
    set q (string replace -r -i '\s+videos?\s*$' '' "$q")
    set q (string trim -- "$q")
    if test -z "$q"
        echo ""
        return
    end
    if string match -qr '(?i)\btutorial\b' "$q"
        echo $q
    else
        echo "$q tutorial"
    end
end

function _agent_build_video_search_cmd --description "Build find_videos skill invocation (internal)"
    set -l q (_agent_parse_video_search_query "$argv[1]")
    if test -z "$q"
        echo "find_videos"
    else
        echo "find_videos $q"
    end
end

function _agent_is_translate_request --description "True if user wants text translated to another language"
    set -l clean (string lower (string trim -- "$argv[1]"))
    if string match -qr '(?i)^translate\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\btranslate\s+.+\s+to\s+\w' "$clean"
        return 0
    end
    if string match -qr '(?i)^(what|how|why|when|where|who|is|are|can|could|does|do)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)\s+to\s+(chinese|mandarin|cantonese|spanish|french|german|japanese|korean|thai|hindi|bengali|tamil|telugu|arabic|russian|portuguese|italian|vietnamese|urdu|marathi|gujarati|punjabi|dutch|polish|turkish|greek|hebrew|nepali|swedish|norwegian|danish|finnish|czech|hungarian|romanian|ukrainian|persian|farsi|indonesian|filipino|tagalog|malay|kannada|malayalam)\s*$' "$clean"
        return 0
    end
    return 1
end

function _agent_parse_translate_nl --description "Parse NL translate → lang\\ttext (internal)"
    set -l cmd (string trim -- "$argv[1]")

    set -l m (string match -r '(?i)^translate\s+(.+?)\s+to\s+(.+)\s*$' -- "$cmd")
    if test (count $m) -ge 3
        printf "%s\t%s\n" $m[3] $m[2]
        return
    end

    set -l m (string match -r '(?i)^translate\s+to\s+(\S+)\s+(.+)$' -- "$cmd")
    if test (count $m) -ge 3
        printf "%s\t%s\n" $m[2] $m[3]
        return
    end

    set -l langs chinese mandarin cantonese spanish french german japanese korean thai vietnamese italian portuguese russian arabic hindi bengali tamil telugu urdu marathi gujarati punjabi kannada malay dutch polish turkish greek hebrew nepali swedish norwegian danish finnish czech hungarian romanian ukrainian persian farsi indonesian filipino tagalog malayalam
    for lang in $langs
        set -l m (string match -r -i "(.+?)\\s+to\\s+$lang\$" -- "$cmd")
        if test (count $m) -ge 2
            set -l text (string trim -- $m[2])
            test -n "$text"; and printf "%s\t%s\n" $lang $text; and return
        end
    end
    echo ""
end

function _agent_build_translate_cmd --description "Build translate skill invocation (internal)"
    set -l parsed (_agent_parse_translate_nl "$argv[1]")
    if test -z "$parsed"
        echo "translate"
        return
    end
    set -l parts (string split \t "$parsed" --max 2)
    echo "translate $parts[1] $parts[2]"
end

function _agent_speak_lang_for_target --description "Best-effort TTS locale for translation target (internal)"
    set -l lang (string lower (string trim -- "$argv[1]"))
    switch $lang
        case chinese mandarin
            echo zh-CN
        case cantonese
            echo zh-HK
        case japanese
            echo ja-JP
        case korean
            echo ko-KR
        case spanish
            echo es-ES
        case french
            echo fr-FR
        case german
            echo de-DE
        case hindi hi
            echo hi-IN
        case bengali bn
            echo bn-IN
        case tamil ta
            echo ta-IN
        case telugu te
            echo te-IN
        case arabic
            echo ar
        case russian
            echo ru-RU
        case '*'
            echo ""
    end
end

function _agent_is_survival_lang_request --description "True if user wants travel survival phrases in another language"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)\bsurvive_lang\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(survival phrases|travel phrases|basic phrases|tourist phrases|phrases to survive)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\bteach me (?:how to )?survive\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\bhow to (?:get by|survive) in\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\bsurvive in\b' "$clean"
        return 0
    end
    return 1
end

function _agent_parse_survival_lang_target --description "Extract target language from survival phrase request (internal)"
    set -l clean (string lower "$argv[1]")
    set -l langs afrikaans arabic bengali burmese chinese cantonese mandarin czech danish dutch english filipino tagalog finnish french german greek gujarati hebrew hindi hungarian indonesian italian japanese kannada korean malay marathi nepali norwegian persian farsi polish portuguese punjabi romanian russian spanish swahili swedish tamil telugu thai turkish ukrainian urdu vietnamese
    for lang in $langs
        if string match -qr "(?:in|for|to|into)\s+$lang\\b" "$clean"
            echo $lang
            return
        end
        if string match -qr "\b$lang\s+(?:phrases|survival|language|for travel)\b" "$clean"
            echo $lang
            return
        end
        if string match -qr "\bsurvive_lang\s+$lang\\b" "$clean"
            echo $lang
            return
        end
    end
    for lang in $langs
        if string match -qr "\b$lang\\b" "$clean"
            echo $lang
            return
        end
    end
    echo ""
end

function _agent_build_survival_lang_cmd --description "Build survive_lang skill invocation (internal)"
    set -l lang (_agent_parse_survival_lang_target "$argv[1]")
    if test -z "$lang"
        echo "survive_lang"
    else
        echo "survive_lang $lang"
    end
end

function _agent_is_pr_check_request --description "True if user wants PR diff / CI / babysit (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    if string match -qr '(?i)^pr_check\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(pr_check|pr check)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(babysit|baby.?sit)\b.*\b(pr|pull request)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(pr|pull request)\b.*\b(babysit|merge.?ready|merge ready)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(why did (the )?ci fail|explain (the )?ci|ci failed|github actions failed|workflow failed|failed checks)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(pr diff|diff vs main|what changed vs|my changes vs)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(pr checks|ci status|github actions status)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(summarize (my )?(pr|changes|diff)|pr summary|summary of (my )?changes)\b' "$clean"
        return 0
    end
    return 1
end

function _agent_route_pr_check --description "Build pr_check invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_pr_check.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_github_repo_request --description "True if user wants GitHub repo activity (commits/files) (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_github_repo.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_is_competitions_request --description "True if user wants hackathon/competition search (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_competitions.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_competitions --description "Build competitions invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_competitions.py) route "$argv[1]" 2>/dev/null | string trim)
    echo $route
end

function _agent_is_bookmarks_request --description "True if user wants bookmark manager (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_bookmarks.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_bookmarks --description "Build bookmarks invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_bookmarks.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_repo_health_request --description "True if user wants repo health checks (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_repo_health.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_repo_health --description "Build repo_health invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_repo_health.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_generate_data_request --description "True if user wants sample data generation (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_generate_data.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_generate_data --description "Build generate_data invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_generate_data.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_data_ask_request --description "True if user wants data file Q&A (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_data_ask.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_data_ask --description "Build data_ask invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_data_ask.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_docker_status_request --description "True if user wants docker status/logs (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_docker_status.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_docker_status --description "Build docker_status invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_docker_status.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_clipboard_history_request --description "True if user wants clipboard history (internal)"
    set -l cmd (string lower (string trim -- "$argv[1]"))
    test -z "$cmd"; and return 1
    if string match -qr '(?i)\b(clipboard\s+history|clip\s+history|clipboard\s+manager|saved?\s+clipboard|paste\s+from\s+history|clipboard\s+entries)\b' "$cmd"
        return 0
    end
    if string match -qr '(?i)\b(?:save|store|remember)\s+(?:this\s+)?(?:clipboard|clip)\b' "$cmd"
        return 0
    end
    if string match -qr '(?i)\b(?:list|show)\s+(?:clipboard\s+)?history\b' "$cmd"
        return 0
    end
    if string match -qr '(?i)\b(?:paste|restore)\s+(?:clipboard\s+)?(?:entry|item)\b' "$cmd"
        return 0
    end
    if string match -qr '(?i)\b(?:clear|wipe)\s+clipboard\s+history\b' "$cmd"
        return 0
    end
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_clipboard_history.py) route "$argv[1]" 2>/dev/null | string trim)
    test -n "$route"
end

function _agent_route_clipboard_history --description "Build clipboard_history invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_clipboard_history.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_is_life_sciences_request --description "True if user wants life sciences plugin catalog (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    test -z "$clean"; and return 1
    if string match -qr '(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(install|setup)\s+(pubmed|single[- ]cell|nextflow|scvi)\b' "$clean"
        return 0
    end
    string match -qr '(?i)\blife[- ]sciences?\b' "$clean"
end

function _agent_route_life_sciences --description "Build life_sciences invocation from NL (internal)"
    set -l cmd "$argv[1]"
    set -l ls_m (string match -r '(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)(?:\s+(\S+))?' -- "$cmd")
    if test (count $ls_m) -ge 3
        set -l ls_extra ""
        if test (count $ls_m) -ge 4
            set ls_extra $ls_m[4]
        end
        echo "life_sciences $ls_m[3] $ls_extra"
        return
    end
    set -l plug_m (string match -r '(?i)\b(?:install|setup)\s+(pubmed|single[- ]cell(?:[- ]rna[- ]qc)?|nextflow(?:[- ]development)?|scvi(?:[- ]tools)?)\b' -- "$cmd")
    if test (count $plug_m) -ge 2
        set -l plug (string lower -- $plug_m[2])
        switch $plug
            case "single-cell" "single cell" "single-cell-rna-qc" "single cell rna qc"
                set plug "single-cell-rna-qc"
            case "nextflow" "nextflow-development"
                set plug "nextflow-development"
            case "scvi" "scvi-tools"
                set plug "scvi-tools"
        end
        echo "life_sciences install $plug"
        return
    end
    echo "life_sciences list"
end

function _agent_is_gemini_cli_request --description "True if user wants Google Gemini CLI (internal)"
    set -l py (_arka_python)
    $py -c "
from arka.integrations.gemini_cli import route_command
import sys
sys.exit(0 if route_command(sys.argv[1]) else 1)
" "$argv[1]" 2>/dev/null
end

function _agent_build_gemini_cli_cmd --description "Build gemini_cli args from NL (internal)"
    set -l py (_arka_python)
    $py -c "
from arka.integrations.gemini_cli import route_command
import sys
route = route_command(sys.argv[1])
if route:
    print(route)
" "$argv[1]" 2>/dev/null
end

function _agent_route_github_repo --description "Build github_repo invocation from NL (internal)"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_github_repo.py) route "$argv[1]" 2>/dev/null | string trim)
    echo "$route"
end

function _agent_youtube_limit_digit --description "Convert limit token to number for --limit (internal)"
    set -l tok (string lower (string trim -- "$argv[1]"))
    switch $tok
        case one a an; echo 1
        case two; echo 2
        case three; echo 3
        case four; echo 4
        case five; echo 5
        case six; echo 6
        case seven; echo 7
        case eight; echo 8
        case nine; echo 9
        case ten; echo 10
        case eleven; echo 11
        case twelve; echo 12
        case '*'
            if string match -qr '^[0-9]+$' -- $tok
                echo $tok
            end
    end
end

function _agent_parse_youtube_research_limit --description "Extract video count from YouTube research NL (internal)"
    set -l cmd $argv[1]
    set -l m (string match -r '(?i)(?:analyze|analyse|research|summarize|study|review)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+videos?' "$cmd")
    if test (count $m) -ge 2
        _agent_youtube_limit_digit $m[2]
        return
    end
    set -l m2 (string match -r '(?i)\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+videos?\s+(?:on|about|for|of)\b' "$cmd")
    if test (count $m2) -ge 2
        _agent_youtube_limit_digit $m2[2]
    end
end

function _agent_build_youtube_research_cmd --description "Build youtube_research skill invocation (internal)"
    set -l cmd $argv[1]
    set -l yq (_agent_parse_youtube_research_query "$cmd")
    set -l ylimit (_agent_parse_youtube_research_limit "$cmd")
    if test -z "$yq"
        echo "youtube_research"
        return
    end
    if test -n "$ylimit"
        echo "youtube_research $yq --limit $ylimit --index"
    else
        echo "youtube_research $yq --index"
    end
end

function _agent_parse_youtube_research_query --description "Extract search query from YouTube research NL (internal)"
    set -l cmd (string trim -- "$argv[1]")
    set -l q $cmd
    set q (string replace -r -i '^.*?\b(?:analyze|analyse|study|review|research|summarize)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:youtube\s+)?videos?\s+(?:on|about|for|of)?\s*' '' "$q")
    set q (string replace -r -i '^.*?\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:youtube\s+)?videos?\s+(?:on|about|for|of)\s+' '' "$q")
    set q (string replace -r -i '^.*?\b(?:do\s+(?:a\s+|an\s+)?)?youtube\s+research\s+(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string replace -r -i '^.*\byoutube\s+research\s+(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string replace -r -i '^.*\bresearch\s+(?:on\s+)?youtube\s+(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string replace -r -i '^.*\bsearch\s+youtube\s+(?:for\s+|about\s+)?' '' "$q")
    set q (string replace -r -i '^.*\bsummarize\s+youtube\s+(?:videos?\s+)?(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string replace -r -i '^.*\bsummarize\s+(?:all\s+)?youtube\s+(?:videos?\s+)?(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string replace -r -i '^.*\bsummarize\s+(?:all\s+)?(?:the\s+)?youtube\s+(?:videos?\s+)?(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string replace -r -i '^.*\byt\s+research\s+(?:about\s+|on\s+|for\s+)?' '' "$q")
    set q (string trim -- "$q")
    echo $q
end

function _agent_parse_folder_path --description "Extract directory path from NL (internal)"
    set -l m (string match -r "(?i)(['\"]?([~/][^\s'\"]+)['\"]?)" "$argv[1]")
    if test (count $m) -ge 3
        echo $m[3]
        return
    end
    set -l m2 (string match -r '(/[^\s'\'']+)' "$argv[1]")
    if test (count $m2) -ge 2
        echo $m2[2]
    end
end

function _agent_doc_ext_pattern --description "Supported RAG file extensions regex fragment (internal)"
    echo 'pdf|docx|doc|pptx|xlsx|xls|txt|md|csv|tsv|html|htm|py|js|ts|jsx|tsx|json|yaml|yml|fish|sh|bash|sql|eml|rtf|xml|tex|rst|php|rb|go|rs|java|c|cpp|h|css|scss|toml|ini|cfg|log'
end

function _agent_is_pdf_question --description "True if user wants to query ingested documents (internal)"
    set -l clean (string lower "$argv[1]")
    set -l exts (_agent_doc_ext_pattern)
    if _agent_is_pdf_ingest_request "$clean"
        return 1
    end
    if string match -qr '(?i)(ask|query|search)\s+(my\s+)?(pdf|pdfs|document|docs?|files?)\b' "$clean"
        return 0
    end
    if string match -qr "(?i)(ask|query|search)\\s+\\S+\\.(?:$exts)\\b" "$clean"
        return 0
    end
    if string match -qr '(?i)what\s+does\s+(my\s+)?(the\s+)?(pdf|document|file)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)(pdf|document|file).*(say|mention|talk|discuss)\s+about' "$clean"
        return 0
    end
    if string match -qr '(?i)(summarize|summary\s+of)\s+(my\s+)?(pdf|document|uploaded\s+docs?|file)\b' "$clean"
        return 0
    end
    if string match -qr "(?i)\\.(?:$exts)\\s+(summarize|summary|summarise|overview|tldr|ask|explain|describe|what|who|how|list)" "$clean"
        return 0
    end
    if string match -qr "(?i)^(summarize|summary|summarise)\\s+.+\\.(?:$exts)\\b" "$clean"
        return 0
    end
    if string match -qr "(?i)\\.(?:$exts)\\b" "$clean"
        if string match -qr '(?i)(summarize|summary|summarise|ask|explain|describe|what|who|how|list|tell|about|overview|weeks?|w\d)' "$clean"
            return 0
        end
    end
    if string match -qr '(?i)(summarize|summary|summarise)\s+(englsh|week|w\d|chapter|module|lecture)' "$clean"
        return 0
    end
    if string match -qr '(?i)(in|from)\s+(my\s+)?(pdf|document|uploaded\s+docs?|private\s?gpt)\b' "$clean"
        return 0
    end
    set -l py (_arka_python)
    set -l parsed ($py (_arka_py_script arka_pdf_rag.py) parse-ask "$argv[1]" 2>/dev/null)
    if test $status -eq 0 -a -n "$parsed"
        set -l parts (string split \t "$parsed")
        if test (count $parts) -ge 3 -a -n "$parts[1]" -a -n "$parts[3]"
            return 0
        end
    end
    return 1
end

function _agent_normalize_pdf_question --description "Strip document query prefixes for RAG (internal)"
    set -l py (_arka_python)
    set -l parsed ($py (_arka_py_script arka_pdf_rag.py) parse-ask "$argv[1]" 2>/dev/null)
    if test $status -eq 0 -a -n "$parsed"
        set -l parts (string split \t "$parsed")
        if test (count $parts) -ge 3 -a -n "$parts[2]" -a -n "$parts[3]"
            echo $parts[3]
            return
        end
    end
    set -l q (string trim -- "$argv[1]")
    set q (string replace -r -i '^(please\s+)?(can you\s+)?(ask|query|search)\s+(my\s+)?(pdf|pdfs|document|docs?)\s+(about\s+|on\s+|regarding\s+)?' '' "$q")
    set q (string replace -r -i '^what\s+does\s+(my\s+)?(the\s+)?(pdf|document)\s+(say|mention)\s+about\s+' '' "$q")
    set q (string replace -r -i '^(summarize|summary\s+of)\s+(my\s+)?(pdf|document|uploaded\s+docs?)\s*(about\s+|on\s+|regarding\s+)?' '' "$q")
    set q (string replace -r -i '^(please\s+)?' '' "$q")
    echo (string trim -- "$q")
end

function _agent_parse_pdf_doc --description "Extract document name from document ask request (internal)"
    set -l py (_arka_python)
    set -l parsed ($py (_arka_py_script arka_pdf_rag.py) parse-ask "$argv[1]" 2>/dev/null)
    if test $status -eq 0 -a -n "$parsed"
        set -l parts (string split \t "$parsed")
        if test (count $parts) -ge 3 -a -n "$parts[2]"
            echo $parts[2]
        end
    end
end

function _agent_pdf_ask_cmd --description "Build pdf_ask command with optional document (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l parsed ($py (_arka_py_script arka_pdf_rag.py) parse-ask "$cmd" 2>/dev/null)
    if test $status -eq 0 -a -n "$parsed"
        set -l parts (string split \t "$parsed")
        if test (count $parts) -ge 3 -a -n "$parts[2]" -a -n "$parts[3]"
            printf 'pdf_ask --doc %s %s\n' (string escape $parts[2]) (string escape $parts[3])
            return
        end
    end
    set -l doc (_agent_parse_pdf_doc "$cmd")
    set -l q (_agent_normalize_pdf_question "$cmd")
    test -z "$q"; and set q $cmd
    if test -n "$doc"
        printf 'pdf_ask --doc %s %s\n' (string escape $doc) (string escape $q)
    else
        echo "pdf_ask $q"
    end
end

function _agent_parse_doc_path --description "Extract document path from NL ingest request (internal)"
    set -l exts (_agent_doc_ext_pattern)
    set -l qm (string match -r "(?i)['\"]([^'\"]+\\.(?:$exts))['\"]" "$argv[1]")
    if test (count $qm) -ge 2
        echo $qm[2]
        return
    end
    set -l m (string match -r "(?i)([~./][^\s'\"]+\\.(?:$exts))\\b" "$argv[1]")
    if test (count $m) -ge 2
        echo $m[2]
        return
    end
    set -l m2 (string match -r "(?i)([^\s'\"]+\\.(?:$exts))\\b" "$argv[1]")
    if test (count $m2) -ge 2
        echo $m2[2]
    end
end

function _agent_parse_pdf_path --description "Extract document path from NL ingest request (internal)"
    _agent_parse_doc_path $argv
end

function _agent_is_essay_request --description "True if user wants an essay/article written on a topic"
    if _agent_is_usage_question "$argv[1]"
        return 1
    end
    if _agent_is_gmail_draft_request "$argv[1]"
        return 1
    end
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)(write|draft|compose)\s+(a\s+)?(script|python|code|function|file|program|shell|fish|bash|skill|to\s+(file|disk|clipboard))' "$clean"
        return 1
    end
    if string match -qr '(?i)^(write|draft|compose)\s+(an?\s+)?(short\s+|brief\s+)?(essay|article|report|summary|paragraph|piece)\s+(about|on|regarding)\s+' "$clean"
        return 0
    end
    if string match -qr '(?i)^(write|draft|compose)\s+(about|on|regarding)\s+' "$clean"
        return 0
    end
    return 1
end

function _agent_strip_query_prefix --description "Strip tell/explain/describe prefixes from NL (internal)"
    set -l q (string trim -- "$argv[1]")
    set q (string replace -r -i '^(?:please\s+)?(?:tell|explain|describe)(?:\s+me)?(?:\s+about)?\s+' '' "$q")
    echo (string trim -- "$q")
end

function _agent_is_investment_question --description "True for core invest/profit NL (internal; narrow for tell/ask)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    test -z "$clean"; and return 1
    string match -qr '(?i)(where\s+(to|should\s+i)\s+invest|how\s+(to|can\s+i)\s+invest|invest\s+\d|make\s+(?:a\s+)?profit|best\s+(?:place|option|way|stock|fund)\s+to\s+(?:invest|put)|\d+\s+for\s+\d+\s*(?:day|week|month)|\b(?:stock|market)\s+invest)' "$clean"
end

function _agent_normalize_knowledge_q --description "Strip tell/explain prefixes for web lookup (internal)"
    set -l q (string trim -- "$argv[1]")
    set q (string replace -r -i '^tell\s+(me\s+)?about\s+' '' "$q")
    set q (string replace -r -i '^(explain|describe)\s+(about\s+)?(the\s+)?' '' "$q")
    set q (string replace -r -i '^please\s+' '' "$q")
    echo (string trim -- "$q")
end

function _agent_is_nearby_places_question --description "True if user wants local POIs near them (offline OSM map)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)\b(nearby|near me|places near|what.s near|around me|close to me|closest to me)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(restaurant|restaurants|food|cafe|coffee|hospital|pharmacy|atm|bank|hotel|grocery|supermarket|mall|eat)\b.*\b(near|nearby|around|close)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(near|nearby|around|close)\b.*\b(restaurant|restaurants|food|cafe|coffee|hospital|pharmacy|atm|bank|hotel|grocery|supermarket|mall|places|place)\b' "$clean"
        return 0
    end
    return 1
end

function _agent_build_nearby_cmd --description "Build nearby_places skill with optional category filter (internal)"
    set -l cmd $argv[1]
    set -l clean (string lower "$cmd")
    set -l filter ""
    for token in food restaurant restaurants cafe coffee hospital pharmacy atm bank hotel grocery supermarket mall eat
        if string match -qr "(^|[[:space:]])$token(\$|[[:space:]])" "$clean"
            set filter $token
            break
        end
    end
    if test -n "$filter"
        echo "nearby_places $filter"
    else
        echo "nearby_places"
    end
end

function _agent_is_places_question --description "True if user asks about tourist places / attractions in a city (internal)"
    if _agent_is_nearby_places_question "$argv[1]"
        return 1
    end
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)\b(top\s+\d+|best|famous|must[\s-]visit|tourist|popular|iconic)\b.*\b(in|at|near|around)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(places|attractions|sightseeing|landmarks|things\s+to\s+do)\b.*\b(in|at|near|around|to\s+visit)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^(top\s+\d+\s+)?places\s+(in|to\s+visit\s+in)\s+' "$clean"
        return 0
    end
    return 1
end

function _agent_parse_hardware_component --description "gpu|cpu|ram|disk|os|ip|kernel|all from NL (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    if string match -qr '(?i)\b(gpu|graphics(\s+card)?|video\s+card|display\s+card)\b' "$clean"
        echo gpu
    else if string match -qr '(?i)\b(cpu|processor|chip(set)?)\b' "$clean"
        echo cpu
    else if string match -qr '(?i)\b(ram|memory)\b' "$clean"
        echo ram
    else if string match -qr '(?i)\b(disk|storage|hard\s+drive|ssd)\b' "$clean"
        echo disk
    else if string match -qr '(?i)\b(ip\s+address|\bip\b)\b' "$clean"
        echo ip
    else if string match -qr '(?i)\b(kernel|os|operating\s+system)\b' "$clean"
        echo os
    else
        echo all
    end
end

function _agent_is_hardware_fact_question --description "True for pinpoint my gpu/cpu/ram questions (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    test -z "$clean"; and return 1
    if string match -qr '(?i)(good\s+enough|worth\s+(it|upgrading)|should\s+i|can\s+i\s+run|will\s+it\s+run|recommend|compare|versus|\bvs\.?\b|bottleneck|outdated|too\s+old|too\s+slow|malware|infected|hacked|compromised)' "$clean"
        return 1
    end
    if string match -qr '(?i)(tell\s+(me\s+)?(what\s+(is\s+)?)?(my|the)\s+(gpu|graphics|cpu|processor|ram|memory|disk|storage|ip|kernel|os)|^(what|which)\s+(gpu|graphics|cpu|processor|ram|memory|disk|storage|ip|kernel|os)\b|(my|this)\s+(gpu|graphics(\s+card)?|cpu|processor|ram|memory|disk|storage|ip)\s*$|how\s+much\s+(ram|memory|disk|storage)\b|what\s+(gpu|graphics|cpu|processor|ram|memory)\s+(do\s+i\s+have|is\s+(this|in|installed)))' "$clean"
        return 0
    end
    return 1
end

function _agent_is_system_info_question --description "True if user wants local machine specs (not opinion/advice)"
    if _agent_is_hardware_fact_question "$argv[1]"
        return 0
    end
    set -l clean (string lower (string trim -- "$argv[1]"))
    test -z "$clean"; and return 1
    if string match -qr '(?i)(good\s+enough|worth\s+(it|upgrading)|should\s+i|can\s+i\s+run|will\s+it\s+run|recommend|compare|versus|\bvs\.?\b|bottleneck|outdated|too\s+old|too\s+slow|malware|infected|hacked|compromised)' "$clean"
        return 1
    end
    if string match -qr '(?i)(system\s*info|system\s*information|\bos\s+info\b)' "$clean"
        return 0
    end
    if string match -qr '(?i)(specs?|specifications|hardware)\s+(of|for|on)\s+(my|this|the)\s+(pc|mac|macbook|imac|machine|computer|laptop|system)' "$clean"
        return 0
    end
    if string match -qr '(?i)^(show|get|list|give)\s+(me\s+)?(the\s+)?(specs?|specifications|hardware)\s+(of|for)\s+(my|this)' "$clean"
        return 0
    end
    if string match -qr '(?i)(tell\s+(me\s+)?about|describe|show\s+(me\s+)?|what\s+(are|is))\s+(my\s+|this\s+)?(mac|macbook|imac|machine|computer|laptop|pc|system|hardware|specs?)' "$clean"
        return 0
    end
    if string match -qr '(?i)(my|this)\s+(mac|macbook|imac|machine|computer|laptop|pc|system)\s+(specs?|specifications|info|details|hardware|configuration)' "$clean"
        return 0
    end
    if string match -qr '(?i)^about\s+my\s+(mac|macbook|machine|computer|laptop|pc|system)\s*$' "$clean"
        return 0
    end
    return 1
end

function _agent_run_skill_line --description "Run one skill string like 'system_info gpu' (internal)"
    set -l line (string trim -- "$argv[1]")
    test -z "$line"; and return 1
    set -l tokens (string split " " -- "$line")
    set -l fn $tokens[1]
    set -e tokens[1]
    if test (count $tokens) -gt 0
        $fn $tokens
    else
        $fn
    end
    return $status
end

function _agent_route_system_info --description "Route to system_info or system_info <component> (internal)"
    set -l cmd "$argv[1]"
    if _agent_is_hardware_fact_question "$cmd"
        echo "system_info "(_agent_parse_hardware_component "$cmd")
    else
        echo "system_info"
    end
end

function _agent_is_knowledge_question --description "True if user wants a factual answer, not a browser search"
    if _agent_is_daily_brief_request "$argv[1]"
        return 1
    end
    if _agent_is_price_check_request "$argv[1]"
        return 1
    end
    if _agent_is_investment_question "$argv[1]"
        return 1
    end
    if _agent_is_system_info_question "$argv[1]"
        return 1
    end
    if _agent_is_usage_question "$argv[1]"
        return 1
    end
    if _agent_is_pdf_question "$argv[1]"; or _agent_is_pdf_ingest_request "$argv[1]"
        return 1
    end
    if _agent_is_nearby_places_question "$argv[1]"
        return 1
    end
    if _agent_is_video_search_request "$argv[1]"
        return 1
    end
    if _agent_is_translate_request "$argv[1]"
        return 1
    end
    if _agent_is_pr_check_request "$argv[1]"
        return 1
    end
    if _agent_is_github_repo_request "$argv[1]"
        return 1
    end
    if _agent_is_competitions_request "$argv[1]"
        return 1
    end
    if _agent_is_bookmarks_request "$argv[1]"
        return 1
    end
    if _agent_is_repo_health_request "$argv[1]"
        return 1
    end
    if _agent_is_generate_data_request "$argv[1]"
        return 1
    end
    if _agent_is_data_ask_request "$argv[1]"
        return 1
    end
    if _agent_is_docker_status_request "$argv[1]"
        return 1
    end
    if _agent_is_clipboard_history_request "$argv[1]"
        return 1
    end
    if _agent_is_model_select_request "$argv[1]"
        return 1
    end
    if _agent_is_personalize_request "$argv[1]"
        return 1
    end
    if _agent_is_life_sciences_request "$argv[1]"
        return 1
    end
    if _agent_is_gemini_cli_request "$argv[1]"
        return 1
    end
    if _agent_is_route_learn_request "$argv[1]"
        return 1
    end
    if _agent_is_model_select_request "$argv[1]"
        return 1
    end
    if _agent_is_personalize_request "$argv[1]"
        return 1
    end
    if _agent_is_life_sciences_request "$argv[1]"
        return 1
    end
    if _agent_is_gemini_cli_request "$argv[1]"
        return 1
    end
    if _agent_is_survival_lang_request "$argv[1]"
        return 1
    end
    if _agent_is_currency_request "$argv[1]"
        return 1
    end
    if _agent_is_kalshi_request "$argv[1]"
        return 1
    end
    if _agent_is_post_x_request "$argv[1]"
        return 1
    end
    if _agent_is_google_calendar_request "$argv[1]"
        or _agent_is_google_gmail_request "$argv[1]"
        return 1
    end
    set -l clean (string lower "$argv[1]")
    # Email compose/send with an address — Gmail draft, not web_answer
    if string match -qr '(?i)[\w.+-]+@[\w.-]+\.\w+' "$clean"
        and string match -qr '(?i)\b(send|email|draft|compose|write)\b' "$clean"
        return 1
    end
    # Gift / life advice / general recommendations — web lookup, not shell context
    if string match -qr '(?i)\b(birthday|anniversary|wedding|valentine|christmas|holiday|gift|gifts|present|presents)\b' "$clean"
        and not string match -qr '(?i)\b(this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop))\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^what\s+to\s+(give|buy|get|choose|pick|wear|say|cook|make|bring|serve)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^what\s+(should|can|could)\s+i\s+(give|buy|get|choose|pick)\b' "$clean"
        and not string match -qr '(?i)\b(this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop))\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^(gift|present)\s+ideas?\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\bideas\s+for\s+(a\s+)?(gift|present|birthday)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)(google|search\s+(the\s+)?web|search\s+online|look\s+up\s+online|open\s+.*search|\bsearch\s+for\b|\bfind\s+on\s+google\b)' "$clean"
        return 1
    end
    # Health / nutrition / general knowledge — web lookup, not shell context
    if string match -qr '(?i)\b(vitamin|supplement|nutrition|nutrient|mineral|herbal|nootropic|focus|memory|concentration|cognitive|brain\s+health|diet|food|protein|caffeine|magnesium|omega|zinc|iron|b12|creatine|wellness|medication|symptom|treatment|remedy)\b' "$clean"
        and not string match -qr '(?i)\b(my|this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop|terminal|shell))\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^which\s+' "$clean"
        and not string match -qr '(?i)\b(my|this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|driver|terminal|shell|mac|macbook|machine|laptop))\b' "$clean"
        return 0
    end
    # Personal / system questions belong in agent_ask or system_info, not web_answer
    if string match -qr '(?i)\b(this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|driver|terminal|shell|mac|macbook|machine|laptop))\b' "$clean"
        return 1
    end
    if string match -qr '(?i)\b(my|should\s+i|can\s+i|do\s+i|am\s+i)\b' "$clean"
        and string match -qr '(?i)\b(outdated|too\s+old|too\s+slow|good\s+enough|worth\s+upgrad|bottleneck|malware|infected|hacked|compromised|specs?\s+for\s+my|upgrade|gaming|cpu|gpu|ram|disk|system|pc|computer|mac|macbook|machine|laptop)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)(outdated|too\s+old|too\s+slow|good\s+enough|worth\s+upgrad|bottleneck|malware|infected|hacked|compromised|specs?\s+for\s+my)' "$clean"
        return 1
    end
    if string match -qr '(?i)^show\s+me\s+' "$clean"
        and not string match -qr '(?i)\b(image|photo|picture|pic|screenshot|snapshot|\.png|\.jpe?g|\.webp|\.gif|\.bmp|\.svg|\.heic|\.tiff?)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^(why\s+(is|are|was|were|do|does|did)|where\s+(is|are|was|were)|when\s+(is|are|was|were|did|does)|who\s+(is|are|was|were)|what\s+(is|are|was|were)|tell\s+(me\s+)?(about|why|where|who|what|when|how)|tell\s+about|explain\s+(what|why|where|who|when|the|about)|describe\s+(what|why|the|about)|how\s+(old|tall|long|far|big|many|much)\s+(is|are|was|were)|what\s+do\s+you\s+know\s+about)' "$clean"
        and not string match -qr '(?i)^(what\s+(is\s+)?(the\s+)?(weather|time|date|ip|my\s+ip)|how\s+(much|many)\s+(disk|space|memory|ram)\s+(left|free|used)|explain\s+how\s+to\s+(install|download|setup|get|fix|use|run|create|open))' "$clean"
        return 0
    end
    return 1
end

function _agent_is_files_preference_question --description "True if user complains about images landing on desktop/home/downloads (internal)"
    set -l clean (string lower "$argv[1]")
    if not string match -qr '(?i)\b(image|images|photo|photos|picture|pictures|screenshot|screenshots|wallpaper|wallpapers|png|jpg|jpeg|pic|pics)\b' "$clean"
        return 1
    end
    if not string match -qr '(?i)\b(desktop|download|downloads|home\s+folder|home\s+directory|my\s+home|on\s+home|\bhome\b|pictures\s+folder)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)(don'\''t\s+like|do\s+not\s+like|hate|annoy|clutter|messy|too\s+many|shouldn'\''t|should\s+not|stop\s+sav|where\s+(do|does|are)|change\s+(where|the)|move|organiz|clean|sort|prefer|instead\s+of|take\s+place|end\s+up|save\s+to|saved\s+to|put\s+on|putting|crowd|cluttered)' "$clean"
        return 0
    end
    if string match -qr '(?i)^(i\s+(?:don'\''t|do\s+not)\s+like|images?\s+on|photos?\s+on|pictures?\s+on|why\s+(?:are|do)\s+(?:images?|photos?|pictures?))' "$clean"
        return 0
    end
    return 1
end

function _agent_is_desktop_organize_request --description "True if user wants to sort/clean desktop or downloads images (internal)"
    set -l clean (string lower "$argv[1]")
    if not string match -qr '(?i)\b(organiz|sort|classify|clean|tidy|declutter|arrange)\b' "$clean"
        return 1
    end
    if not string match -qr '(?i)\b(desktop|download|downloads|file|files|image|images|photo|photos|picture|pictures|folder)\b' "$clean"
        return 1
    end
    return 0
end

function _agent_is_advisory_question --description "True if user wants an opinion/answer, not a metrics dump"
    if _agent_is_describe_screen_request "$argv[1]"
        return 1
    end
    if _agent_is_investment_question "$argv[1]"
        return 1
    end
    if _agent_is_system_info_question "$argv[1]"
        return 1
    end
    if _agent_is_knowledge_question "$argv[1]"
        return 1
    end
    if _agent_is_files_preference_question "$argv[1]"
        return 1
    end
    if _agent_is_storage_breakdown_question "$argv[1]"
        return 1
    end
    set -l clean (string lower "$argv[1]")
    # Health / nutrition / general "which …" — web_answer, not shell advisory
    if string match -qr '(?i)\b(vitamin|supplement|nutrition|nutrient|mineral|herbal|nootropic|focus|memory|concentration|cognitive|brain\s+health|diet|food|protein|health|wellness|medication|symptom|treatment|remedy)\b' "$clean"
        and not string match -qr '(?i)\b(my|this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop|terminal|shell))\b' "$clean"
        return 1
    end
    if string match -qr '(?i)^which\s+' "$clean"
        and not string match -qr '(?i)\b(my|this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|driver|terminal|shell|mac|macbook|machine|laptop))\b' "$clean"
        return 1
    end
    # Explicit metrics / monitor requests
    if string match -qr '(?i)(system\s*monitor|system\s*status|show\s+(me\s+)?(system\s+)?(monitor|resources)|check\s+(cpu|ram|memory|disk|battery)|\b(cpu|ram|memory|disk)\s+(usage|load|percent)|how\s+much\s+(cpu|ram|memory|disk)\s+(left|free|used|available)|\buptime\b|\bbattery\b|\bload\s+average|port_scan|speedtest|system_info|take\s+a\s+screenshot)' "$clean"
        return 1
    end
    # Security / malware diagnostics (opinion from gathered evidence, not a live monitor)
    if string match -qr '(?i)(malware|virus|viruses|infected|compromised|rootkit|trojan|ransomware|spyware|keylogger|botnet|have\s+i\s+been\s+hacked|been\s+hacked|security\s+(risk|threat|issue|problem)|suspicious\s+(process|activity|connection|program|file))' "$clean"
        return 0
    end
    if string match -qr '(?i)^(tell\s+(me\s+)?(if|whether)|check\s+(if|for|whether)|scan\s+(my\s+)?(pc|computer|system|machine)\s+for|do\s+i\s+have|am\s+i\s+(infected|compromised|hacked))' "$clean"
        return 0
    end
    # Hardware/software opinion, compatibility, recommendations
    if string match -qr '(?i)(outdated|too\s+old|too\s+slow|good\s+enough|worth\s+(it|upgrading)|should\s+i\s+(upgrade|buy|get|replace)|enough\s+for|capable\s+of|can\s+i\s+run|will\s+it\s+run|recommend|comparison|compare|better\s+than|\bvs\.?\b|versus|bottleneck|specs?\s+for)' "$clean"
        return 0
    end
    # Open-ended questions about this machine (need local context)
    if string match -qr '(?i)^(is|are|am|should|can|could|would|will|how|why|what|which|who|do|does|did|where|when)\s+' "$clean"
        and string match -qr '(?i)\b(my|this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop|terminal|shell|driver|software|app|browser|wifi|network|battery|storage|malware|infected|hacked|compromised))\b' "$clean"
        and not string match -qr '(?i)^(what\s+(is\s+)?(the\s+)?(weather|time|date|ip|my\s+ip)|how\s+(much|many)\s+(disk|space|memory|ram)\s+(left|free|used))' "$clean"
        return 0
    end
    # Personal statements about this machine → agent_ask; life/health → general_chat/web_answer
    if string match -qr '(?i)^i(?:'\''m|\s+am|\s+have|\s+feel|\s+need|\s+want|\s+was|\s+think|\s+got|\s+keep|\s+started|\s+noticed|\s+face|\s+facing|\s+suffer|\s+lost|\s+gained)\s+' "$clean"
        and string match -qr '(?i)\b(my|this pc|my pc|my computer|my cpu|my gpu|my ram|my disk|my system|my laptop|my terminal|my shell|my driver|malware|infected|hacked|compromised)\b' "$clean"
        return 0
    end
    if string match -qr '\?$' "$clean"
        and string match -qr '(?i)\b(my|this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop|terminal|shell|driver|malware|infected|hacked|compromised|outdated|upgrade))\b' "$clean"
        return 0
    end
    return 1
end

function _agent_is_general_chat --description "True if plain conversational input, not shell/skill"
    set -l clean (string lower (string trim -- "$argv[1]"))
    test -z "$clean"; and return 1
    if _agent_is_files_preference_question "$argv[1]"; or _agent_is_desktop_organize_request "$argv[1]"
        return 1
    end
    if _agent_is_platform_howto_question "$argv[1]"
        return 1
    end
    if _agent_is_system_info_question "$argv[1]"
        return 1
    end
    set -l exts (_agent_doc_ext_pattern)
    if string match -qr "(?i)\\.(?:$exts)\\b" "$clean"
        return 1
    end
    if _agent_is_knowledge_question "$argv[1]"; or _agent_is_advisory_question "$argv[1]"
        return 1
    end
    if _agent_is_usage_question "$argv[1]"; or _agent_is_pdf_question "$argv[1]"; or _agent_is_essay_request "$argv[1]"
        return 1
    end
    if _agent_is_aie_request "$argv[1]"
        return 1
    end
    if _agent_is_youtube_bulk_request "$argv[1]"
        return 1
    end
    if _agent_is_youtube_download_request "$argv[1]"
        return 1
    end
    if _agent_is_model_select_request "$argv[1]"
        return 1
    end
    if _agent_is_personalize_request "$argv[1]"
        return 1
    end
    if _agent_is_life_sciences_request "$argv[1]"
        return 1
    end
    if _agent_is_gemini_cli_request "$argv[1]"
        return 1
    end
    if _agent_is_bookmarks_request "$argv[1]"
        return 1
    end
    if _agent_is_competitions_request "$argv[1]"
        return 1
    end
    if _agent_is_generate_data_request "$argv[1]"
        return 1
    end
    if _agent_is_data_ask_request "$argv[1]"
        return 1
    end
    if _agent_is_repo_health_request "$argv[1]"
        return 1
    end
    if _agent_is_docker_status_request "$argv[1]"
        return 1
    end
    if _agent_is_kalshi_request "$argv[1]"
        return 1
    end
    if _agent_is_mcp_request "$argv[1]"
        return 1
    end
    if string match -qr '(?i)^(select|best_model|model_select|gemini|gemini_cli|life|bookmarks|mcp|docker|clipboard|competitions|route|teach|generate_data|data_ask|ask_data|query_data|analyze_data|repo_health|post_x|daily_brief)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)^(install|play|open|run|create|download|search|list|show|fix|set|take|timer|remind|weather|pdf|ingest|screenshot|spotify|whatsapp|send|loop|agent_|generate_image|generate_video|generate_password|chart|ascii|ascii_art|figlet|graph|plot|predictions|stock|translate|survive_lang|pr_check|cheat|excuse|bored)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)^(routines?\b|every\s+day|each\s+day|daily\s+at|every\s+morning|every\s+evening|every\s+hour|schedule\s+daily)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)^(generate|create|make)\s+(?:a |an |the |me )?(?:new )?(password|passcode)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)(save|store|get|retrieve|list|rotate|delete).*(password|passcode)|(?:password|passcode).*(for|named)\b' "$clean"
        and not string match -qr '(?i)(decrypt|protected|pdf)' "$clean"
        return 1
    end
    if string match -qr '(?i)^i(?:'\''m|\s+am|\s+have|\s+feel|\s+need|\s+want|\s+was|\s+think|\s+got|\s+keep|\s+started|\s+noticed|\s+face|\s+facing|\s+suffer|\s+lost|\s+gained)\s+' "$clean"
        return 0
    end
    if string match -qr '(?i)^(about|facing|dealing with|struggling with|suffering from|worried about|concerned about|tell me about)\s+' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(hair\s*loss|alopecia|anxiety|depression|headache|migraine|insomnia|sleep|weight\s*loss|weight\s*gain|acne|allerg|diabetes|blood\s*pressure|cholesterol|stress|burnout|fatigue|nutrition|diet|exercise|pregnancy|fertility|symptom|treatment|remedy|medication)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^(help me|please help|can you|could you|tell me about|give me advice|any tips|what should i do|how do i deal|i need help)\b' "$clean"
        return 0
    end
    if string match -qr '(?i)^(hi|hello|hey|good morning|good evening|thanks|thank you)\b' "$clean"
        if string match -qr '(?i)(play|open|install|run|search|weather|timer|stop|listen|debug|spotify|youtube|music|song|movie)\b' "$clean"
            return 1
        end
        return 0
    end
    if string match -qr '\?' "$clean"
        return 0
    end
    set -l n (count (string split " " "$clean"))
    if test $n -ge 3
        and not string match -qr '[;|&><`$\\(){}]' "$clean"
        and not string match -qr '(?i)^(sudo|cd|ls|cat|grep|find|apt|pip|npm|uv|git|curl|wget|python|fish|play|open|install|run|create|download|search|list|show|fix|set|timer|weather)\s' "$clean"
        and string match -qr '^[a-z0-9 ,'\''"-]+$' "$clean"
        return 0
    end
    if test $n -ge 4
        and not string match -qr '[;|&><`$\\(){}]' "$clean"
        and not string match -qr '(?i)^(sudo|cd|ls|cat|grep|find|apt|pip|npm|uv|git|curl|wget|python|fish)\s' "$clean"
        return 0
    end
    return 1
end

function _agent_route_general_chat --description "Pick web_answer vs agent_ask for conversational input (internal)"
    set -l cmd "$argv[1]"
    if _agent_is_platform_howto_question "$cmd"
        echo "platform_howto $cmd"
        return
    end
    if _agent_is_files_preference_question "$cmd"
        echo "files_preference_help $cmd"
    else if _agent_is_system_info_question "$cmd"
        echo (_agent_route_system_info "$cmd")
    else if string match -qr '(?i)\b(my|this pc|my pc|my computer|my cpu|my gpu|my system|my laptop|my mac|my macbook|my machine|this mac|my terminal|my shell|malware|infected|hacked|compromised)\b' "$cmd"
        echo "agent_ask $cmd"
    else
        echo "web_answer $cmd"
    end
end

function _agent_is_google_login_request --description "True if user wants Google OAuth sign-in (internal)"
    string match -qr '(?i)(google\s+(?:login|sign[\s-]?in|connect|auth|setup|status|logout)|connect\s+(?:my\s+)?(?:google|gmail|calendar)|sign[\s-]?in\s+(?:to\s+)?(?:google|gmail|calendar)|link\s+(?:my\s+)?google|oauth\s+google)' "$argv[1]"
end

function _agent_is_post_x_request --description "True if user wants to post/share URL content on X/Twitter (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_x_post.py) parse (string escape --style=script -- $argv[1]) >/dev/null 2>&1
end

function _agent_build_post_x_cmd --description "Build post_x args from NL (internal)"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_x_post.py) parse (string escape --style=script -- $argv[1]) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "post_x $rest"
    end
end

function _agent_is_gmail_draft_request --description "True if user wants a Gmail draft (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_google.py) parse-draft (string escape --style=script -- $argv[1]) >/dev/null 2>&1
end

function _agent_build_gmail_draft_cmd --description "Build google gmail --draft args from NL (internal)"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_google.py) parse-draft (string escape --style=script -- $argv[1]) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "google $rest"
    end
end

function _agent_is_gmail_summarize_request --description "True if user wants AI summary of Gmail (internal)"
    string match -qr '(?i)(summarize|summary|tldr|digest|brief).*(email|emails|gmail|gmails|mail|inbox)' "$argv[1]"
    or string match -qr '(?i)(email|emails|gmail|gmails|mail|inbox).*(summarize|summary|tldr|digest|brief)' "$argv[1]"
end

function _agent_build_gmail_cmd --description "Build google gmail args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l summarize 0
    if test (count $argv) -ge 2; and test "$argv[2]" = summarize
        set summarize 1
    end
    set -l out
    if test $summarize -eq 1
        set out "google gmail --summarize"
    else
        set out "google gmail"
    end
    if string match -qr '(?i)\bunread\b' "$cmd"
        set out "$out --unread"
    end
    set -l days (_agent_parse_gmail_days "$cmd")
    if test -n "$days"
        set out "$out --days $days"
    else if string match -qr '(?i)\btoday\b' "$cmd"
        set out "$out --today"
    end
    set -l unread_only 0
    if string match -qr '(?i)\bunread\b' "$cmd"
        set unread_only 1
    end
    if string match -qr '(?i)\ball\b' "$cmd"
        set out "$out --all"
    else if test $unread_only -eq 1; and test -z "$days"; and not string match -qr '(?i)\btoday\b' "$cmd"
        set out "$out --all"
    else if test $summarize -eq 1
        set out "$out --all"
    else if test -n "$days"
        set out "$out --limit 100"
    end
    if test $summarize -eq 1
        if test -z "$days"; and not string match -qr '(?i)\btoday\b' "$cmd"; and test $unread_only -eq 0
            set out "$out --days 2 --all"
        end
    else if string match -qr '(?i)\b(snippet|preview|body)\b' "$cmd"
        set out "$out --snippet"
    end
    echo $out
end

function _agent_is_routines_request --description "True if user wants a daily/hourly routine (internal)"
    test -n "$(_agent_build_routines_cmd "$argv[1]")"
end

function _agent_build_routines_cmd --description "Build routines args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_routines.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "routines $rest"
    end
end

function _agent_is_remind_request --description "True if user wants a reminder (internal)"
    test -n "$(_agent_build_remind_cmd "$argv[1]")"
end

function _agent_is_currency_request --description "True if user wants currency conversion (internal)"
    test -n "$(_agent_build_currency_cmd "$argv[1]")"
end

function _agent_is_kalshi_request --description "True if user wants Kalshi prediction market data (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    string match -qr '(?i)\b(kalshi|prediction\s+market|kalshi\s+odds|kalshi\s+predictions?)\b' "$clean"
end

function _agent_build_kalshi_cmd --description "Build kalshi invocation from NL (internal)"
    set -l py (_arka_python)
    set -l cmd $argv[1]
    set -l rest ($py (_arka_py_script arka_kalshi.py) parse -- $cmd 2>/dev/null)
    if test (count $rest) -gt 0
        echo "kalshi $rest"
    end
end

function _agent_build_currency_cmd --description "Build currency_convert args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_currency.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "currency_convert $rest"
    end
end

function _agent_is_price_check_request --description "True if user wants retail product prices (internal)"
    set -l clean (string lower "$argv[1]")
    if string match -qr '(?i)^price_check\b' "$clean"
        return 0
    end
    if string match -qr '(?i)\b(?:stock|crypto|bitcoin|ethereum|btc|eth|solana|share|ticker|house\s+price|rent|gas\s+price|oil\s+price|gold\s+price|silver\s+price)\b' "$clean"
        return 1
    end
    if string match -qr '(?i)\b(?:price\s+of|cost\s+of|what(?:''s| is) the price of)\s+' "$clean"
        return 0
    end
    if string match -qr '(?i)\bhow\s+much\s+(?:is|are|does|for)\s+(?:the\s+)?(?:a\s+)?' "$clean"
        and not string match -qr '(?i)\b(?:disk|space|memory|ram|cpu|gpu|battery)\b' "$clean"
        return 0
    end
    if string match -qr '(?i).+\s+price\s+(?:right\s+now|in\s+(?:india|us|usa))' "$clean"
        return 0
    end
    if string match -qr '(?i).+\s+price\s*$' "$clean"
        and not string match -qr '(?i)\b(?:stock|crypto|bitcoin|ethereum)\b' "$clean"
        return 0
    end
    return 1
end

function _agent_parse_price_check_query --description "Extract product query for price_check (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l out ($py -c "
from arka.agent.price_sources import extract_product_name
import sys
print(extract_product_name(sys.argv[1]))
" (string escape --style=script -- $cmd) 2>/dev/null)
    string trim -- $out
end

function _agent_build_remind_cmd --description "Build remind args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_remind.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "remind $rest"
    end
end

function _agent_parse_guess_route --description "Extract skill command from guess_route line (internal)"
    set -l line "$argv[1]"
    set -l parts (string split "|" "$line")
    if test (count $parts) -lt 2
        return 1
    end
    switch $parts[1]
        case skill shell llm_codegen
            echo $parts[2]
            return 0
        case listen
            echo "listen $parts[2]"
            return 0
        case none llm
            return 1
    end
    return 1
end

function _agent_parse_video_prompt --description "Extract AI video prompt from NL (internal)"
    set -l cmd "$argv[1]"
    set -l rest (string replace -r -i '^(?:generate|create|make|render|produce|animate|film)\s+(?:an?\s+)?(?:video|clip|animation|movie|animated\s+video)\s*' '' "$cmd" | string trim)
    if test -z "$rest"
        set rest (string replace -r -i '^(?:generate|create|make|render|produce|animate|film)\s+(?:an?\s+)?' '' "$cmd" | string trim)
    end
    set rest (string replace -r -i '^(?:of|about|on|for|showing)\s+' '' "$rest" | string trim)
    echo $rest
end

function _agent_offline_route_cmd --description "Full symbolic NL to skill command (internal)"
    set -l cmd "$argv[1]"
    if _agent_is_currency_request "$cmd"
        echo (_agent_build_currency_cmd "$cmd")
        return 0
    end
    if _agent_is_remind_request "$cmd"
        echo (_agent_build_remind_cmd "$cmd")
        return 0
    end
    if _agent_is_routines_request "$cmd"
        echo (_agent_build_routines_cmd "$cmd")
        return 0
    end
    if _agent_is_file_size_find "$cmd"
        echo (_agent_route_file_size_find "$cmd")
        return 0
    end
    if _agent_is_chart_request "$cmd"
        echo (_agent_build_chart_cmd "$cmd")
        return 0
    end
    if _agent_is_model_select_request "$cmd"
        echo (_agent_build_model_select_cmd "$cmd")
        return 0
    end
    if _agent_is_personalize_request "$cmd"
        echo (_agent_build_personalize_cmd "$cmd")
        return 0
    end
    if _agent_is_ascii_art_request "$cmd"
        echo (_agent_build_ascii_art_cmd "$cmd")
        return 0
    end
    if _agent_is_drawing_ask_request "$cmd"
        echo (_agent_build_drawing_ask_cmd "$cmd")
        return 0
    end
    if _agent_is_describe_screen_request "$cmd"
        echo (_agent_build_describe_screen_cmd "$cmd")
        return 0
    end
    if _agent_is_describe_image_request "$cmd"
        echo (_agent_build_describe_image_cmd "$cmd")
        return 0
    end
    if _agent_is_generate_thumbnail_request "$cmd"
        echo (_agent_build_generate_thumbnail_cmd "$cmd")
        return 0
    end
    if _agent_is_generate_image_request "$cmd"
        echo (_agent_build_generate_image_cmd "$cmd")
        return 0
    end
    if _agent_is_compose_slides_request "$cmd"
        echo (_agent_build_compose_slides_cmd "$cmd")
        return 0
    end
    if _agent_is_convert_media_request "$cmd"
        echo (_agent_build_convert_media_cmd "$cmd")
        return 0
    end
    if _agent_is_compose_video_request "$cmd"
        echo (_agent_build_compose_video_cmd "$cmd")
        return 0
    end
    if _agent_is_download_request "$cmd"
        echo (_agent_build_download_cmd "$cmd")
        return 0
    end
    if set -l g (_agent_route_google "$cmd")
        echo $g
        return 0
    end
    if _agent_is_agent_hub_request "$cmd"
        set -l hub_cmd (_agent_route_agent_hub "$cmd")
        if test -n "$hub_cmd"
            echo $hub_cmd
            return 0
        end
    end
    if _agent_is_mcp_request "$cmd"
        set -l mcp_cmd (_agent_route_mcp "$cmd")
        if test -n "$mcp_cmd"
            echo $mcp_cmd
            return 0
        end
    end
    if _agent_is_post_x_request "$cmd"
        echo (_agent_build_post_x_cmd "$cmd")
        return 0
    end
    if _agent_is_gmail_summarize_request "$cmd"
        echo (_agent_build_gmail_cmd "$cmd" summarize)
        return 0
    end
    if _agent_is_investment_question "$cmd"
        set -l topic (_agent_strip_query_prefix "$cmd")
        echo "predictions --domain stocks --deep "(string escape --style=script -- $topic)
        return 0
    end
    if _agent_is_clipboard_history_request "$cmd"
        echo (_agent_route_clipboard_history "$cmd")
        return 0
    end
    if _agent_is_competitions_request "$cmd"
        echo (_agent_route_competitions "$cmd")
        return 0
    end
    if _agent_is_bookmarks_request "$cmd"
        echo (_agent_route_bookmarks "$cmd")
        return 0
    end
    if _agent_is_repo_health_request "$cmd"
        echo (_agent_route_repo_health "$cmd")
        return 0
    end
    if _agent_is_generate_data_request "$cmd"
        echo (_agent_route_generate_data "$cmd")
        return 0
    end
    if _agent_is_data_ask_request "$cmd"
        echo (_agent_route_data_ask "$cmd")
        return 0
    end
    if _agent_is_docker_status_request "$cmd"
        echo (_agent_route_docker_status "$cmd")
        return 0
    end
    if _agent_is_route_learn_request "$cmd"
        echo (_agent_route_learn_management "$cmd")
        return 0
    end
    if _agent_is_daily_brief_request "$cmd"
        echo "daily_brief"
        return 0
    end
    if _agent_is_life_sciences_request "$cmd"
        echo (_agent_route_life_sciences "$cmd")
        return 0
    end
    if _agent_is_platform_howto_question "$cmd"
        echo "platform_howto $cmd"
        return 0
    end
    if _agent_is_gemini_cli_request "$cmd"
        echo (_agent_build_gemini_cli_cmd "$cmd")
        return 0
    end
    set -l prev $ROUTE_MODE
    set -gx ROUTE_MODE symbolic_only
    set -l guess (_agent_guess_route "$cmd")
    if set -q prev
        set -gx ROUTE_MODE $prev
    else
        set -e ROUTE_MODE
    end
    _agent_parse_guess_route "$guess"
end

function _agent_is_chart_request --description "True if user wants a data chart (internal)"
    test -n "$(_agent_build_chart_cmd "$argv[1]")"
end

function _agent_build_model_select_cmd --description "Build select_model args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_model_advisor.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "select_model $rest"
    end
end

function _agent_build_personalize_cmd --description "Build personalize args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_personalize.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "personalize $rest"
    end
end

function _agent_is_personalize_request --description "True if user wants onboarding or skill recommendations (internal)"
    test -n "$(_agent_build_personalize_cmd "$argv[1]")"
end

function _agent_is_model_select_request --description "True if user wants hardware-based model advice (internal)"
    test -n "$(_agent_build_model_select_cmd "$argv[1]")"
end

function _agent_build_chart_cmd --description "Build chart args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_chart.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "chart $rest"
    end
end

function _agent_is_ascii_art_request --description "True if user wants ASCII art (internal)"
    test -n "$(_agent_build_ascii_art_cmd "$argv[1]")"
end

function _agent_build_ascii_art_cmd --description "Build ascii_art args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_ascii_art.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "ascii_art $rest"
    end
end

function _agent_is_drawing_ask_request --description "True if user wants drawing/blueprint vision analysis (internal)"
    test -n "$(_agent_build_drawing_ask_cmd "$argv[1]")"
end

function _agent_build_drawing_ask_cmd --description "Build drawing_ask args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_drawing.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "drawing_ask $rest"
    end
end

function _agent_is_describe_screen_request --description "True if user wants screen capture + vision describe (internal)"
    test -n "$(_agent_build_describe_screen_cmd "$argv[1]")"
end

function _agent_build_describe_screen_cmd --description "Build describe_screen args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_screen.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "describe_screen $rest"
    end
end

function _agent_is_describe_image_request --description "True if user wants vLLM image description (internal)"
    test -n "$(_agent_build_describe_image_cmd "$argv[1]")"
end

function _agent_build_generate_image_cmd --description "Build generate_image args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_generate_image.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "generate_image $rest"
    end
end

function _agent_is_generate_image_request --description "True if user wants AI image generation (internal)"
    test -n "$(_agent_build_generate_image_cmd "$argv[1]")"
end

function _agent_build_generate_thumbnail_cmd --description "Build generate_thumbnail args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_generate_thumbnail.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "generate_thumbnail generate $rest"
    end
end

function _agent_is_generate_thumbnail_request --description "True if user wants YouTube thumbnail (internal)"
    test -n "$(_agent_build_generate_thumbnail_cmd "$argv[1]")"
end

function _agent_build_compose_slides_cmd --description "Build compose_slides args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l name (_agent_call_name)
    set cmd (string replace -r -i "^$name\\s+" '' "$cmd" | string trim)
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_compose_slides.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "compose_slides $rest"
    end
end

function _agent_is_compose_slides_request --description "True if user wants presentation slides (internal)"
    test -n "$(_agent_build_compose_slides_cmd "$argv[1]")"
end

function _agent_build_convert_media_cmd --description "Build convert_media args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l name (_agent_call_name)
    set cmd (string replace -r -i "^$name\\s+" '' "$cmd" | string trim)
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_convert_media.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "convert_media $rest"
    end
end

function _agent_is_convert_media_request --description "True if user wants media format conversion (internal)"
    test -n "$(_agent_build_convert_media_cmd "$argv[1]")"
end

function _agent_build_compose_video_cmd --description "Build compose_video args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l name (_agent_call_name)
    set cmd (string replace -r -i "^$name\\s+" '' "$cmd" | string trim)
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_compose_video.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "compose_video $rest"
    end
end

function _agent_is_compose_video_request --description "True if user wants info/YouTube video compose (internal)"
    test -n "$(_agent_build_compose_video_cmd "$argv[1]")"
end

function _agent_build_describe_image_cmd --description "Build describe_image args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_describe_image.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo "describe_image $rest"
    end
end

function _agent_build_download_cmd --description "Build download_file args from NL (internal)"
    set -l cmd "$argv[1]"
    set -l clean (string lower "$cmd")
    if string match -qr '(?i)download\s+and\s+install' "$clean"
        return 1
    end
    if _agent_is_youtube_bulk_request "$cmd"
        return 1
    end
    if _agent_is_youtube_download_request "$cmd"
        return 1
    end
    set -l url (string match -r '(https?://[^\s"\']+)' "$cmd")[1]
    if test -n "$url"
        if string match -qr '(?i)\b(download|save|fetch|grab|wget|curl)\b' "$clean"
            echo "download_file $url"
            return 0
        else if test (string trim "$cmd") = "$url"
            echo "download_file $url"
            return 0
        end
    end
    set -l target ""
    if string match -qr '(?i)^(?:download\s+|wget\s+|curl\s+-o\s+)' "$clean"
        set target (string replace -r -i '^(?:download\s+|wget\s+|curl\s+-o\s+)' '' "$cmd" | string trim)
    else if string match -qr '(?i)^download\s+(?:this|the)\s+' "$clean"
        set target (string replace -r -i '^download\s+(?:this|the)\s+' '' "$cmd" | string trim)
    end
    if test -n "$target"
        echo "download_file $target"
    end
end

function _agent_is_download_request --description "True if user wants to download a file (internal)"
    test -n "$(_agent_build_download_cmd "$argv[1]")"
end

function _agent_is_google_gmail_request --description "True if user wants Gmail via Google integration (internal)"
    set -l cmd "$argv[1]"
    if string match -qr '(?i)(send\s+email|compose|write\s+email|draft|voice\s+mail|voicemail)' "$cmd"
        return 1
    end
    if not string match -qr '(?i)(\bgmails?\b|google\s+mail|google\s+email|\bemails?\b|\bmail\b)' "$cmd"
        return 1
    end
    if _agent_is_gmail_summarize_request "$cmd"
        return 1
    end
    string match -qr '(?i)(unread|check|read|show|list|recent|today|inbox|all|within|last|past|from|get|fetch|see|view|any|my\s+(?:gmail|mail|email)|how\s+many|count|\d+\s+days?|\d+\s+hours?)' "$cmd"
end

function _agent_parse_gmail_days --description "Extract day window from NL gmail request (internal)"
    set -l cmd "$argv[1]"
    set -l m (string match -r '(?i)(?:within|last|past)\s+(\d+)\s+days?' "$cmd")
    if test (count $m) -ge 2
        echo $m[2]
        return 0
    end
    set m (string match -r '(?i)\b(\d+)\s+days?\b' "$cmd")
    if test (count $m) -ge 2
        echo $m[2]
        return 0
    end
    set m (string match -r '(?i)(?:within|last|past)\s+(\d+)\s+hours?' "$cmd")
    if test (count $m) -ge 2
        set -l hrs $m[2]
        echo (python3 -c "import math; print(max(1, math.ceil($hrs/24)))")
        return 0
    end
    return 1
end

function _agent_is_google_calendar_request --description "True if user wants Google Calendar (internal)"
    string match -qr '(?i)(google\s+calendar|my\s+calendar|calendar\s+today|calendar\s+this\s+week|what(?:'\''s|\s+is)\s+on\s+my\s+calendar|meetings?\s+today|schedule\s+today|events?\s+today|upcoming\s+meetings?)' "$argv[1]"
end

function _agent_is_agent_hub_request --description "True if user wants Agent Hub sync/launch (internal)"
    string match -qr '(?i)(\bagent\s+hub\b|\barka\s+hub\b|ollama\s+launch|shared\s+mcp\s+for\s+agents?|launch\s+claude\s+code|sync\s+agent\s+hub)' "$argv[1]"
end

function _agent_route_agent_hub --description "Map NL to agent_hub subcommand (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_agent_hub.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo $rest
        return 0
    end
    return 1
end

function _agent_is_mcp_request --description "True if user wants MCP server/tool management (internal)"
    string match -qr '(?i)(\bmcp\b|model\s+context\s+protocol|mcp\s+(?:list|status|tools?|call|add|connect))' "$argv[1]"
end

function _agent_route_mcp --description "Map NL to mcp subcommand (internal)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l rest ($py (_arka_py_script arka_mcp.py) parse (string escape --style=script -- $cmd) 2>/dev/null)
    if test (count $rest) -gt 0
        echo $rest
        return 0
    end
    return 1
end

function _agent_route_google --description "Map NL to google subcommand (internal)"
    set -l cmd "$argv[1]"
    if _agent_is_gmail_draft_request "$cmd"
        echo (_agent_build_gmail_draft_cmd "$cmd")
        return 0
    end
    if _agent_is_google_login_request "$cmd"
        if string match -qr '(?i)\b(setup|configure|config)\b' "$cmd"
            echo "google setup"
        else if string match -qr '(?i)\b(status|connected|signed\s+in)\b' "$cmd"
            echo "google status"
        else if string match -qr '(?i)\b(logout|sign[\s-]?out|disconnect)\b' "$cmd"
            echo "google logout"
        else
            echo "google login"
        end
        return 0
    end
    if _agent_is_google_gmail_request "$cmd"
        echo (_agent_build_gmail_cmd "$cmd")
        return 0
    end
    if _agent_is_gmail_summarize_request "$cmd"
        echo (_agent_build_gmail_cmd "$cmd" summarize)
        return 0
    end
    if _agent_is_google_calendar_request "$cmd"
        if string match -qr '(?i)\b(week|7\s+days)\b' "$cmd"
            echo "google calendar --week"
        else
            echo "google calendar --today"
        end
        return 0
    end
    return 1
end

function _agent_is_whatsapp_inbox_request --description "True if user wants WhatsApp inbox listener"
    string match -qr '(?i)(whatsapp\s+inbox|inbox\s+whatsapp|whatsapp\s+listen|listen\s+whatsapp)' "$argv[1]"
end

function _agent_route_whatsapp_inbox --description "Map NL to whatsapp_listen command"
    set -l cmd "$argv[1]"
    if not _agent_is_whatsapp_inbox_request "$cmd"
        return 1
    end
    if string match -qr '(?i)\bstop\b' "$cmd"
        echo "whatsapp_listen stop"
    else if string match -qr '(?i)\b(status|state)\b' "$cmd"
        echo "whatsapp_listen status"
    else if string match -qr '(?i)\b(fg|foreground)\b' "$cmd"
        echo "whatsapp_listen fg"
    else if string match -qr '(?i)\bdebug\b' "$cmd"
        echo "whatsapp_listen debug"
    else if string match -qr '(?i)\blog\b' "$cmd"
        echo "whatsapp_listen log"
    else
        echo "whatsapp_listen"
    end
end

function _agent_is_aie_request --description "True if user wants Artificial Internet Enhancements"
    string match -qr '(?i)(artificial\s+internet\s+enhance(?:ment?s?)?|internet\s+enhance(?:ment?s?)?|\baie\b)' "$argv[1]"
end

function _agent_route_aie --description "Map AIE natural language to internet_enhance command"
    set -l cmd "$argv[1]"
    if not _agent_is_aie_request "$cmd"
        return 1
    end
    if string match -qr '(?i)\bstart\b' "$cmd"
        echo "internet_enhance start all"
    else if string match -qr '(?i)\b(stop\s+all|stop-all|stop\s+everything|kill\s+all|turn\s+off\s+all)\b' "$cmd"
        echo "internet_enhance stop-all"
    else if string match -qr '(?i)\bstop\b' "$cmd"
        echo "internet_enhance stop all"
    else if string match -qr '(?i)\bcleanup\b' "$cmd"
        echo "internet_enhance cleanup"
    else
        echo "internet_enhance status"
    end
end

function _agent_is_youtube_bulk_request --description "True if user wants YouTube bulk downloader"
    set -l cmd "$argv[1]"
    if string match -qr '(?i)(youtube\s+bulk|yt\s+bulk|bulk\s+download(?:er)?|download\s+(?:a\s+|the\s+|all\s+)?(?:youtube\s+)?(?:playlist|channel)|download\s+all\s+(?:videos\s+)?from\s+(?:channel|playlist|youtube)|youtube\s+bulk\s+downloader|\byt_bulk\b|\byoutube_bulk\b)' "$cmd"
        return 0
    end
    if string match -qr '(?i)(download|save|fetch|grab)\b' "$cmd"
        and string match -qr '(?i)(youtube\.com/playlist|playlist\?list=|/playlist\?list=|watch\?[^\s]*list=)' "$cmd"
        return 0
    end
    return 1
end

function _agent_route_youtube_bulk --description "Map NL to youtube_bulk command (internal)"
    set -l cmd "$argv[1]"
    if not _agent_is_youtube_bulk_request "$cmd"
        return 1
    end
    if string match -qr '(?i)\b(start|launch|run)\b' "$cmd"
        echo "youtube_bulk start"
        return 0
    end
    if string match -qr '(?i)\b(stop)\b' "$cmd"
        echo "youtube_bulk stop"
        return 0
    end
    if string match -qr '(?i)\b(open|ui|web)\b' "$cmd"
        echo "youtube_bulk open"
        return 0
    end
    if string match -qr '(?i)\b(library|downloaded|saved)\b' "$cmd"
        echo "youtube_bulk library"
        return 0
    end
    set -l url (string match -r 'https?://[^\s]+' "$cmd")
    if test (count $url) -lt 1
        set url (string match -r '@[\w.-]+' "$cmd")
    end
    if test (count $url) -ge 1
        set -l dl "youtube_bulk download $url[1] --wait"
        if string match -qr '(?i)\b(channel|@\w)' "$cmd"
            set dl "$dl --channel"
        end
        if string match -qr '(?i)\b(audio|mp3)\b' "$cmd"
            set dl "$dl --audio"
        end
        set -l lim (string match -r '(?i)(?:limit|latest|newest|last)\s+(\d+)' "$cmd")
        if test (count $lim) -ge 2
            set dl "$dl --limit $lim[2]"
        end
        echo $dl
        return 0
    end
    echo "youtube_bulk status"
end

function _agent_is_youtube_download_request --description "True if user wants to download a single YouTube video"
    set -l cmd "$argv[1]"
    if _agent_is_youtube_bulk_request "$cmd"
        return 1
    end
    if string match -qr '(?i)(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)' "$cmd"
        if string match -qr '(?i)(download|save|fetch|grab)\b' "$cmd"
            return 0
        end
    end
    if string match -qr '(?i)(download|save|fetch|grab)\b' "$cmd"
        if string match -qr '(?i)(youtube\.com|youtu\.be)' "$cmd"
            if string match -qr '(?i)playlist\?list=' "$cmd"
                and not string match -qr '(?i)watch\?v=' "$cmd"
                return 1
            end
            return 0
        end
        if string match -qr '(?i)(youtube\s+video|video\s+from\s+youtube|youtube\s+url|youtube\s+shorts?)' "$cmd"
            return 0
        end
    end
    return 1
end

function _agent_route_youtube_download --description "Map NL to youtube_download command (internal)"
    set -l cmd "$argv[1]"
    if not _agent_is_youtube_download_request "$cmd"
        return 1
    end
    set -l url (string match -r 'https?://[^\s]+' "$cmd")
    if test (count $url) -lt 1
        set url (string match -r '(?i)\b[A-Za-z0-9_-]{11}\b' "$cmd")
    end
    if test (count $url) -ge 1
        set -l dl "youtube_download $url[1]"
        if string match -qr '(?i)\b(audio|mp3)\b' "$cmd"
            set dl "$dl --audio"
        end
        echo $dl
        return 0
    end
    echo "youtube_download"
end

function _agent_chat_intent_route --description "Map question to chat skill via arka_chat intent (internal)"
    set -l cmd (string trim -- "$argv[1]")
    test -z "$cmd"; and return 1
    if _agent_is_daily_brief_request "$cmd"
        return 1
    end
    if string match -qr '(?i)(password|passcode)' "$cmd"
        and not string match -qr '(?i)(decrypt|protected|pdf)' "$cmd"
        return 1
    end
    if _agent_is_google_login_request "$cmd"
        or _agent_is_google_gmail_request "$cmd"
        or _agent_is_google_calendar_request "$cmd"
        return 1
    end
    if string match -qr '^/' "$cmd"
        set -l forced (string trim (string replace -r '^/+?' '' "$cmd"))
        test -z "$forced"; and set forced $cmd
        echo "deep_web_answer $forced"
        return 0
    end
    set -l intent (python3 (_arka_py_script arka_chat.py) intent "$cmd" 2>/dev/null)
    test -z "$intent"; and return 1
    set -l action (string split -f 1 \t "$intent")
    switch $action
        case SEARCH
            echo "web_answer $cmd"
        case CALC
            echo "calc $cmd"
        case WEATHER
            echo "hyperlocal_weather $cmd"
        case ERROR
            echo "error_helper $cmd"
        case '*'
            return 1
    end
end

function _agent_looks_like_shell_cmd --description "True if input is likely a shell command, not chat (internal)"
    set -l cmd (string trim -- "$argv[1]")
    set -l words (string split " " "$cmd")
    test (count $words) -eq 0; and return 1
    if _agent_is_general_chat "$cmd"
        return 1
    end
    if test (count $words) -eq 1
        type -q "$words[1]"
        return $status
    end
    string match -qr '(?i)^(sudo|cd|ls|cat|grep|find|apt|pip|npm|uv|git|curl|wget|python|fish|echo|export|mkdir|cp|mv|rm|chmod|chown|systemctl|docker|kubectl|make|cmake|cargo|go|node|npm|npx|pnpm|yarn|brew|snap|flatpak)\s' "$cmd"
    return $status
end

function _agent_ask_gather_exec --description "Run AI-chosen gather cmd (read-only; allows 2>/dev/null)"
    set -l cmd (string trim -- "$argv[1]")
    test -z "$cmd"; and return 1

    if __agent_classify "$cmd"
        _arka_run_shell_string "$cmd" 2>&1
        return $status
    end

    set -l low (string lower "$cmd")
    if string match -qr '(sudo|\brm\b|\bmv\b|\bchmod\b|\bchown\b|\bdd\b|\bmkfs\b|\bkill\b|\bapt\b|\binstall\b|\bpip\b|\bnpm\b|\bshutdown\b|\breboot\b|sed -i|>\s*[^/])' "$low"
        echo "[skipped: not read-only]"
        return 2
    end
    if string match -qr '(?i)^(lscpu|grep|free|df |du |lsblk|lspci|uname|cat |head |tail |wc |uptime|lsb_release|sysctl|sw_vers|vm_stat|system_profiler|lsappinfo|ioreg|command |eza |batcat |rg |fd |nvidia-smi|glxinfo|vulkaninfo|ls |find |stat |file |which |type |ps |ss |netstat|lsof |journalctl|systemctl |last |w |who |dpkg -l|snap list|flatpak list|clamscan|freshclam|rkhunter|chkrootkit|crontab -l|python3.*arka_usage\.py|app_usage)' "$low"
        _arka_run_shell_string "$cmd" 2>&1
        return $status
    end
    if string match -qr '(?i)(/proc/|/sys/|/etc/os-release|cpuinfo|meminfo|/var/log/)' "$low"
        _arka_run_shell_string "$cmd" 2>&1
        return $status
    end

    echo "[skipped: not read-only]"
    return 2
end

function _agent_ask_gather_context --description "AI chooses read-only shell commands to gather facts for a question"
    set -l question $argv[1]
    set -l max 6
    if test -n "$argv[2]"
        set max $argv[2]
    end

    set -l cwd (pwd)
    set -l history_text ""
    set -l iter 0
    set -l gathered 0

    set -l system_text "You gather system facts to answer an advisory question.
Each turn return ONLY JSON (no markdown fences):
{\"status\":\"continue\"|\"done\",\"cmd\":\"one read-only shell command or empty\",\"why\":\"brief reason\"}

Rules:
- Pick commands relevant to the QUESTION and the host OS.
- Linux: lscpu, /proc/cpuinfo, free -h, df -h, lspci, lsblk, uname -a, /etc/os-release, ps, ss, journalctl, systemctl status/list, last, crontab -l.
- macOS: sw_vers, sysctl, vm_stat, df -h, system_profiler SPDisplaysDataType, uname -a, ps aux, lsof.
- READ-ONLY only. NO sudo, rm, mv, chmod, install, apt, pip, or any write/destructive action.
- One command per turn. Use status \"done\" with empty cmd when you have enough facts (usually after 2-5 commands).
- Commands run in fish shell.
- (_arka_agent_platform_hint)"

    printf '%s%s%s\n' (set_color brblack) "  AI choosing context commands..." (set_color normal) >&2

    while test $iter -lt $max
        set iter (math $iter + 1)
        set -l prior "(nothing yet)"
        if test -n "$history_text"
            set prior "$history_text"
        end
        set -l user_text "QUESTION: $question
CWD: $cwd

ALREADY GATHERED:
$prior

Step $iter/$max — return the next gather command as JSON, or {\"status\":\"done\",\"cmd\":\"\",\"why\":\"enough facts\"}."

        set -l ai_raw (_agent_llm_complete "$system_text" "$user_text")
        if test -z "$ai_raw"
            set ai_raw (_agent_llm_complete "$system_text" "$user_text")
        end
        if test -z "$ai_raw"
            printf '%s%s%s\n' (set_color yellow) "  LLM returned no gather step; stopping early." (set_color normal) >&2
            break
        end

        _agent_loop_parse_step "$ai_raw"
        set -l step_status $_loop_status
        set -l step_cmd $_loop_cmd
        set -l step_why $_loop_why

        if test "$step_status" = done
            if test -n "$step_why"
                printf '%s%s%s\n' (set_color brblack) "  Done gathering: $step_why" (set_color normal) >&2
            end
            break
        end

        if test -z "$step_cmd"
            break
        end

        printf '%s%s%s\n' (set_color cyan) "  ▶ $step_cmd" (set_color normal) >&2
        if test -n "$step_why"
            printf '%s%s%s\n' (set_color brblack) "    $step_why" (set_color normal) >&2
        end

        set -l out (_agent_ask_gather_exec "$step_cmd")
        set -l exit_code $status
        set gathered 1

        if test $exit_code -eq 2
            printf '%s%s%s\n' (set_color yellow) "    ⊘ skipped (not safe/read-only)" (set_color normal) >&2
        else if test $exit_code -ne 0
            printf '%s%s%s\n' (set_color yellow) "    ✗ exit $exit_code" (set_color normal) >&2
        end

        set -l out_store (printf '%s\n' "$out" | head -30)
        set -l nlines (printf '%s\n' "$out" | wc -l)
        if test $nlines -gt 30
            set out_store "$out_store
... (truncated, $nlines lines total)"
        end

        if test -n "$out"
            printf '%s\n' "$out" | head -8 | sed 's/^/    /' >&2
            if test $nlines -gt 8
                printf '%s%s%s\n' (set_color brblack) "    ... ($nlines lines)" (set_color normal) >&2
            end
        end

        set history_text "$history_text
--- gather $iter ---
cmd: $step_cmd
exit: $exit_code
why: $step_why
output:
$out_store
"
    end

    if test $gathered -eq 0
        if _agent_is_knowledge_question "$question"
            printf '%s%s%s\n' (set_color brblack) "  General knowledge — no system probes needed." (set_color normal) >&2
        else if test -n "$step_why"; and string match -qr '(?i)(subjective|personal context|general knowledge|not system|no system|cannot help|does not require|doesn'\''t require|not.*system facts)' "$step_why"
            printf '%s%s%s\n' (set_color brblack) "  Not a system question — skipping probes." (set_color normal) >&2
        else if _arka_is_macos
            printf '%s%s%s\n' (set_color brblack) "  Using default macOS system probes..." (set_color normal) >&2
            for cmd in \
                    "sw_vers" \
                    "sysctl -n machdep.cpu.brand_string hw.memsize hw.ncpu" \
                    "vm_stat" \
                    "df -h /" \
                    "system_profiler SPDisplaysDataType 2>/dev/null | head -20"
                printf '%s%s%s\n' (set_color cyan) "  ▶ $cmd" (set_color normal) >&2
                set -l out (_agent_ask_gather_exec "$cmd")
                set history_text "$history_text
--- default ---
cmd: $cmd
output:
$out
"
            end
        else
            printf '%s%s%s\n' (set_color brblack) "  Using default system probes..." (set_color normal) >&2
            for cmd in \
                    "grep -m1 'model name' /proc/cpuinfo" \
                    "lscpu 2>/dev/null | head -25" \
                    "free -h" \
                    "df -h /" \
                    "lspci 2>/dev/null | rg -i 'vga|3d|display' | head -3" \
                    "lsb_release -ds 2>/dev/null"
                printf '%s%s%s\n' (set_color cyan) "  ▶ $cmd" (set_color normal) >&2
                set -l out (_agent_ask_gather_exec "$cmd")
                set history_text "$history_text
--- default ---
cmd: $cmd
output:
$out
"
            end
        end
    end

    printf '%s' "$history_text"
end

function _agent_advise_offline --description "Heuristic hardware advice when AI is unavailable"
    set -l question (string lower "$argv[1]")
    set -l ctx "$argv[2]"
    echo (set_color --bold blue)"━━━ Local advisory (AI unavailable) ━━━"(set_color normal)
    printf "%s\n" "$ctx"
    echo ""
    set -l cpu_line (echo "$ctx" | string match -r 'CPU:.*')
    if string match -qr '(?i)(outdated|too\s+old|upgrade)' "$question"
        if string match -qr 'i3-7020U|7020U' "$cpu_line"
            echo "Intel Core i3-7020U (7th gen, ~2017): fine for browsing, docs, and light dev."
            echo "It is weak for gaming, video editing, and heavy IDEs — the Intel HD 620 GPU is usually the limit."
            echo "Upgrade only if your actual workload feels slow; RAM (8GB+) and an SSD matter more than replacing the CPU alone."
            return 0
        else if string match -qr 'i[3579]-[0-9]{4,5}[A-Z]?|Core\(TM\)' "$cpu_line"
            echo "This is a laptop-class Intel CPU. For everyday Linux use it is likely still adequate."
            echo "For gaming, VMs, or heavy compile jobs, compare against recommended specs for that software."
            return 0
        end
    end
    echo (set_color yellow)"Set GEMINI_API_KEY or GROQ_API_KEY, or run: ollama serve"(set_color normal)
    echo (set_color brblack)"Then retry: agent_ask $argv[1]"(set_color normal)
    return 1
end

function _arka_answer_ok --description "True if arka_chat answer is usable (internal)"
    set -l a "$argv[1]"
    test -z "$a"; and return 1
    string match -qr '(?i)^could not (generate|get|analyze)' "$a"; and return 1
    return 0
end

function _arka_web_answer_llm_fallback --description "Snippet + LLM when arka_chat returned nothing (internal)"
    set -l question "$argv[1]"
    set -l py (_arka_python)
    set -l snippet ($py (_arka_py_script web_answer.py) snippet "$question" 2>/dev/null)
    set -l plat (_arka_agent_platform_label)
    set -l ui_hint (_arka_platform_ui_shortcuts)
    set -l system_text "You are a helpful assistant. Answer clearly in 2-5 short sentences for TTS. Start with [FROM MEMORY] or [FROM SEARCH]. Be factual. The user is on $plat. $ui_hint When the question is about app/window UI, answer ONLY for $plat — do not list other OSes."
    set -l user_text "Question: $question"
    if test -n "$snippet"
        set user_text "Web snippet:\n$snippet\n\nQuestion: $question"
    end
    set -l answer (_arka_capture_output _agent_llm_complete "$system_text" "$user_text")
    if test -n "$answer"
        _arka_print_answer_block "$answer"
        return 0
    end
    if test -n "$snippet"
        _arka_print_answer_block "$snippet"
        return 0
    end
    return 1
end

function _arka_chat_ask --description "Run arka_chat.py ask; prints answer (internal)"
    argparse 'd/deep' 'n/no-session' -- $argv
    or return 1
    if not _arka_ensure_venv
        return 1
    end
    set -l py_args ask
    test -n "$_flag_d"; and set -a py_args --deep
    test -n "$_flag_n"; and set -a py_args --no-session
    set -l question (_agent_with_voice_context (string join " " $argv))
    set -a py_args "$question"
    set -l py (_arka_python)
    $py (_arka_py_script arka_chat.py) $py_args
end

function deep_web_answer --description "Deep web search + scrape RAG answer"
    if test (count $argv) -eq 0
        echo "Usage: deep_web_answer <question>"
        return 1
    end
    set -l question (string join " " $argv)
    if not _arka_verify_web_query "$question"
        return 1
    end
    _arka_ui_header "Deep search: $question" query
    set -l answer (_arka_capture_output _arka_chat_ask --deep $argv)
    if test -z "$answer"
        echo (set_color red)"Deep search failed (check API keys / network / pip: ddgs trafilatura beautifulsoup4)"(set_color normal) >&2
        echo (set_color brblack)"Tip: run the same question with web_answer (without --deep) or check keys in .env"(set_color normal) >&2
        return 1
    end
    _arka_print_answer_block "$answer"
end

function calc --description "Symbolic math via SymPy + AI explanation"
    if test (count $argv) -eq 0
        echo "Usage: calc <expression or math question>"
        echo "Example: calc integrate sin(x) dx"
        return 1
    end
    set -l expr (string join " " $argv)
    _arka_ui_header "$expr" math
    set -l answer (_arka_capture_output python3 (_arka_py_script arka_chat.py) ask $argv)
    if test -z "$answer"
        set -l raw (python3 (_arka_py_script arka_chat.py) calc $argv 2>/dev/null)
        test -n "$raw"; and echo "[FROM MEMORY] $raw"; and return 0
        echo (set_color red)"Calc failed (pip install sympy)"(set_color normal)
        return 1
    end
    _arka_print_answer_block "$answer"
end

function chat_reset --description "Reset Arka chat session and location context"
    python3 (_arka_py_script arka_chat.py) session-reset
end

function set_location --description "Set or refresh location/PIN for grounded search"
    if test (count $argv) -eq 0
        python3 (_arka_py_script arka_chat.py) location --refresh
        return $status
    end
    python3 (_arka_py_script arka_chat.py) location $argv[1]
end

function nearby_places --description "Offline nearby POIs from cached city map (OpenStreetMap + distance)"
    set -l out (_arka_capture_output python3 (_arka_py_script arka_chat.py) nearby $argv)
    if test -z "$out"
        echo (set_color red)"No nearby data — try: map_download <city>"(set_color normal)
        return 1
    end
    _arka_ui_header "Nearby (offline map)" places
    echo ""
    _arka_print_answer "$out"
end

function map_download --description "Download offline POI map for a city (Overpass/OSM)"
    if test (count $argv) -eq 0
        echo "Usage: map_download <city>"
        return 1
    end
    python3 (_arka_py_script arka_chat.py) map download $argv[1]
end

function error_helper --description "Explain a Python/shell error or traceback"
    if test (count $argv) -eq 0
        echo "Usage: error_helper <error text>"
        echo "Example: error_helper (python3 script.py 2>&1 | tail -20)"
        return 1
    end
    set -l text (string join " " $argv)
    _arka_ui_header "Analyzing error…" error
    set -l answer (_arka_capture_output python3 (_arka_py_script arka_chat.py) error-explain $argv)
    if test -z "$answer"
        echo (set_color red)"Could not analyze error"(set_color normal)
        return 1
    end
    _arka_print_answer_block "$answer" "Error help"
end

function deep_queue --description "Background deep-search queue (add/list/run/results)"
    if test (count $argv) -eq 0
        echo "Usage: deep_queue add|list|run|results [task]"
        return 1
    end
    switch $argv[1]
        case add
            if test (count $argv) -lt 2
                echo "Usage: deep_queue add <question>"
                return 1
            end
            python3 (_arka_py_script arka_chat.py) queue add $argv[2..-1]
        case list
            python3 (_arka_py_script arka_chat.py) queue list
        case run
            python3 (_arka_py_script arka_chat.py) queue run
        case results
            python3 (_arka_py_script arka_chat.py) queue results
        case '*'
            echo "Usage: deep_queue add|list|run|results"
            return 1
    end
end

function _arka_agent --description "Run arka_agent.py subcommand (internal)"
    set -l py (_arka_python)
    set -l sub "$argv[1]"
    switch $sub
        case research ask
            set -l raw (_arka_capture_output $py (_arka_py_script arka_agent.py) $argv)
            set -l st $status
            if test -n "$raw"
                _arka_pretty_python_output "$raw"
            end
            return $st
        case '*'
            $py (_arka_py_script arka_agent.py) $argv
    end
end

function _arka_memory_detect_fact --description "Symbolic autodetect of memorable facts (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_memory_detect.py) extract --quiet (string join " " $argv) 2>/dev/null
end

function _arka_memory_probe --description "Set _arka_last_mem_fact if NL asserts a personal fact (internal)"
    set -g _arka_last_mem_fact (_arka_memory_detect_fact $argv[1])
    test -n "$_arka_last_mem_fact"
end

function agent_remember --description "Store a long-term memory for Arka"
    if test (count $argv) -eq 0
        echo "Usage: agent_remember <fact or preference>"
        return 1
    end
    _arka_agent remember (string join " " $argv)
end

function agent_recall --description "Recall memories matching a query"
    if test (count $argv) -eq 0
        agent_memory list
        return $status
    end
    _arka_agent recall (string join " " $argv)
end

function agent_memory --description "List or manage long-term agent memory"
    if test (count $argv) -eq 0; or test "$argv[1]" = list
        _arka_agent memory-list
    else if test "$argv[1]" = forget
        if test (count $argv) -lt 2
            echo "Usage: agent_memory forget <id or text fragment>"
            return 1
        end
        _arka_agent forget $argv[2]
    else
        _arka_agent memory-list
    end
end

function agent_trace --description "Show last routing decision"
    _arka_agent trace-last
end

function agent_why --description "Explain why Arka routed your last request"
    _arka_agent trace-why
end

function agent_last --description "Alias for agent_trace"
    agent_trace $argv
end

function agent_resume --description "Resume or list saved agent_loop states"
    if test (count $argv) -eq 0; or test "$argv[1]" = list
        _arka_agent loop-list
    else if test "$argv[1]" = clear
        _arka_agent loop-clear $argv[2]
    else
        set -l sid $argv[1]
        set -l state (_arka_agent loop-load $sid)
        if test -z "$state" -o "$state" = "{}"
            echo (set_color red)"No saved loop state for: $sid"(set_color normal)
            return 1
        end
        set -l goal (printf '%s' "$state" | jq -r '.goal // empty')
        set -l saved_iter (printf '%s' "$state" | jq -r '.iter // 0')
        set -l max_iter (printf '%s' "$state" | jq -r '.max_iter // 12')
        set -l remain (math $max_iter - $saved_iter)
        test $remain -lt 1; and set remain 1
        echo (set_color cyan)"Resuming loop: $goal (from step $saved_iter)"(set_color normal)
        agent_loop -n $remain --resume-id $sid $goal
    end
end

function agent_research --description "Unified research: TurboQuant + web + media"
    if test (count $argv) -eq 0
        echo "Usage: agent_research [--deep] [--light] [--doc DOC] [--path FILE] <question>"
        return 1
    end
    set -l flags
    set -l args $argv
    set -l light false
    while test (count $args) -gt 0
        switch $args[1]
            case --deep -d
                set -a flags --deep
                set args $args[2..-1]
            case --light --snippet -s
                set light true
                set args $args[2..-1]
            case --doc
                set -a flags --doc $args[2]
                set args $args[3..-1]
            case --path
                set -a flags --path $args[2]
                set args $args[3..-1]
            case '*'
                break
        end
    end
    if test "$light" != true; and not contains -- --deep $flags
        set -a flags --deep
    end
    set -l question (string join " " $args)
    _arka_ui_header "Research: $question" query
    _arka_agent research $flags $question
end

function agent_nudge --description "Proactive hints (disk, queue, handoff)"
    _arka_agent nudge $argv
end

function agent_watch --description "Condition → action watches"
    if test (count $argv) -eq 0
        echo "Usage: agent_watch add|list|run|remove ..."
        return 1
    end
    switch $argv[1]
        case add
            if test (count $argv) -lt 4
                echo "Usage: agent_watch add \"<condition>\" \"<action>\""
                echo "  Conditions: disk >90%, file exists PATH, process NAME, queue pending >0"
                return 1
            end
            _arka_agent watch-add $argv[2] $argv[3]
        case list ls
            _arka_agent watch-list
        case run check
            _arka_agent watch-run
        case remove rm delete
            _arka_agent watch-remove $argv[2]
        case '*'
            echo "Usage: agent_watch add|list|run|remove"
            return 1
    end
end

function agent_routine --description "Scheduled agent tasks (systemd timers)"
    if test (count $argv) -eq 0
        echo "Usage: agent_routine add|list|install|remove ..."
        return 1
    end
    switch $argv[1]
        case add
            if test (count $argv) -lt 4
                echo "Usage: agent_routine add \"daily|hourly|HH:MM\" \"command\""
                return 1
            end
            _arka_agent routine-add $argv[2] $argv[3]
        case list ls
            _arka_agent routine-list
        case install enable
            _arka_agent routine-install
        case remove rm
            _arka_agent routine-remove $argv[2]
        case '*'
            echo "Usage: agent_routine add|list|install|remove"
            return 1
    end
end

function agent_fanout --description "Run parallel agent jobs and optionally merge"
    if test (count $argv) -eq 0
        echo "Usage: agent_fanout [--merge \"question\"] job1 job2 ..."
        return 1
    end
    set -l merge ""
    set -l jobs $argv
    if test "$argv[1]" = --merge
        set merge $argv[2]
        set jobs $argv[3..-1]
    end
    if test (count $jobs) -eq 0
        echo "Usage: agent_fanout [--merge \"question\"] job1 job2 ..."
        return 1
    end
    if test -n "$merge"
        _arka_agent fanout --merge "$merge" $jobs
    else
        _arka_agent fanout $jobs
    end
end

function agent_code --description "Repo-scoped coding agent with TurboQuant context"
    if test (count $argv) -eq 0
        echo "Usage: agent_code [--ingest] [--repo PATH] <goal>"
        return 1
    end
    set -l flags
    set -l args $argv
    while test (count $args) -gt 0
        switch $args[1]
            case --ingest
                set -a flags --ingest
                set args $args[2..-1]
            case --repo
                set -a flags --repo $args[2]
                set args $args[3..-1]
            case '*'
                break
        end
    end
    _arka_agent code $flags (string join " " $args)
end

function agent_handoff --description "Phone ↔ PC shared task queue"
    if test (count $argv) -eq 0
        echo "Usage: agent_handoff add|list|run|clear [task]"
        return 1
    end
    switch $argv[1]
        case add queue
            if test (count $argv) -lt 2
                echo "Usage: agent_handoff add <task>"
                return 1
            end
            _arka_agent handoff-add (string join " " $argv[2..-1])
        case list ls
            _arka_agent handoff-list
        case run
            set -l py (_arka_python)
            $py (_arka_py_script arka_talents.py) handoff-run-notify
        case notify notifications
            set -l py (_arka_python)
            if test (count $argv) -ge 2; and test "$argv[2]" = read
                $py (_arka_py_script arka_talents.py) handoff-notify-read $argv[3]
            else
                $py (_arka_py_script arka_talents.py) handoff-notify-list --unread
            end
        case clear
            _arka_agent handoff-clear
        case '*'
            echo "Usage: agent_handoff add|list|run|clear"
            return 1
    end
end

function agent_browser --description "Goal-oriented web research agent"
    if test (count $argv) -eq 0
        echo "Usage: agent_browser <goal>"
        return 1
    end
    _arka_agent browser (string join " " $argv)
end

function transcript_ask --description "Ask questions about a media transcript"
    if test (count $argv) -lt 2
        echo "Usage: transcript_ask <media-file> <question>"
        return 1
    end
    _arka_agent transcript-ask $argv[1] $argv[2..-1]
end

function media_ask --description "Alias for transcript_ask"
    transcript_ask $argv
end

function meeting_agent --description "Extract action items from meeting notes"
    if test (count $argv) -eq 0
        echo "Usage: meeting_agent <notes or paste>"
        return 1
    end
    _arka_agent meeting (string join " " $argv)
end

function study_agent --description "Study tutor mode with web + docs"
    if test (count $argv) -eq 0
        echo "Usage: study_agent <topic or question>"
        return 1
    end
    _arka_agent study (string join " " $argv)
end

function inbox_agent --description "Triage inbox or message backlog"
    if test (count $argv) -eq 0
        echo "Usage: inbox_agent <messages or description>"
        return 1
    end
    _arka_agent inbox (string join " " $argv)
end

function compare_agent --description "Compare two topics with web research"
    if test (count $argv) -lt 2
        echo "Usage: compare_agent <topic A> <topic B>"
        return 1
    end
    _arka_agent compare $argv[1] $argv[2]
end

function product_reviewer --description "Review product ingredients with web research"
    if test (count $argv) -eq 0
        echo "Usage: product_reviewer <ingredients or product name> [what you want to know]"
        return 1
    end
    _arka_agent product-reviewer (string join " " $argv)
end

function price_check --description "Look up current retail product prices"
    if test (count $argv) -eq 0
        echo "Usage: price_check <product> [e.g. macbook air m3 | iphone 16 price in india]"
        return 1
    end
    _arka_agent price-check (string join " " $argv)
end

function rag_setup --description "Install Firmamento TurboQuant for unified RAG"
    argparse q/quiet -- $argv
    or return 1
    set -l py (_arka_python)
    set -l flags install
    test -n "$_flag_q"; and set -a flags --quiet
    $py (_arka_py_script arka_turboquant_install.py) $flags
end

function rag_status --description "Check TurboQuant RAG backend status"
    set -l py (_arka_python)
    $py (_arka_py_script arka_turboquant_install.py) check
end

function google --description "Google Calendar and Gmail — login, status, mail, calendar"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_google.py) help
        return $status
    end
    $py (_arka_py_script arka_google.py) $argv
end

function agent_hub --description "Shared MCP, memory, and skills for ollama launch agents"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_agent_hub.py) help
        return $status
    end
    $py (_arka_py_script arka_agent_hub.py) $argv
end

function mcp --description "Model Context Protocol — list, add, tools, call, status"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_mcp.py) help
        return $status
    end
    $py (_arka_py_script arka_mcp.py) $argv
end

function gemini_cli --description "Google Gemini CLI agent (@google/gemini-cli)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_gemini.py) --help
        return $status
    end
    $py (_arka_py_script arka_gemini.py) $argv
end

function voice_agent --description "Multi-turn voice chat via wake listener"
    if test (count $argv) -eq 0
        echo "Usage: voice_agent start|stop|status"
        echo "  Or say wake word + question (AGENT_WAKE_AUTO=1)"
        _agent_listen_status
        return 0
    end
    switch $argv[1]
        case start on
            _agent_listen_start $argv[2..-1]
        case stop off
            _agent_listen_stop
        case status
            _agent_listen_status
        case '*'
            agent_ask $argv
    end
end

function wake_control --description "Control wake-word listener"
    if test (count $argv) -eq 0
        _agent_listen_status
        return 0
    end
    switch $argv[1]
        case start on enable
            _agent_listen_start $argv[2..-1]
        case stop off disable
            _agent_listen_stop
        case status
            _agent_listen_status
        case debug
            _agent_listen_start debug
        case '*'
            _agent_try_listen_control (string join " " $argv)
    end
end

function _arka_talents --description "Run arka_talents.py (internal)"
    set -l py (_arka_python)
    $py (_arka_py_script arka_talents.py) $argv
end

function arka_ask --description "Unified brain: semantic memory + TurboQuant + web + optional YouTube"
    if test (count $argv) -eq 0
        echo "Usage: arka_ask [--deep] [--youtube] [--speak] [--doc DOC] <question>"
        echo "Example: arka_ask how does routing work in config.fish"
        echo "Example: arka_ask --youtube --speak macbook air review"
        return 1
    end
    set -l flags
    set -l args $argv
    while test (count $args) -gt 0
        switch $args[1]
            case --deep -d
                set -a flags --deep
                set args $args[2..-1]
            case --youtube -y
                set -a flags --youtube
                set args $args[2..-1]
            case --speak -s
                set -a flags --speak
                set args $args[2..-1]
            case --doc
                set -a flags --doc $args[2]
                set args $args[3..-1]
            case '*'
                break
        end
    end
    _arka_talents ask $flags (string join " " $args)
end

function semantic_memory --description "Remember with TurboQuant semantic indexing"
    if test (count $argv) -eq 0
        echo "Usage: semantic_memory remember|recall|reindex [text|query]"
        return 1
    end
    switch $argv[1]
        case remember mem add
            _arka_talents semantic-remember (string join " " $argv[2..-1])
        case recall search
            _arka_talents semantic-recall (string join " " $argv[2..-1])
        case reindex sync
            _arka_talents memory-reindex
        case list
            agent_memory list
        case '*'
            _arka_talents semantic-remember (string join " " $argv)
    end
end

function supermemory --description "Supermemory cloud memory with local fallback"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_supermemory.py) status
        echo ""
        echo "Usage: supermemory remember|recall|list|status|forget [text|query|id]"
        return 0
    end
    switch $argv[1]
        case remember mem add save store
            if test (count $argv) -lt 2
                echo "Usage: supermemory remember <fact>"
                return 1
            end
            $py (_arka_py_script arka_supermemory.py) remember (string join " " $argv[2..-1])
        case recall search find query
            if test (count $argv) -lt 2
                $py (_arka_py_script arka_supermemory.py) recall
            else
                $py (_arka_py_script arka_supermemory.py) recall (string join " " $argv[2..-1])
            end
        case list ls
            $py (_arka_py_script arka_supermemory.py) list
        case status mode backend
            $py (_arka_py_script arka_supermemory.py) status
        case forget delete remove
            if test (count $argv) -lt 2
                echo "Usage: supermemory forget <id or text fragment>"
                return 1
            end
            $py (_arka_py_script arka_supermemory.py) forget $argv[2]
        case context ctx
            if test (count $argv) -lt 2
                echo "Usage: supermemory context <goal>"
                return 1
            end
            $py (_arka_py_script arka_supermemory.py) context (string join " " $argv[2..-1])
        case '*'
            $py (_arka_py_script arka_supermemory.py) $argv
    end
end

function speak_research --description "YouTube research digest spoken aloud (Hindi/English TTS)"
    if test (count $argv) -eq 0
        echo "Usage: speak_research [--limit N] [--no-speak] <search query>"
        echo "Example: speak_research macbook air review"
        return 1
    end
    set -l limit 5
    set -l flags
    set -l args $argv
    while test (count $args) -gt 0
        switch $args[1]
            case --limit -n
                set limit $args[2]
                set args $args[3..-1]
            case --no-speak
                set -a flags --no-speak
                set args $args[2..-1]
            case '*'
                break
        end
    end
    _arka_talents speak-research --limit $limit $flags (string join " " $args)
end

function voice_session --description "Multi-turn voice conversation context"
    if test (count $argv) -eq 0
        _arka_talents voice-status
        return $status
    end
    switch $argv[1]
        case clear reset end stop
            _arka_talents voice-clear
        case status
            _arka_talents voice-status
        case '*'
            echo "Usage: voice_session clear|status"
    end
end

function handoff_notify --description "Handoff notifications for phone (list/read/run)"
    if test (count $argv) -eq 0
        echo "Usage: handoff_notify list|read|run"
        return 1
    end
    switch $argv[1]
        case list ls
            _arka_talents handoff-notify-list --unread
        case read
            _arka_talents handoff-notify-read $argv[2]
        case run
            _arka_talents handoff-run-notify
        case '*'
            echo "Usage: handoff_notify list|read [id]|run"
    end
end

function session_memory --description "OpenClaw-style markdown session memory (MEMORY.md + daily notes)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_session_memory.py) status
        echo ""
        echo "Usage: session_memory append|search|context|status [text|query|goal]"
        return 0
    end
    switch $argv[1]
        case append remember note add
            if test (count $argv) -lt 2
                echo "Usage: session_memory append <note>"
                return 1
            end
            $py (_arka_py_script arka_session_memory.py) append (string join " " $argv[2..-1])
        case search find
            if test (count $argv) -lt 2
                $py (_arka_py_script arka_session_memory.py) search
            else
                $py (_arka_py_script arka_session_memory.py) search (string join " " $argv[2..-1])
            end
        case context ctx
            if test (count $argv) -lt 2
                echo "Usage: session_memory context <goal>"
                return 1
            end
            $py (_arka_py_script arka_session_memory.py) context (string join " " $argv[2..-1])
        case status
            $py (_arka_py_script arka_session_memory.py) status
        case '*'
            $py (_arka_py_script arka_session_memory.py) $argv
    end
end

function heartbeat --description "Agent health — last activity, routines, memory stats"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_heartbeat.py) status
        return $status
    end
    switch $argv[1]
        case ping touch
            if test (count $argv) -ge 2
                $py (_arka_py_script arka_heartbeat.py) ping (string join " " $argv[2..-1])
            else
                $py (_arka_py_script arka_heartbeat.py) ping manual.ping
            end
        case status health
            $py (_arka_py_script arka_heartbeat.py) status
        case '*'
            $py (_arka_py_script arka_heartbeat.py) $argv
    end
end

function webhook --description "Verified webhook ingress for external channels (opt-in)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_webhook.py) status
        echo ""
        echo "Usage: webhook serve | status"
        echo "Set WEBHOOK_ENABLED=1 and WEBHOOK_TOKEN in .env first."
        return 0
    end
    switch $argv[1]
        case serve start run
            $py (_arka_py_script arka_webhook.py) serve
        case status
            $py (_arka_py_script arka_webhook.py) status
        case '*'
            $py (_arka_py_script arka_webhook.py) $argv
    end
end

function message_session --description "Per-channel message sessions (cross-platform continuity)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_message_sessions.py) status
        echo ""
        echo "Usage: message_session push|context|resume|reset|list|status [channel chat_id ...]"
        return 0
    end
    switch $argv[1]
        case push
            if test (count $argv) -lt 5
                echo "Usage: message_session push <channel> <chat_id> <user|assistant|system> <text>"
                return 1
            end
            $py (_arka_py_script arka_message_sessions.py) push $argv[2] $argv[3] $argv[4] (string join " " $argv[5..-1])
        case context ctx
            if test (count $argv) -lt 3
                echo "Usage: message_session context <channel> <chat_id>"
                return 1
            end
            $py (_arka_py_script arka_message_sessions.py) context $argv[2] $argv[3]
        case resume show
            if test (count $argv) -lt 3
                echo "Usage: message_session resume <channel> <chat_id>"
                return 1
            end
            $py (_arka_py_script arka_message_sessions.py) resume $argv[2] $argv[3]
        case reset new clear
            if test (count $argv) -lt 3
                echo "Usage: message_session reset <channel> <chat_id>"
                return 1
            end
            $py (_arka_py_script arka_message_sessions.py) reset $argv[2] $argv[3]
        case list ls
            $py (_arka_py_script arka_message_sessions.py) list
        case status
            if test (count $argv) -ge 3
                $py (_arka_py_script arka_message_sessions.py) status $argv[2] $argv[3]
            else
                $py (_arka_py_script arka_message_sessions.py) status
            end
        case '*'
            $py (_arka_py_script arka_message_sessions.py) $argv
    end
end

function unified_memory --description "Unified memory facade (facts + notes + channel turns)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_unified_memory.py) status
        echo ""
        echo "Usage: unified_memory remember|recall|status [text|goal] [--layer fact|note|channel|auto]"
        return 0
    end
    switch $argv[1]
        case remember store save
            if test (count $argv) -lt 2
                echo "Usage: unified_memory remember <text> [--layer fact|note|channel|auto] [--long-term]"
                return 1
            end
            $py (_arka_py_script arka_unified_memory.py) remember (string join " " $argv[2..-1])
        case recall context ctx
            if test (count $argv) -lt 2
                echo "Usage: unified_memory recall <goal>"
                return 1
            end
            $py (_arka_py_script arka_unified_memory.py) recall (string join " " $argv[2..-1])
        case status
            $py (_arka_py_script arka_unified_memory.py) status
        case '*'
            $py (_arka_py_script arka_unified_memory.py) $argv
    end
end

function subagent --description "Isolated sub-agent delegation (background tasks)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_subagent.py) status
        echo ""
        echo "Usage: subagent spawn <task> | list | resume <id> | status [id]"
        return 0
    end
    switch $argv[1]
        case spawn background bg
            if test (count $argv) -lt 2
                echo "Usage: subagent spawn <task>"
                return 1
            end
            $py (_arka_py_script arka_subagent.py) spawn (string join " " $argv[2..-1])
        case list ls
            $py (_arka_py_script arka_subagent.py) list
        case resume show
            if test (count $argv) -lt 2
                echo "Usage: subagent resume <id>"
                return 1
            end
            $py (_arka_py_script arka_subagent.py) resume $argv[2]
        case status
            if test (count $argv) -ge 2
                $py (_arka_py_script arka_subagent.py) status $argv[2]
            else
                $py (_arka_py_script arka_subagent.py) status
            end
        case '*'
            $py (_arka_py_script arka_subagent.py) $argv
    end
end

function routines --description "Schedule daily or hourly tasks (launchd/systemd timers)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        echo "Usage: routines add daily|hourly|HH:MM \"task\""
        echo "       routines list | install | remove ID | run ID"
        echo ""
        echo "NL: arka every day at 9am check unread emails"
        echo "    arka routine daily brief at 8am"
        echo "    arka every morning summarize my gmail"
        echo ""
        echo "Tasks run via agent (natural language OK). Install timers: routines install"
        return 1
    end
    $py (_arka_py_script arka_routines.py) $argv
    return $status
end

function remind --description "Schedule a reminder (fires at time; again when you're back if idle/off)"
    set -l py (_arka_python)
    if test (count $argv) -eq 0
        $py (_arka_py_script arka_remind.py) status
        return $status
    end
    switch $argv[1]
        case help -h --help
            echo "Usage: remind <when> <message>"
            echo "       remind add [--in 30m | --at TIME] <message>"
            echo "       remind list | status | cancel <id> | start | stop"
            echo ""
            echo "Examples:"
            echo "  remind to go to gym"
            echo "  remind in 30m stretch"
            echo "  remind at 5pm call mom"
            echo "  remind tomorrow 9am standup"
            echo "  remind list"
            echo ""
            echo "Behavior:"
            echo "  • Fires at the scheduled time if the PC is on"
            echo "  • If you were idle (away), also fires when you start using the PC"
            echo "  • If the PC was off/shut down, fires when you return after boot"
            return 0
        case list ls status start stop cancel check add
            $py (_arka_py_script arka_remind.py) $argv
            return $status
        case '*'
            $py (_arka_py_script arka_remind.py) add $argv
            return $status
    end
end

function predictions --description "Arka talent: opportunity predictions (antiques, stocks, strategy)"
    if test (count $argv) -eq 0
        echo "Usage: predictions [--domain antiques|stocks|strategy|all] [--deep] [--horizon '6 months'] <topic>"
        echo "       predictions history"
        echo ""
        echo "Examples:"
        echo "  predictions antique silver and vintage watches in India"
        echo "  predictions --domain stocks RELIANCE.NS and banking sector opportunities"
        echo "  predictions --domain strategy AI startup trends for 2026"
        echo "  predictions where to invest 3000 for 1 month to make a profit"
        echo "  stock invest where to put 5000 rupees for 2 weeks"
        echo "  predictions history"
        return 1
    end
    set -l py (_arka_python)
    if test "$argv[1]" = history
        $py (_arka_py_script arka_predictions.py) history
        return $status
    end
    set -l flags
    set -l args $argv
    while test (count $args) -gt 0
        switch $args[1]
            case --domain -d
                set -a flags --domain $args[2]
                set args $args[3..-1]
            case --deep
                set -a flags --deep
                set args $args[2..-1]
            case --horizon
                set -a flags --horizon $args[2]
                set args $args[3..-1]
            case '*'
                break
        end
    end
    if test (count $args) -eq 0
        echo "Usage: predictions [--domain antiques|stocks|strategy] <topic>"
        return 1
    end
    set -l topic (string join " " $args)
    printf '%s%s%s\n' (set_color cyan) "📈 $topic" (set_color normal) >&2
    set -l answer (_arka_capture_output $py (_arka_py_script arka_predictions.py) run $flags -- $args)
    set -l st $status
    if test $st -ne 0 -o -z "$answer"
        $py (_arka_py_script arka_predictions.py) run $flags -- $args
        return $status
    end
    _arka_print_answer_block "$answer" "Investment research"
end

function _arka_profession_title --description "Display title for profession domain id (internal)"
    switch $argv[1]
        case health
            echo "Health & Clinical"
        case nutrition
            echo "Nutrition"
        case startup
            echo "Startup"
        case investor
            echo "Investor"
        case teacher
            echo "Education"
        case legal
            echo "Legal"
        case engineer
            echo "Engineering"
        case journalism
            echo "Journalism"
        case marketing
            echo "Marketing"
        case finance
            echo "Finance"
        case counselor
            echo "Counseling"
        case chef
            echo "Culinary"
        case '*'
            echo (string upper $argv[1])
    end
end

function profession --description "Profession domains: curated sources (RSS, web, local repos) — not role prompts"
    set -l py (_arka_python)
    set -l script (_arka_py_script arka_professions.py)
    set -l proj (_arka_py_script arka_profession_projects.py)
    if test (count $argv) -eq 0
        $py $script list
        return $status
    end
    switch $argv[1]
        case list ls help -h --help
            $py $script list
        case ask run
            if test (count $argv) -ge 2
                set -l domains ($py $script list-ids 2>/dev/null)
                set -l title "Answer"
                if contains -- $argv[2] $domains
                    set title (_arka_profession_title $argv[2])
                end
                set -l answer (_arka_capture_output $py $script ask $argv[2..-1])
                set -l st $status
                if test $st -ne 0
                    return $st
                end
                if test -z "$answer"
                    return 1
                end
                _arka_print_answer_block "$answer" "$title"
                return 0
            end
            echo "Usage: profession ask <domain> <question>"
            echo "       profession ask <question>  (needs saved profession in memory)"
            return 1
        case setup clone
            if test (count $argv) -ge 2
                $py $proj setup $argv[2]
            else
                $py $proj setup
            end
            return $status
        case status
            $py $proj status
            return $status
        case sources
            $py $script sources $argv[2..-1]
            return $status
        case open cd
            if test (count $argv) -lt 2
                echo "Usage: profession open <nutrition|startup|investor|engineer>"
                return 1
            end
            set -l dir ($py $proj path $argv[2] 2>/dev/null)
            if test -n "$dir"; and test -d "$dir"
                cd "$dir"
                echo (set_color green)"✓ "(set_color normal)"$dir"
            else
                echo (set_color yellow)"No project for '$argv[2]' — run: profession setup $argv[2]"(set_color normal)
                return 1
            end
        case route match
            $py $script $argv[1] $argv[2..-1]
            return $status
        case install
            if test (count $argv) -lt 2
                echo "Usage: profession install <git-url|path>"
                echo "Example: profession install ~/my-profession-plugin"
                return 1
            end
            $py $script install $argv[2]
            return $status
        case plugins
            if test (count $argv) -lt 2
                $py $script plugins list
                return $status
            end
            switch $argv[2]
                case list ls
                    $py $script plugins list
                case refresh
                    $py $script plugins refresh
                case info
                    if test (count $argv) -ge 3
                        $py (_arka_py_script arka_profession_plugins.py) info $argv[3]
                    else
                        echo "Usage: profession plugins info <id>"
                        return 1
                    end
                case '*'
                    echo "Usage: profession plugins list|refresh|info <id>"
                    return 1
            end
            return $status
        case '*'
            set -l route ($py $script route (string join " " $argv) 2>/dev/null | string trim)
            if test -n "$route"
                _agent_run_skill_line "$route"
                return $status
            end
            echo "Usage: profession ask <domain> <question>"
            echo "Domains: health, nutrition, startup, investor, teacher, legal, engineer, journalism, marketing, finance, counselor, chef"
            return 1
    end
end

function _agent_route_profession --description "Symbolic profession routing (doctor, nutritionist, startup, …)"
    set -l cmd "$argv[1]"
    set -l py (_arka_python)
    set -l route ($py (_arka_py_script arka_professions.py) route "$cmd" 2>/dev/null | string trim)
    if test -n "$route"
        echo $route
    end
end

function _agent_trace_log --description "Log routing decision for agent_why (internal)"
    set -l input_text $argv[1]
    set -l interpreted $argv[2]
    set -l source $argv[3]
    set -l why ""
    if test (count $argv) -ge 4
        set why $argv[4]
    end
    _arka_agent trace-log --input "$input_text" --interpreted "$interpreted" --source "$source" --why "$why" 2>/dev/null
end

function platform_howto --description "Platform-specific app/window UI how-to (shortcuts, window chrome)"
    if test (count $argv) -eq 0
        echo "Usage: platform_howto <question>"
        echo "Example: platform_howto how to close a window in Brave"
        return 1
    end
    if not _arka_ensure_venv
        return 1
    end
    set -l question (_agent_with_voice_context (string join " " $argv))
    _arka_ui_header "$question" query
    set -l py (_arka_python)
    set -l answer ($py -m arka.agent.platform_howto $argv 2>/dev/null)
    if test -n "$answer"
        _arka_print_answer_block "$answer"
        return 0
    end
    set -l plat (_arka_agent_platform_label)
    set -l ui_hint (_arka_platform_ui_shortcuts)
    set -l system_text "You are a helpful assistant on $plat. Answer UI/how-to questions ONLY for $plat. $ui_hint Do NOT mention Windows, Linux, or macOS alternatives unless the user explicitly asks. Give 2-4 short, direct sentences suitable for text-to-speech."
    set -l user_text "Question: $question"
    set answer (_arka_capture_output _agent_llm_complete "$system_text" "$user_text")
    if test -n "$answer"
        _arka_print_answer_block "$answer"
        return 0
    end
    echo (set_color red)"Could not get an answer (check GEMINI_API_KEY or GROQ_API_KEY)"(set_color normal)
    return 1
end

function web_answer --description "Answer factual questions via web lookup + AI (auto deep search when needed)"
    if test (count $argv) -eq 0
        echo "Usage: web_answer [--deep] [--no-session] <question>"
        echo "Example: web_answer where is Tokyo"
        echo "Example: web_answer --deep who won IPL 2025"
        return 1
    end
    if not _arka_ensure_venv
        return 1
    end
    set -l force_deep false
    set -l no_session false
    set -l args $argv
    while test (count $args) -gt 0
        switch $args[1]
            case --deep -d
                set force_deep true
                set args $args[2..-1]
            case --no-session -n
                set no_session true
                set args $args[2..-1]
            case '*'
                break
        end
    end
    if test (count $args) -eq 0
        echo "Usage: web_answer [--deep] [--no-session] <question>"
        return 1
    end
    set -l question (_agent_with_voice_context (string join " " $args))
    if _agent_is_skills_help_request "$question"
        _arka_skills_help_show
        return 0
    end
    if not _arka_verify_web_query "$question"
        return 1
    end
    _arka_ui_header "$question" query

    set -l py (_arka_python)
    set -l intent ($py (_arka_py_script arka_chat.py) intent "$question" 2>/dev/null)
    set -l action (string split -f 1 \t "$intent")
    if test "$force_deep" = true; or contains -- "$action" SEARCH CALC WEATHER ERROR
        if test "$action" = CALC
            calc $args
            return $status
        end
        if test "$action" = ERROR
            error_helper $args
            return $status
        end
        if test "$action" = WEATHER; and test "$force_deep" != true
            hyperlocal_weather (_agent_with_voice_context (string join " " $args))
            return $status
        end
        if test "$force_deep" = true
            deep_web_answer (_agent_with_voice_context (string join " " $args))
            return $status
        end
        set -l answer ""
        if test "$no_session" = true
            set answer (_arka_capture_output _arka_chat_ask --no-session $args)
        else
            set answer (_arka_capture_output _arka_chat_ask $args)
        end
        if test -n "$answer"
            _arka_print_answer_block "$answer"
            return 0
        end
        if _arka_web_answer_llm_fallback "$question"
            return 0
        end
        deep_web_answer $args
        return $status
    end

    set -l answer ""
    if test "$no_session" = true
        set answer (_arka_capture_output _arka_chat_ask --no-session $args)
    else
        set answer (_arka_capture_output _arka_chat_ask $args)
    end
    if test -n "$answer"
        _arka_print_answer_block "$answer"
        return 0
    end

    if _arka_web_answer_llm_fallback "$question"
        return 0
    end
    echo (set_color red)"Could not get an answer (check GEMINI_API_KEY or GROQ_API_KEY)"(set_color normal)
    return 1
end

function hyperlocal_weather --description "Weather via Open-Meteo + IP geolocation"
    set -l question (string join " " $argv)
    set -l py (_arka_python)
    set -l wx ($py (_arka_py_script arka_chat.py) weather $argv 2>/dev/null)
    if test -z "$wx"
        weather $argv
        return $status
    end
    if test -z "$question"
        _arka_pretty_python_output "$wx"
        return 0
    end
    set -l system_text "Summarize this weather data for the user's question. Start with [FROM MEMORY]. Be concise for speech."
    set -l user_text "Weather data:\n$wx\n\nQuestion: $question"
    set -l answer (_arka_capture_output _agent_llm_complete "$system_text" "$user_text")
    if test -n "$answer"
        _arka_print_answer_block "$answer" "Weather"
    else
        _arka_pretty_python_output "$wx"
    end
end

function web_essay --description "Write an essay on a topic via web lookup + AI"
    if test (count $argv) -eq 0
        echo "Usage: web_essay <topic>"
        echo "Example: web_essay computer vision"
        return 1
    end
    set -l topic (string join " " $argv)
    _arka_ui_header "Essay: $topic" query

    set -l snippet (python3 (_arka_py_script web_answer.py) snippet "$topic" 2>/dev/null)

    set -l system_text "You are a clear, engaging writer. Write a short essay on the topic in 3-5 paragraphs (about 300-500 words). Include an introduction, key points in the body, and a brief conclusion. Be factual, informative, and well-structured. Do not use markdown headings or bullet lists unless essential."
    set -l user_text "Topic: $topic"
    if test -n "$snippet"
        set user_text "Reference material from web lookup:
$snippet

Topic: $topic"
    end

    set -l answer (_arka_capture_output _agent_llm_complete "$system_text" "$user_text")
    if test -z "$answer"
        if test -n "$snippet"
            _arka_print_answer_block "$snippet" "Essay"
            return 0
        end
        echo (set_color red)"Could not write essay (check GEMINI_API_KEY, GROQ_API_KEY, or ollama serve)"(set_color normal)
        return 1
    end
    _arka_print_answer_block "$answer" "Essay"
end

function agent_ask --description "Answer advisory questions: AI gathers context via shell, then answers"
    if test (count $argv) -eq 0
        echo "Usage: agent_ask <question>"
        echo "Example: agent_ask is my cpu too outdated for gaming?"
        return 1
    end
    set -l question (_agent_with_voice_context (string join " " $argv))
    if _agent_is_files_preference_question "$question"
        files_preference_help $argv
        return $status
    end
    if _agent_is_platform_howto_question "$question"
        platform_howto $argv
        return $status
    end
    if _agent_is_knowledge_question "$question"
        web_answer $argv
        return $status
    end
    if _agent_is_system_info_question "$question"
        set -l route (_agent_route_system_info "$question")
        _agent_run_skill_line "$route"
        return $status
    end
    _arka_ui_header "$question" chat

    set -l facts (_agent_ask_gather_context "$question" 6)
    if test -z (string trim -- "$facts"); and not _agent_is_system_info_question "$question"
        web_answer $argv
        return $status
    end
    echo ""

    set -l plat (_arka_agent_platform_label)
    set -l system_text "You are a helpful system advisor on $plat. Answer the question using ONLY the gathered command output below. Be direct and practical. If specs are borderline, say so. For security/malware questions: explain what the evidence shows, what is inconclusive without dedicated scanners, and suggest safe next steps appropriate for the OS (e.g. clamav on Linux, built-in security tools on macOS) without claiming certainty."
    set -l user_text "Gathered facts (from commands the assistant chose to run):
$facts

Question: $question"

    set -l answer (_arka_capture_output _agent_llm_complete "$system_text" "$user_text")
    if test -n "$answer"
        _arka_print_answer_block "$answer"
        return 0
    end
    _agent_advise_offline "$question" "$facts"
    return $status
end

function _agent_skill_matches_request --description "True if skill fits the user request (blocks telegRAM→system_monitor)"
    set -l cmd (string lower "$argv[1]")
    set -l skill (string split -f 1 " " -- "$argv[2]")[1]

    switch $skill
        case agent_ask
            _agent_is_advisory_question "$cmd"
            and not _agent_is_knowledge_question "$cmd"
            and not _agent_is_files_preference_question "$cmd"
        case files_preference_help
            _agent_is_files_preference_question "$cmd"
        case google
            _agent_is_google_login_request "$cmd"
            or _agent_is_google_gmail_request "$cmd"
            or _agent_is_google_calendar_request "$cmd"
        case classify_files
            _agent_is_desktop_organize_request "$cmd"
            or string match -qr '(?i)(classify.*file|sort.*file|organize.*file|auto.*sort)' "$cmd"
        case web_answer
            _agent_is_knowledge_question "$cmd"
        case platform_howto
            _agent_is_platform_howto_question "$cmd"
        case web_essay
            _agent_is_essay_request "$cmd"
        case app_usage
            _agent_is_usage_question "$cmd"
        case search_web
            string match -qr '(?i)(google|search\s+(the\s+)?web|search\s+online|look\s+up\s+online|\bsearch\s+for\b)' "$cmd"
            and not _agent_is_knowledge_question "$cmd"
        case system_monitor
            string match -qr '(?i)(system\s*monitor|system\s*status|show\s+(me\s+)?(system\s+)?(monitor|resources)|check\s+(cpu|ram|memory|disk|battery)|\b(cpu|ram|memory)\s+(usage|load|percent)|how\s+much\s+(cpu|ram|memory)\s+(left|free|used)|\buptime\b|\bbattery\b|\bload\s+average)' "$cmd"
            and not _agent_is_advisory_question "$cmd"
        case system_info
            _agent_is_system_info_question "$cmd"
            or _agent_is_hardware_fact_question "$cmd"
            or string match -qr '(?i)(system\s*info|\bos\s+info\b|\buname\b)' "$cmd"
        case disk_usage
            string match -qr '(?i)(disk\s*usage|disk\s*space|\bdf\b|storage\s+usage)' "$cmd"
        case disk_breakdown
            _agent_is_storage_breakdown_question "$cmd"
        case pdf_ask doc_ask pdf_ingest doc_ingest pdf_list doc_list codebase_ingest
            string match -qr '(?i)(pdf|document|doc|file|ingest|codebase|repo|repository|private\s?gpt|\.(?:pdf|docx|txt|md|pptx|xlsx|csv|html|py|json|yaml|fish|sh|sql|eml|xml))\b' "$cmd"
        case folder_summarize playlist_summarize youtube_research yt_research
            string match -qr '(?i)(summarize|summary|digest).*(folder|directory|playlist|series|all videos|all episodes)|playlist.*summarize' "$cmd"
        case media_transcript transcribe_media
            string match -qr '(?i)(transcrib|transcript).*(mp3|mp4|m4a|wav|audio|video|podcast|recording)|(?:mp3|mp4|m4a|wav|mkv|mov|webm|ogg|flac)\b.*(transcrib|transcript|summarize)' "$cmd"
        case install_app install_apt install_brew install_flatpak install_snap install_package install_uv
            string match -qr '(?i)(install|setup|get\s+app)' "$cmd"
        case install_uv
            string match -qr '(?i)(install|setup|get)\s+' "$cmd"
            and _agent_is_python_pip_install "$cmd"
        case install_app
            string match -qr '(?i)(install|setup|get)\s+' "$cmd"
            and not string match -qr '(?i)(flatpak|flathub|snap|with\s+apt|via\s+apt|brew|homebrew)' "$cmd"
        case install_brew
            string match -qr '(?i)(install|get|setup).*(with|via|using)\s+brew|\bhomebrew\s+install|\bbrew\s+install' "$cmd"
        case install_apt
            string match -qr '(?i)(install|get|setup).*(with|via|using)\s+apt|\bapt\s+install' "$cmd"
        case search_stores
            string match -qr '(?i)((search|query|find|look).*(flatpak|snap)|(flatpak|snap).*(search|query))' "$cmd"
        case create_desktop_app
            string match -qr '(?i)(create|add|make).*(desktop|launcher|shortcut|menu|entry)|unreal.*(desktop|launcher|shortcut)' "$cmd"
        case fix_graphics_driver
            string match -qr '(?i)(intel|graphics|gpu).*(driver|issue)|driver has known|recommended driver|installed version of the' "$cmd"
        case download_file extract_and_run
            string match -qr '(?i)(download|extract|unzip|wget|curl)' "$cmd"
        case play_spotify
            string match -qr '(?i)spotify' "$cmd"
        case play_song
            string match -qr '(?i)(play\s+song|random\s+song|local\s+music)' "$cmd"
        case stop_music
            string match -qr '(?i)^(stop|pause|kill)\s+(?:the\s+|this\s+|playing\s+)?(?:song|songs|music|audio|playback|spotify|it)\b' "$cmd"
        case play_youtube
            string match -qr '(?i)(youtube|watch\s+video)' "$cmd"
        case play_movie
            string match -qr '(?i)(play\s+|movie|film|rplay)' "$cmd"
        case browse_web
            string match -qr '(?i)(browse|scrape|website|web\s*page|click|login|automate)' "$cmd"
        case write_script run_script lint_python
            string match -qr '(?i)(script|python|lint|code)' "$cmd"
        case whatsapp_listen
            string match -qr '(?i)(whatsapp\s+inbox|inbox\s+whatsapp|whatsapp\s+listen|listen\s+whatsapp)' "$cmd"
        case send_whatsapp
            string match -qr '(?i)whatsapp' "$cmd"
        case monitor_x
            string match -qr '(?i)(monitor|watch|track|notify).*(twitter|tweet|\bx\.com\b|\bx\b)' "$cmd"
            or string match -qr '(?i)(twitter|tweet).*(monitor|watch|track|notify)' "$cmd"
        case post_x
            string match -qr '(?i)\b(?:post|share|tweet|publish).*(?:on\s+(?:my\s+)?(?:x|twitter)|to\s+(?:my\s+)?(?:x|twitter))\b' "$cmd"
            or string match -qr '(?i)\b(?:shorten|summarize).*(?:linkedin|post).*(?:post|tweet|share).*(?:x|twitter)\b' "$cmd"
        case internet_enhance aie
            string match -qr '(?i)(artificial\s+internet\s+enhance(?:ment?s?)?|internet\s+enhance(?:ment?s?)?|\baie\b)' "$cmd"
        case youtube_bulk yt_bulk
            string match -qr '(?i)(youtube\s+bulk|yt\s+bulk|bulk\s+download(?:er)?|download\s+(?:a\s+|the\s+|all\s+)?(?:youtube\s+)?(?:playlist|channel)|download\s+all\s+(?:videos\s+)?from\s+(?:channel|playlist|youtube)|youtube\s+bulk\s+downloader|\byt_bulk\b|\byoutube_bulk\b)' "$cmd"
        case youtube_download yt_download
            _agent_is_youtube_download_request "$cmd"
        case youtube_transcript
            string match -qr '(?i)(youtube.*transcript|transcript.*youtube|get transcript.*youtube|summarize.*youtube.*video)' "$cmd"
        case media_transcript transcribe_media
            string match -qr '(?i)(transcrib|transcript).*(mp3|mp4|m4a|wav|audio|video|podcast|recording)|(?:mp3|mp4|m4a|wav|mkv|mov|webm|ogg|flac)\b.*(transcrib|transcript|summarize)' "$cmd"
        case summarize_url
            string match -qr '(?i)(summarize (this |the )?(url|page|article|website|link)|summarize https?://|summary of https?://)' "$cmd"
        case daily_brief
            _agent_is_daily_brief_request "$cmd"
        case wifi_info
            string match -qr '(?i)(wifi|wi-fi|wireless).*(info|network|signal|ssid)|what wifi|am i on wifi' "$cmd"
        case generate_thumbnail
            _agent_is_generate_thumbnail_request "$cmd"
        case generate_image
            _agent_is_generate_image_request "$cmd"
        case chart
            _agent_is_chart_request "$cmd"
        case select_model model_select best_model model_advisor
            _agent_is_model_select_request "$cmd"
        case personalize onboard onboarding
            _agent_is_personalize_request "$cmd"
        case ascii_art
            _agent_is_ascii_art_request "$cmd"
        case drawing_ask
            _agent_is_drawing_ask_request "$cmd"
        case describe_screen
            _agent_is_describe_screen_request "$cmd"
        case describe_image
            _agent_is_describe_image_request "$cmd"
        case compose_slides
            _agent_is_compose_slides_request "$cmd"
        case convert_media
            _agent_is_convert_media_request "$cmd"
        case compose_video
            _agent_is_compose_video_request "$cmd"
        case generate_video
            string match -qr '(?i)(generate|create|make|render|produce|animate|film).*(video|clip|animation|movie)|^(animate|film)\s+' "$cmd"
        case generate_password store_password pass
            string match -qr '(?i)(password|passcode)' "$cmd"
            and not string match -qr '(?i)(decrypt|protected|pdf)' "$cmd"
        case predictions
            string match -qr '(?i)(predict|prediction|forecast|opportunit|outlook).*(antique|stock|market|strategy|invest|collectible|portfolio)|^(predict|forecast)\s+|(where\s+(to|should\s+i)\s+invest|how\s+(to|can\s+i)\s+invest|make\s+(?:a\s+)?profit)' "$cmd"
        case remind
            string match -qr '(?i)\bremind(?:\s+me)?\b' "$cmd"
            and not string match -qr '(?i)\b(?:every\s+day|each\s+day|daily\s+at|routine)\b' "$cmd"
        case routines
            _agent_is_routines_request "$cmd"
        case inbox_agent
            if _agent_is_gmail_summarize_request "$cmd"
                return 1
            else if _agent_is_google_gmail_request "$cmd"
                return 1
            else if _agent_is_google_calendar_request "$cmd"
                return 1
            end
            string match -qr '(?i)(inbox|unread|email|mail|message)' "$cmd"
        case stock stock_analysis
            string match -qr '(?i)^(macro|emotion|fundamentals|funding|competition)(\s+\d+|\s+[A-Z][A-Z0-9.-]+)*$' "$cmd"
            or string match -qr '(?i)^(stock|market)\s+(news|prices|policy|strategy|volatility|dashboard|context|invest|macro|emotion|fundamentals|funding|competition)\b|^(analyze|check)\s+(?:stock\s+)?[A-Z][A-Z0-9.-]{1,12}\b|(where\s+(to|should\s+i)\s+invest|how\s+(to|can\s+i)\s+invest|invest\s+\d|make\s+(?:a\s+)?profit)' "$cmd"
        case '*'
            return 0
    end
end

function _agent_guess_route --description "Suggest route: skill|shell|llm|llm_codegen (internal)"
    set -l cmd $argv[1]
    set -l stripped (_agent_strip_wake "$cmd")
    if test -n "$stripped"
        set cmd "$stripped"
    end
    set -l clean (string lower "$cmd")
    if string match -qr '(?i)^speak\s+' "$clean"
        set cmd (string replace -r -i '^speak\s+' '' "$cmd")
        set clean (string lower "$cmd")
    end

    if _agent_is_post_x_request "$cmd"
        set -l px_cmd (_agent_build_post_x_cmd "$cmd")
        if test -n "$px_cmd"
            echo "skill|$px_cmd|Shorten URL and post to X/Twitter"
            return
        end
    end

    if _agent_is_clipboard_history_request "$cmd"
        set -l ch (_agent_route_clipboard_history "$cmd")
        if test -n "$ch"
            echo "skill|$ch|Clipboard history"
            return
        end
    end

    if _agent_is_agent_hub_request "$cmd"
        set -l hub_cmd (_agent_route_agent_hub "$cmd")
        if test -n "$hub_cmd"
            echo "skill|$hub_cmd|Agent Hub — shared MCP and memory"
            return
        end
    end

    if _agent_is_mcp_request "$cmd"
        set -l mcp_cmd (_agent_route_mcp "$cmd")
        if test -n "$mcp_cmd"
            echo "skill|$mcp_cmd|MCP server tools and status"
            return
        end
    end

    if _agent_is_bookmarks_request "$cmd"
        set -l br (_agent_route_bookmarks "$cmd")
        if test -n "$br"
            echo "skill|$br|Bookmark manager"
            return
        end
    end

    if _agent_is_daily_brief_request "$cmd"
        echo "skill|daily_brief|Weather + news headlines"
        return
    end

    if _agent_is_life_sciences_request "$cmd"
        set -l ls (_agent_route_life_sciences "$cmd")
        if test -n "$ls"
            echo "skill|$ls|Life sciences plugin catalog"
            return
        end
    end

    if _agent_is_gemini_cli_request "$cmd"
        set -l gc (_agent_build_gemini_cli_cmd "$cmd")
        if test -n "$gc"
            echo "skill|$gc|Google Gemini CLI agent"
            return
        end
    end

    set -l route_mode (_arka_route_mode)
    if test "$route_mode" = ai -o "$route_mode" = ai_only
        set -l skills (_agent_available_skills)
        set -l llm (_agent_llm_route "$cmd" "$skills")
        if test -n "$llm"
            echo "llm|$llm|AI routing (LLM)"
            return
        end
        if test "$route_mode" = ai_only
            echo "none||No AI route (ROUTE_MODE=ai_only)"
            return
        end
    end

    switch $clean
        case debug 'listen debug' 'enable debug' 'debug mode' 'turn on debug' 'debug listen' 'start debug'
            echo "listen|debug|Restart wake listener with STT debug logging"
            return
        case 'listen fg' 'listen foreground' fg foreground 'live listen' 'listen live'
            echo "listen|fg|Live STT debug in foreground"
            return
        case listen 'start listening' 'start listen'
            echo "listen|start|Start wake listener"
            return
        case stop 'stop listen' 'stop listening'
            echo "listen|stop|Stop wake listener"
            return
        case status 'listen status' 'listener status'
            echo "listen|status|Wake listener status"
            return
    end

    if string match -qr '(?i)(browse|scrape|automate.*web|playwright|fill\s+form|website.*click)' "$clean"
        echo "llm_codegen|browse_web|Needs generated browser automation code"
        return
    end
    if string match -qr '(?i)(write|create|generate).*(script|python|function)' "$clean"
        echo "llm_codegen|write_script|Generate then run script"
        return
    end
    if string match -qr '(?i)(save|store|remember)\s+(?:password|pass)\s+\S+\s+(?:for|as|named)\s+[a-zA-Z0-9._-]+' "$clean"
        set -l m (string match -r '(?i)(?:save|store|remember)\s+(?:password|pass)\s+(\S+)\s+(?:for|as|named)\s+([a-zA-Z0-9._-]+)' "$cmd")
        if test (count $m) -ge 3
            echo "skill|generate_password set $m[3] "(string escape --style=script -- $m[2])"|Store existing password encrypted"
            return
        end
    end
    if string match -qr '(?i)(save|store|remember).*(password|pass).*(for|as|named)|generate.*password.*(for|named)\s+\S' "$clean"
        set -l pname (_agent_parse_password_name "$cmd")
        if test -n "$pname"
            echo "skill|generate_password save "(string escape --style=script -- $pname)"|Generate + store encrypted password"
        else
            echo "skill|generate_password save|Generate + store encrypted password"
        end
        return
    end
    if string match -qr '(?i)(get|show|retrieve).*(password|pass).*(for|named)|what.*password.*(for|to)\s+\S' "$clean"
        set -l pname (_agent_parse_password_name "$cmd")
        if test -n "$pname"
            echo "skill|generate_password get "(string escape --style=script -- $pname)"|Retrieve stored password"
            return
        end
    end
    if string match -qr '(?i)^(generate|create|make)\s+(?:a |an |the |me )?(?:new )?(password|passcode)\b' "$clean"
        echo "skill|generate_password|Generate secure random password"
        return
    end
    if string match -qr '(?i)(install|get|setup).*(with|via|using)\s+apt|\bapt\s+install' "$clean"
        echo "skill|install_apt $(_agent_parse_install_app_name "$cmd")|APT package install"
        return
    end
    if string match -qr '(?i)(install|get|setup).*(with|via|using)\s+brew|\bhomebrew\s+install|\bbrew\s+install' "$clean"
        echo "skill|install_brew $(_agent_parse_install_app_name "$cmd")|Homebrew install"
        return
    end
    if string match -qr '(?i)(install|get|setup).*(flatpak|flathub)' "$clean"
        echo "skill|install_flatpak $(_agent_parse_install_app_name "$cmd")|Flatpak install"
        return
    end
    if string match -qr '(?i)(install|get|setup).*snap' "$clean"
        echo "skill|install_snap $(_agent_parse_install_app_name "$cmd")|Snap install"
        return
    end
    if string match -qr '(?i)^(install|get|setup)\s+' "$clean"
        and not string match -qr '(flatpak|flathub|snap|apt|brew|homebrew)' "$clean"
        and _agent_is_python_pip_install "$cmd"
        echo "skill|"(string trim -- (_agent_parse_install_uv "$cmd"))"|Python package via uv pip"
        return
    end
    if string match -qr '(?i)^(install|get|setup)\s+' "$clean"
        and not string match -qr '(flatpak|flathub|snap|apt|brew|homebrew)' "$clean"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"; and not _install_target_is_package_file "$app"
            if _arka_is_macos
                echo "skill|install_app $app|Search Homebrew and install"
            else
                echo "skill|install_app $app|Search Flatpak, Snap, and apt"
            end
            return
        end
    end
    if string match -qr '(?i)(create|add|make).*(desktop|launcher|shortcut).*(unreal|unreal\s*engine)|unreal.*(desktop|launcher|shortcut)' "$clean"
        echo "skill|create_desktop_app unreal|Create .desktop launcher for Unreal Editor"
        return
    end
    if string match -qr '(?i)(intel|graphics|gpu).*(driver|issue)|driver has known|recommended driver|installed version of the.*driver' "$clean"
        echo "skill|fix_graphics_driver|Fix GPU driver warnings (Linux Mesa + vendor page)"
        return
    end
    if string match -qr '(?i)^macro(\s+\d+)?$' "$clean"
        set -l n (string match -r '(?i)^macro\s+(\d+)$' "$clean")[2]
        if test -n "$n"
            echo "skill|stock macro $n|Macro events → stock sector impact"
        else
            echo "skill|stock macro|Macro events → stock sector impact"
        end
        return
    end
    if string match -qr '(?i)^emotion(\s+\d+)?$' "$clean"
        set -l n (string match -r '(?i)^emotion\s+(\d+)$' "$clean")[2]
        if test -n "$n"
            echo "skill|stock emotion $n|Market sentiment + crowd forecast"
        else
            echo "skill|stock emotion|Market sentiment + crowd forecast"
        end
        return
    end
    if string match -qr '(?i)(weather|forecast|temp|rain|sunny|cloudy|snow|storm|umbrella|will it rain|is it going to rain|is it raining)' "$clean"
        echo "skill|hyperlocal_weather $cmd|Weather via Open-Meteo + IP"
        return
    end
    if _agent_is_file_size_find "$cmd"
        echo "skill|find_files_by_size $cmd|Find files by size threshold"
        return
    end
    if _agent_is_chart_request "$cmd"
        set -l parts (_agent_build_chart_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Line, bar, pie, or scatter chart (matplotlib PNG)"
            return
        end
    end
    if _agent_is_model_select_request "$cmd"
        set -l parts (_agent_build_model_select_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Recommend LLM models from PC resources"
            return
        end
    end
    if _agent_is_personalize_request "$cmd"
        set -l parts (_agent_build_personalize_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Onboarding and skill recommendations"
            return
        end
    end
    if _agent_is_ascii_art_request "$cmd"
        set -l parts (_agent_build_ascii_art_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|ASCII banner or image-to-ASCII art (figlet)"
            return
        end
    end
    if _agent_is_drawing_ask_request "$cmd"
        set -l parts (_agent_build_drawing_ask_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Vision analysis of blueprints, drawings, and scanned specs"
            return
        end
    end
    if _agent_is_describe_screen_request "$cmd"
        set -l parts (_agent_build_describe_screen_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Capture screen after countdown and describe with vision"
            return
        end
    end
    if _agent_is_describe_image_request "$cmd"
        set -l parts (_agent_build_describe_image_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Describe a photo or image via local vLLM"
            return
        end
    end
    if _agent_is_download_request "$cmd"
        set -l parts (_agent_build_download_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Download file via curl (resume)"
            return
        end
    end
    if _agent_is_routines_request "$cmd"
        set -l parts (_agent_build_routines_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Daily or hourly scheduled task"
            return
        end
    end
    if _agent_is_remind_request "$cmd"
        set -l parts (_agent_build_remind_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Reminder (idle/shutdown aware)"
            return
        end
    end
    if string match -qr '(?i)\b(timer|countdown)\b' "$clean"
        set -l trest (string replace -r -i '^(?:please\s+)?(?:set\s+a\s+)?(?:timer|countdown)\s+(?:for\s+)?' '' "$cmd" | string trim)
        if test -n "$trest"
            echo "skill|timer $trest|Countdown timer"
        else
            echo "skill|timer|Countdown timer"
        end
        return
    end
    if string match -qr '(?i)(search\s+(?:the\s+)?(?:web|internet)(?:\s+for)?|google\s+(?:search\s+)?(?:for\s+)?)' "$clean"
        set -l q (string replace -r -i '^(?:search\s+(?:the\s+)?(?:web|internet)(?:\s+for)?|google\s+(?:search\s+)?(?:for\s+)?)' '' "$cmd" | string trim)
        test -n "$q"; and echo "skill|search_web $q|Web search"
        test -n "$q"; and return
    end
    if string match -qr '(?i)\b(?:code\s+agent|agent\s+code)\b' "$clean"
        set -l goal (string replace -r -i '.*(?:code\s+agent|agent\s+code)\s*' '' "$cmd" | string trim)
        test -n "$goal"; and echo "skill|agent_code $goal|Code agent"
        test -n "$goal"; and return
        echo "skill|agent_code|Code agent"
        return
    end
    if string match -qr '(?i)\b(?:browser\s+agent|agent\s+browser)\b' "$clean"
        set -l goal (string replace -r -i '.*(?:browser\s+agent|agent\s+browser)\s*' '' "$cmd" | string trim)
        test -n "$goal"; and echo "skill|agent_browser $goal|Browser automation agent"
        test -n "$goal"; and return
        echo "skill|agent_browser|Browser automation agent"
        return
    end
    if string match -qr '(?i)\b(?:meeting\s+agent|summarize\s+(?:these\s+)?meeting\s+notes)\b' "$clean"
        set -l notes (string replace -r -i '^(?:meeting\s+agent|summarize\s+(?:these\s+)?meeting\s+notes)\s*' '' "$cmd" | string trim)
        test -n "$notes"; and echo "skill|meeting_agent $notes|Meeting notes agent"
        test -n "$notes"; and return
        echo "skill|meeting_agent|Meeting notes agent"
        return
    end
    if string match -qr '(?i)\b(?:study\s+agent|help\s+me\s+study)\b' "$clean"
        set -l topic (string replace -r -i '^(?:study\s+agent|help\s+me\s+study)\s*' '' "$cmd" | string trim)
        test -n "$topic"; and echo "skill|study_agent $topic|Study agent"
        test -n "$topic"; and return
        echo "skill|study_agent|Study agent"
        return
    end
    if string match -qr '(?i)\b(?:product\s+reviewer|review\s+this\s+product|check\s+(?:the\s+)?ingredients|ingredient\s+check|analyze\s+ingredients|ingredients?\s+review)\b' "$clean"
        set -l query (string replace -r -i '^(?:product\s+reviewer|review\s+this\s+product|check\s+(?:the\s+)?ingredients|ingredient\s+check|analyze\s+ingredients|ingredients?\s+review)\s*' '' "$cmd" | string trim)
        test -n "$query"; and echo "skill|product_reviewer $query|Product reviewer"
        test -n "$query"; and return
        echo "skill|product_reviewer|Product reviewer"
        return
    end
    if string match -qr '(?i)\b(?:is\s+this|are\s+these)\s+.+\s+good\s+for\s+' "$clean"
        echo "skill|product_reviewer $cmd|Product reviewer"
        return
    end
    if string match -qr '(?i)\bis\s+.+\s+(?:vegan|cruelty[- ]free|safe\s+for\s+sensitive\s+skin)\b' "$clean"
        echo "skill|product_reviewer $cmd|Product reviewer"
        return
    end
    if string match -qr '(?i)\bsupermemory\b' "$clean"
        set -l q (string replace -r -i '^.*supermemory\s*' '' "$cmd" | string trim)
        test -n "$q"; and echo "skill|supermemory $q|Supermemory recall/store"
        test -n "$q"; and return
        echo "skill|supermemory|Supermemory"
        return
    end
    if string match -qr '(?i)\b(?:set\s+my\s+location|my\s+location\s+is|i\s+am\s+in)\b' "$clean"
        set -l loc (string replace -r -i '^(?:please\s+)?(?:set\s+my\s+location\s+(?:to\s+)?|my\s+location\s+is\s+|i\s+am\s+in\s+)' '' "$cmd" | string trim)
        test -n "$loc"; and echo "skill|set_location $loc|Save location for weather/nearby"
        test -n "$loc"; and return
        echo "skill|set_location|Save location"
        return
    end
    if _agent_is_compose_slides_request "$cmd"
        echo "skill|"(_agent_build_compose_slides_cmd "$cmd")"|Presentation slides (pptx, pdf, html, md, json)"
        return
    end
    if _agent_is_convert_media_request "$cmd"
        echo "skill|"(_agent_build_convert_media_cmd "$cmd")"|Convert image/video/slide formats"
        return
    end
    if _agent_is_compose_video_request "$cmd"
        echo "skill|"(_agent_build_compose_video_cmd "$cmd")"|YouTube info video (Unsplash + ffmpeg)"
        return
    end
    if string match -qr '(?i)^(generate|create|make|render|produce|animate|film)\s+(?:an?\s+)?(?:video|clip|animation|movie|animated\s+video)\b|^(animate|film)\s+' "$clean"
        set -l vid_prompt (_agent_parse_video_prompt "$cmd")
        if test -n "$vid_prompt"
            echo "skill|generate_video "(string escape --style=script -- $vid_prompt)"|Generate real AI video (Pollinations/Gemini)"
        else
            echo "skill|generate_video|Generate real AI video (Pollinations/Gemini)"
        end
        return
    end
    if string match -qr '(?i)(where\s+(to|should\s+i)\s+invest|how\s+(to|can\s+i)\s+invest|invest\s+\d|make\s+(?:a\s+)?profit|best\s+(?:place|option|way)\s+to\s+(?:invest|put))' "$clean"
        set -l topic (_agent_strip_query_prefix "$cmd")
        echo "skill|predictions --domain stocks --deep $topic|Short-term investment research"
        return
    end
    if string match -qr '(?i)(predict|prediction|forecast|opportunit).*(antique|stock|market|strategy|invest|collectible|portfolio)|^(predict|forecast)\s+' "$clean"
        echo "skill|predictions|Opportunity predictions: antiques, stocks, strategy"
        return
    end
    if string match -qr '(?i)^(stock|market)\s+(news|prices|policy|strategy|volatility|dashboard|context|invest|macro|emotion|fundamentals|funding|competition)\b' "$clean"
        set -l stock_cmd (string replace -r -i '^(?:stock|market)\s+' '' "$cmd" | string trim)
        echo "skill|stock $stock_cmd|Stock analysis project"
        return
    end
    if _agent_is_repo_health_request "$cmd"
        set -l rh (_agent_route_repo_health "$cmd")
        if test -n "$rh"
            echo "skill|$rh|Repo health scan and checks"
            return
        end
    end
    if _agent_is_data_ask_request "$cmd"
        set -l da (_agent_route_data_ask "$cmd")
        if test -n "$da"
            echo "skill|$da|Ask questions about data files"
            return
        end
    end
    if string match -qr '(?i)^(analyze|check)\s+(?:stock\s+)?([A-Z][A-Z0-9.-]{1,12})\b' "$clean"
        and not _agent_is_repo_health_request "$cmd"
        and not _agent_is_data_ask_request "$cmd"
        set -l ticker (string upper (string match -r '(?i)([A-Z][A-Z0-9.-]{1,12})\s*$' "$cmd")[2])
        echo "skill|stock analyze $ticker|AI stock strategy backtest"
        return
    end
    if string match -qr '(?i)(?:^|\b)(?:generate|create|make|design)\s+(?:an?\s+)?(?:youtube\s+)?thumbnail\b' "$clean"
        echo "skill|generate_thumbnail|YouTube thumbnail — Unsplash photo + title overlay"
        return
    end
    if _agent_is_data_ask_request "$cmd"
        set -l da (_agent_route_data_ask "$cmd")
        if test -n "$da"
            echo "skill|$da|Ask questions about data files"
            return
        end
    end
    if _agent_is_generate_data_request "$cmd"
        set -l gd (_agent_route_generate_data "$cmd")
        if test -n "$gd"
            echo "skill|$gd|Generate sample datasets"
            return
        end
    end
    if _agent_is_ascii_art_request "$cmd"
        set -l parts (_agent_build_ascii_art_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|ASCII banner or image-to-ASCII art (figlet)"
            return
        end
    end
    if string match -qr '(?i)^(generate|create|make|draw|paint|sketch|show)\s+(?:an?\s+)?(?:image|picture|photo|art|drawing|sketch|painting|illustration|portrait|landscape)\b|^(draw|paint|sketch)\s+' "$clean"
        and not string match -qr '(?i)\bascii\s+(?:art|banner)\b' "$clean"
        and not string match -qr '(?i)\bfiglet\b' "$clean"
        echo "skill|generate_image|Generate images with Gemini API (gemini-2.5-flash-image)"
        return
    end
    if string match -qr '(?i)wallpaper|desktop\s+background|set\s+(?:this|it)\s+as\s+wallpaper|background\s+image' "$clean"
        set -l words (string split " " -- "$cmd")
        set -l img ""
        for w in $words
            if string match -irq '\.(jpe?g|png|webp|gif|bmp|svg)$' -- "$w"
                set img $w
            end
        end
        if test -n "$img"
            echo "skill|set_wallpaper $img|GNOME desktop background"
            return
        end
        echo "skill|set_wallpaper|GNOME desktop background (needs image path)"
        return
    end
    if string match -qr '(?i)^https?://' "$clean"
        if _agent_is_bookmarks_request "$cmd"
            set -l br (_agent_route_bookmarks "$cmd")
            if test -n "$br"
                echo "skill|$br|Bookmark manager"
                return
            end
        end
        if set -l dl (_agent_build_download_cmd "$cmd")
            echo "skill|$dl|Download file via curl (resume)"
            return
        end
        echo "shell|curl/wget|Direct URL download"
        return
    end
    if string match -qr '(?i)^(date|pwd|whoami|ls|df|free)\b' "$clean"
        echo "shell|$cmd|Simple shell command"
        return
    end
    if _agent_is_usage_question "$cmd"
        set -l period (_agent_parse_usage_period "$cmd")
        echo "skill|app_usage $period|Your app/screen time from local tracker"
        return
    end
    if _agent_is_essay_request "$cmd"
        set -l topic (_agent_normalize_essay_topic "$cmd")
        test -z "$topic"; and set topic $cmd
        echo "skill|web_essay $topic|Essay via web lookup + AI"
        return
    end
    if string match -qr '^/' "$cmd"
        set -l forced (string trim (string replace -r '^/+?' '' "$cmd"))
        test -z "$forced"; and set forced $cmd
        echo "skill|deep_web_answer $forced|Forced deep web search"
        return
    end
    if _agent_is_nearby_places_question "$cmd"
        set -l nb (_agent_build_nearby_cmd "$cmd")
        echo "skill|$nb|Offline nearby POIs (OpenStreetMap)"
        return
    end
    if _agent_is_video_search_request "$cmd"
        set -l vf (_agent_build_video_search_cmd "$cmd")
        echo "skill|$vf|YouTube video links"
        return
    end
    if _agent_is_translate_request "$cmd"
        set -l tr (_agent_build_translate_cmd "$cmd")
        echo "skill|$tr|Google Translate"
        return
    end
    if _agent_is_pr_check_request "$cmd"
        set -l prr (_agent_route_pr_check "$cmd")
        if test -n "$prr"
            echo "skill|$prr|PR diff / CI / babysit"
            return
        end
    end
    if _agent_is_github_repo_request "$cmd"
        set -l gr (_agent_route_github_repo "$cmd")
        if test -n "$gr"
            echo "skill|$gr|GitHub repo commits and modified files"
            return
        end
    end
    if _agent_is_competitions_request "$cmd"
        set -l cr (_agent_route_competitions "$cmd")
        if test -n "$cr"
            echo "skill|$cr|Search hackathons and ML competitions"
            return
        end
    end
    if _agent_is_bookmarks_request "$cmd"
        set -l br (_agent_route_bookmarks "$cmd")
        if test -n "$br"
            echo "skill|$br|Bookmark manager"
            return
        end
    end
    if _agent_is_repo_health_request "$cmd"
        set -l rh (_agent_route_repo_health "$cmd")
        if test -n "$rh"
            echo "skill|$rh|Repo health scan and checks"
            return
        end
    end
    if _agent_is_data_ask_request "$cmd"
        set -l da (_agent_route_data_ask "$cmd")
        if test -n "$da"
            echo "skill|$da|Ask questions about data files"
            return
        end
    end
    if _agent_is_generate_data_request "$cmd"
        set -l gd (_agent_route_generate_data "$cmd")
        if test -n "$gd"
            echo "skill|$gd|Generate sample datasets"
            return
        end
    end
    if _agent_is_docker_status_request "$cmd"
        set -l dr (_agent_route_docker_status "$cmd")
        if test -n "$dr"
            echo "skill|$dr|Docker status and logs"
            return
        end
    end
    if _agent_is_clipboard_history_request "$cmd"
        set -l ch (_agent_route_clipboard_history "$cmd")
        if test -n "$ch"
            echo "skill|$ch|Clipboard history"
            return
        end
    end
    if _agent_is_route_learn_request "$cmd"
        set -l lr (_agent_route_learn_management "$cmd")
        if test -n "$lr"
            echo "skill|$lr|Learned route management"
            return
        end
    end
    set -l learned (_arka_match_learned_route "$cmd")
    if test -n "$learned"
        echo "skill|$learned|Learned route"
        return
    end
    if _agent_is_survival_lang_request "$cmd"
        set -l sl (_agent_build_survival_lang_cmd "$cmd")
        echo "skill|$sl|Travel survival phrases"
        return
    end
    if _agent_is_currency_request "$cmd"
        set -l cc (_agent_build_currency_cmd "$cmd")
        if test -n "$cc"
            echo "skill|$cc|Currency conversion"
            return
        end
    end
    if _agent_is_price_check_request "$cmd"
        set -l pq (string replace -r -i '^price_check\s+' '' "$cmd" | string trim)
        test -z "$pq"; and set pq $cmd
        echo "skill|price_check $pq|Product price lookup"
        return
    end
    if _agent_is_platform_howto_question "$cmd"
        echo "skill|platform_howto $cmd|Platform-specific app/UI how-to"
        return
    end

    if _agent_is_knowledge_question "$cmd"
        set -l kq (_agent_normalize_knowledge_q "$cmd")
        test -z "$kq"; and set kq $cmd
        echo "skill|web_answer $kq|Factual answer via web + AI"
        return
    end
    if _agent_is_storage_breakdown_question "$cmd"
        echo "skill|disk_breakdown|Disk space by videos, pictures, documents, etc."
        return
    end
    if _agent_is_places_question "$cmd"
        echo "skill|web_answer $cmd|Places / travel answer via web + AI"
        return
    end
    if _agent_is_pdf_ingest_request "$cmd"
        set -l pdf (_agent_parse_pdf_path "$cmd")
        if test -n "$pdf"
            echo "skill|pdf_ingest $pdf|Ingest document (auto-starts PrivateGPT)"
        else
            echo "skill|pdf_ingest|Ingest document (auto-starts PrivateGPT)"
        end
        return
    end
    if _agent_is_codebase_ingest_request "$cmd"
        set -l root (_agent_parse_codebase_path "$cmd")
        if test -n "$root"
            echo "skill|codebase_ingest '$root'|Index project for Q&A"
        else
            echo "skill|codebase_ingest|Index project for Q&A (needs path)"
        end
        return
    end
    if _agent_is_pdf_question "$cmd"
        set -l pq (_agent_pdf_ask_cmd "$cmd")
        echo "skill|$pq|Ask/summarize ingested documents (optional --doc)"
        return
    end
    if string match -qr '(?i)^(reset|clear)\s+(chat|session|memory)\b' "$clean"
        echo "skill|chat_reset|Reset chat session"
        return
    end
    if string match -qr '(?i)^(stop|pause|kill)\s+(?:the\s+|this\s+|that\s+|playing\s+)?(?:song|songs|music|audio|playback|player|spotify|it)\b' "$clean"
        echo "skill|stop_music|Stop/pause music (mpv + MPRIS)"
        return
    end
    if string match -qr '(?i)(play.*spotify|spotify)' "$clean"
        echo "skill|play_spotify|Spotify playback"
        return
    end
    if set -l media_route (_agent_route_media "$cmd")
        echo "skill|$media_route|Transcribe/summarize local audio or video"
        return
    end
    if _agent_is_playlist_summarize_request "$cmd"
        set -l urlm (string match -r '(https?://[^\s'\'']+)' "$cmd")
        if test (count $urlm) -ge 2
            echo "skill|playlist_summarize --url '$urlm[2]'|YouTube playlist digest"
            return
        end
        set -l folder (_agent_parse_folder_path "$cmd")
        if test -n "$folder"
            echo "skill|playlist_summarize --folder '$folder'|Local playlist folder digest"
        else
            echo "skill|playlist_summarize|Playlist digest (needs --url or --folder)"
        end
        return
    end
    if _agent_is_folder_summarize_request "$cmd"
        set -l folder (_agent_parse_folder_path "$cmd")
        if test -n "$folder"
            echo "skill|folder_summarize '$folder'|Summarize all media in folder"
        else
            echo "skill|folder_summarize|Summarize folder (needs path)"
        end
        return
    end
    if _agent_is_youtube_research_request "$cmd"
        set -l ytr (_agent_build_youtube_research_cmd "$cmd")
        echo "skill|$ytr|YouTube search + transcript research digest"
        return
    end
    if set -l ytb_route (_agent_route_youtube_bulk "$cmd")
        echo "skill|$ytb_route|YouTube bulk playlist/channel download"
        return
    end
    if set -l ytd_route (_agent_route_youtube_download "$cmd")
        echo "skill|$ytd_route|Download single YouTube video"
        return
    end
    if string match -qr '(?i)(youtube.*transcript|transcript.*youtube|video transcript|get transcript.*youtube|summarize.*youtube.*video)' "$clean"
        set -l yt_target (string replace -r -i '^.*(?:transcript|summarize)\s+(?:for\s+|of\s+)?' '' "$cmd" | string trim)
        if string match -qr 'https?://|youtu\.be/' "$yt_target"
            echo "skill|youtube_transcript $yt_target --summarize|YouTube transcript + summary"
        else if test -n "$yt_target"
            echo "skill|youtube_transcript $yt_target|YouTube transcript"
        else
            echo "skill|youtube_transcript|YouTube transcript (needs URL)"
        end
        return
    end
    if _agent_is_post_x_request "$cmd"
        set -l px_cmd (_agent_build_post_x_cmd "$cmd")
        if test -n "$px_cmd"
            echo "skill|$px_cmd|Shorten URL and post to X/Twitter"
            return
        end
    end
    if string match -qr '(?i)(summarize (this |the )?(url|page|article|website|link)|summarize https?://|summary of https?://)' "$clean"
        set -l page_url (string match -r 'https?://[^\s]+' "$cmd")
        if test (count $page_url) -ge 1
            echo "skill|summarize_url $page_url[1]|Summarize web page"
        else
            echo "skill|summarize_url|Summarize web page (needs URL)"
        end
        return
    end
    if string match -qr '(?i)(live\s+(sports?\s+)?scores?|sports?\s+scores?|ipl\s+(live|score)|cricket\s+(live|score)|nfl\s+scores?|nba\s+scores?|match\s+score)' "$clean"
        echo "skill|sports_score $cmd|Live sports scores"
        return
    end
    if _agent_is_kalshi_request "$cmd"
        set -l kc (_agent_build_kalshi_cmd "$cmd")
        if test -n "$kc"
            echo "skill|$kc|Kalshi prediction market odds"
            return
        end
    end
    if set -l cc_cmd (_agent_build_currency_cmd "$cmd")
        if test -n "$cc_cmd"
            echo "skill|$cc_cmd|Currency conversion"
            return
        end
    end
    set -l py (_arka_python)
    set -l learned ($py (_arka_py_script arka_route_learn.py) match "$cmd" 2>/dev/null | string trim)
    if test -n "$learned"
        echo "skill|$learned|Learned route"
        return
    end
    set -l tp ($py (_arka_py_script arka_skills.py) match "$cmd" 2>/dev/null)
    if test -n "$tp"
        echo "skill|$tp|Third-party plugin"
        return
    end
    if _agent_is_daily_brief_request "$cmd"
        echo "skill|daily_brief $cmd|Weather + news headlines"
        return
    end
    if string match -qr '(?i)(wifi|wi-fi|wireless).*(info|network|signal|ssid)|what wifi|am i on wifi' "$clean"
        echo "skill|wifi_info|Current Wi-Fi network"
        return
    end
    if string match -qr '(?i)(play.*youtube|youtube|watch\s+(?:a\s+|an\s+)?(?:video|episode))' "$clean"
        echo "skill|play_youtube|YouTube playback"
        return
    end
    if string match -qr '(?i)(play.*song|random.*song|local.*music|play\s+(?:a\s+|an\s+)?music|play\s+music)' "$clean"
        echo "skill|play_song|Local music playback"
        return
    end
    if string match -qr '(?i)(play.*movie|play.*film|play\s+(?:a\s+|an\s+)?video)' "$clean"
        echo "skill|play_movie|Local video playback"
        return
    end
    if string match -qr '(?i)^play\s+\S' "$clean"
        if string match -qr '(?i)(song|music)\b' "$clean"
            echo "skill|play_song|Local music playback"
            return
        end
    end
    if set -l g_route (_agent_route_google "$cmd")
        echo "skill|$g_route|Google Calendar or Gmail"
        return
    end
    if set -l chat_route (_agent_chat_intent_route "$cmd")
        echo "skill|$chat_route|Chat engine ($chat_route)"
        return
    end
    if _agent_is_file_size_find "$cmd"
        echo "skill|find_files_by_size $cmd|Find files by size threshold"
        return
    end
    if string match -qr '(find.*file|search.*file|look.*for.*file|locate.*file)' "$clean"
        set -l file_pat (string replace -r -i '^.*(?:find|search|look for|locate)\s+(?:file\s+)?' '' "$cmd")
        set -l file_pat (string replace -r -i '\s+(?:in|under|from)\s+.+$' '' "$file_pat")
        set file_pat (string trim -- "$file_pat")
        if test -n "$file_pat"
            echo "skill|search_files $file_pat|Find files by name pattern"
        else
            echo "skill|search_files|Find files by name pattern"
        end
        return
    end
    if set -l aie_route (_agent_route_aie "$cmd")
        echo "skill|$aie_route|Artificial Internet Enhancements"
        return
    end
    if set -l prof_route (_agent_route_profession "$cmd")
        if test -n "$prof_route"
            echo "skill|$prof_route|Profession domain (explicit)"
            return
        end
    end
    if set -l wa_route (_agent_route_whatsapp_inbox "$cmd")
        echo "skill|$wa_route|WhatsApp inbox listener"
        return
    end
    if _agent_is_skills_help_request "$cmd"
        echo "skill|arka help|Arka skills + active LLM model"
        return
    end
    if string match -qr '(?i)^(remember|memorize|store|don\'t forget|dont forget|keep in mind)\s+' "$clean"
        set -l mem (_arka_memory_detect_fact "$cmd")
        test -z "$mem"; and set mem (string replace -r -i '^(?:remember|memorize|store|don\'t forget|dont forget|keep in mind)\s+(?:that\s+)?' '' "$cmd")
        echo "skill|agent_remember $mem|Long-term memory"
        return
    end
    if string match -qr '(?i)^(recall|what do you remember)' "$clean"
        set -l rq (string replace -r -i '^(?:recall|what do you remember about)\s*' '' "$cmd")
        echo "skill|agent_recall $rq|Recall memories"
        return
    end
    if _arka_memory_probe "$cmd"
        echo "skill|agent_remember $_arka_last_mem_fact|Symbolic memory autodetect"
        return
    end
    if _agent_is_system_info_question "$cmd"
        if _agent_is_hardware_fact_question "$cmd"
            set -l comp (_agent_parse_hardware_component "$cmd")
            echo "skill|system_info $comp|Local hardware fact ($comp)"
        else
            echo "skill|system_info|Local OS/CPU/GPU/RAM/disk overview"
        end
        return
    end
    if _agent_is_knowledge_question "$cmd"
        set -l kq (_agent_normalize_knowledge_q "$cmd")
        test -z "$kq"; and set kq $cmd
        echo "skill|web_answer $kq|Factual web lookup"
        return
    end
    if _agent_is_describe_screen_request "$cmd"
        set -l parts (_agent_build_describe_screen_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Capture screen after countdown and describe with vision"
        return
    end
    if _agent_is_advisory_question "$cmd"
        echo "skill|agent_ask $cmd|AI gathers context via shell, then answers"
        return
    end
    if _agent_is_files_preference_question "$cmd"
        echo "skill|files_preference_help $cmd|Where Arka saves images and how to change it"
        return
    end
    if set -l g_route (_agent_route_google "$cmd")
        echo "skill|$g_route|Google Calendar or Gmail"
        return
    end
    if _agent_is_file_size_find "$cmd"
        echo "skill|find_files_by_size $cmd|Find files by size threshold"
        return
    end
    if _agent_is_chart_request "$cmd"
        set -l parts (_agent_build_chart_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Line, bar, pie, or scatter chart (matplotlib PNG)"
        return
    end
    if _agent_is_model_select_request "$cmd"
        set -l parts (_agent_build_model_select_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Recommend LLM models from PC resources"
        return
    end
    if _agent_is_ascii_art_request "$cmd"
        set -l parts (_agent_build_ascii_art_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|ASCII banner or image-to-ASCII art (figlet)"
        return
    end
    if _agent_is_drawing_ask_request "$cmd"
        set -l parts (_agent_build_drawing_ask_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Vision analysis of blueprints, drawings, and scanned specs"
        return
    end
    if _agent_is_describe_screen_request "$cmd"
        set -l parts (_agent_build_describe_screen_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Capture screen after countdown and describe with vision"
        return
    end
    if _agent_is_describe_image_request "$cmd"
        set -l parts (_agent_build_describe_image_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Describe a photo or image via local vLLM"
        return
    end
    if _agent_is_routines_request "$cmd"
        set -l parts (_agent_build_routines_cmd "$cmd")
        test -n "$parts"; and echo "skill|$parts|Daily or hourly scheduled task"
        return
    end
    if _agent_is_desktop_organize_request "$cmd"
        echo "skill|classify_files|Auto-sort files in Downloads by type"
        return
    end
    if _agent_is_platform_howto_question "$cmd"
        echo "skill|platform_howto $cmd|Platform-specific app/UI how-to"
        return
    end
    if _agent_is_model_select_request "$cmd"
        set -l parts (_agent_build_model_select_cmd "$cmd")
        if test -n "$parts"
            echo "skill|$parts|Recommend LLM models from PC resources"
            return
        end
    end
    if _agent_is_life_sciences_request "$cmd"
        set -l ls (_agent_route_life_sciences "$cmd")
        if test -n "$ls"
            echo "skill|$ls|Life sciences plugin catalog"
            return
        end
    end
    if _agent_is_gemini_cli_request "$cmd"
        set -l gc (_agent_build_gemini_cli_cmd "$cmd")
        if test -n "$gc"
            echo "skill|$gc|Google Gemini CLI agent"
            return
        end
    end
    if _agent_is_general_chat "$cmd"
        set -l route (_agent_route_general_chat "$cmd")
        echo "skill|$route|Conversational question via AI"
        return
    end
    if string match -qr '(?i)(system\s*monitor|system\s*status|show\s+(me\s+)?(system\s+)?(monitor|resources)|check\s+(cpu|ram|memory|disk|battery)|\b(cpu|ram|memory)\s+(usage|load|percent)|how\s+much\s+(cpu|ram|memory)\s+(left|free|used)|\buptime\b|\bbattery\b)' "$clean"
        echo "skill|system_monitor|Live resource monitor"
        return
    end
    if test "$route_mode" = symbolic_only
        echo "none||No symbolic match (ROUTE_MODE=symbolic_only)"
    else if test "$route_mode" = ai
        echo "none||No route after AI + symbolic passes"
    else
        echo "llm|interpret|No offline rule; use LLM or add a skill"
    end
end

function _agent_correct_interpretation --description "Fix bad LLM skill picks using rules (internal)"
    set -l cmd $argv[1]
    set -l interpreted $argv[2]
    set -l clean (string lower "$cmd")

    if _agent_is_nearby_places_question "$cmd"
        echo (_agent_build_nearby_cmd "$cmd")
        return
    end

    if _agent_is_video_search_request "$cmd"
        echo (_agent_build_video_search_cmd "$cmd")
        return
    end

    if _agent_is_translate_request "$cmd"
        echo (_agent_build_translate_cmd "$cmd")
        return
    end

    if _agent_is_pr_check_request "$cmd"
        set -l prr (_agent_route_pr_check "$cmd")
        test -n "$prr"; and echo "$prr"
        return
    end

    if _agent_is_survival_lang_request "$cmd"
        echo (_agent_build_survival_lang_cmd "$cmd")
        return
    end

    if set -l g_route (_agent_route_google "$cmd")
        echo $g_route
        return
    end

    if _agent_is_file_size_find "$cmd"
        echo (_agent_route_file_size_find "$cmd")
        return
    end

    if _agent_is_chart_request "$cmd"
        echo (_agent_build_chart_cmd "$cmd")
        return
    end

    if _agent_is_model_select_request "$cmd"
        echo (_agent_build_model_select_cmd "$cmd")
        return
    end

    if _agent_is_ascii_art_request "$cmd"
        echo (_agent_build_ascii_art_cmd "$cmd")
        return
    end

    if _agent_is_drawing_ask_request "$cmd"
        echo (_agent_build_drawing_ask_cmd "$cmd")
        return
    end

    if _agent_is_describe_screen_request "$cmd"
        echo (_agent_build_describe_screen_cmd "$cmd")
        return
    end

    if _agent_is_describe_image_request "$cmd"
        echo (_agent_build_describe_image_cmd "$cmd")
        return
    end

    if _agent_is_routines_request "$cmd"
        echo (_agent_build_routines_cmd "$cmd")
        return
    end

    if _agent_is_remind_request "$cmd"
        echo (_agent_build_remind_cmd "$cmd")
        return
    end

    if _agent_is_gmail_summarize_request "$cmd"
        echo (_agent_build_gmail_cmd "$cmd" summarize)
        return
    end

    if string match -qr '(?i)^inbox_agent\b' "$interpreted"
        if set -l g_route (_agent_route_google "$cmd")
            echo $g_route
            return
        end
    end

    if _agent_is_investment_question "$cmd"
        set -l topic (_agent_strip_query_prefix "$cmd")
        echo "predictions --domain stocks --deep "(string escape --style=script -- $topic)
        return
    end

    if test -n "$interpreted"; and _agent_skill_matches_request "$cmd" "$interpreted"
        echo "$interpreted"
        return
    end

    if string match -qr '(?i)^system_monitor\b' "$interpreted"
        if _agent_is_system_info_question "$cmd"
            echo (_agent_route_system_info "$cmd")
            return
        end
        if _agent_is_advisory_question "$cmd"
            echo "agent_ask $cmd"
            return
        end
    end

    if string match -qr '(?i)^agent_ask\b' "$interpreted"
        if _agent_is_files_preference_question "$cmd"
            echo "files_preference_help $cmd"
            return
        end
        if _agent_is_platform_howto_question "$cmd"
            echo "platform_howto $cmd"
            return
        end
        if _agent_is_knowledge_question "$cmd"
            set -l kq (_agent_normalize_knowledge_q "$cmd")
            test -z "$kq"; and set kq $cmd
            echo "web_answer $kq"
            return
        end
        if _agent_is_system_info_question "$cmd"
            echo (_agent_route_system_info "$cmd")
            return
        end
    end

    if _agent_is_files_preference_question "$cmd"
        echo "files_preference_help $cmd"
        return
    end

    if _agent_is_desktop_organize_request "$cmd"
        echo "classify_files"
        return
    end

    if set -l g_route (_agent_route_google "$cmd")
        echo $g_route
        return
    end

    if string match -qr '(?i)^web_answer\b' "$interpreted"
        if set -l g_route (_agent_route_google "$cmd")
            echo $g_route
            return
        end
        if _agent_is_investment_question "$cmd"
            set -l topic (_agent_strip_query_prefix "$cmd")
            echo "predictions --domain stocks --deep "(string escape --style=script -- $topic)
            return
        end
        if _agent_is_system_info_question "$cmd"
            echo (_agent_route_system_info "$cmd")
            return
        end
        if _agent_is_platform_howto_question "$cmd"
            echo "platform_howto $cmd"
            return
        end
    end

    if string match -qr '(?i)^search_web\b' "$interpreted"
        if _agent_is_platform_howto_question "$cmd"
            echo "platform_howto $cmd"
            return
        end
        if _agent_is_knowledge_question "$cmd"
            set -l kq (_agent_normalize_knowledge_q "$cmd")
            test -z "$kq"; and set kq $cmd
            echo "web_answer $kq"
            return
        end
    end

    if _agent_is_usage_question "$cmd"
        set -l period (_agent_parse_usage_period "$cmd")
        echo "app_usage $period"
        return
    end

    if string match -qr '(?i)^play_movie\b' "$interpreted"
        set -l rest (string replace -r '^play_movie\s+' '' "$interpreted")
        set -l norm (_play_normalize_media_query "$rest")
        if test -n "$norm"
            echo "play_movie $norm"
            return
        end
    end

    if string match -qr '(?i)^play_song\b' "$interpreted"
        set -l rest (string replace -r '^play_song\s+' '' "$interpreted")
        set -l norm (_play_normalize_media_query "$rest")
        if test -n "$norm"
            echo "play_song $norm"
            return
        end
    end

    if _agent_is_essay_request "$cmd"
        set -l topic (_agent_normalize_essay_topic "$cmd")
        test -z "$topic"; and set topic $cmd
        echo "web_essay $topic"
        return
    end

    if _agent_is_storage_breakdown_question "$cmd"
        echo "disk_breakdown"
        return
    end

    if _agent_is_pdf_ingest_request "$cmd"
        set -l pdf (_agent_parse_pdf_path "$cmd")
        if test -n "$pdf"
            echo "pdf_ingest $pdf"
        else
            echo "pdf_ingest"
        end
        return
    end

    if _agent_is_pdf_question "$cmd"
        echo (_agent_pdf_ask_cmd "$cmd")
        return
    end

    if _agent_is_system_info_question "$cmd"
        echo (_agent_route_system_info "$cmd")
        return
    end

    if _agent_is_platform_howto_question "$cmd"
        echo "platform_howto $cmd"
        return
    end

    if _agent_is_knowledge_question "$cmd"
        set -l kq (_agent_normalize_knowledge_q "$cmd")
        test -z "$kq"; and set kq $cmd
        echo "web_answer $kq"
        return
    end

    if _agent_is_advisory_question "$cmd"
        echo "agent_ask $cmd"
        return
    end

    if string match -qr '(?i)^macro(\s+\d+)?$' "$clean"
        set -l n (string match -r '(?i)^macro\s+(\d+)$' "$clean")[2]
        if test -n "$n"
            echo "stock macro $n"
        else
            echo "stock macro"
        end
        return
    end
    if string match -qr '(?i)^emotion(\s+\d+)?$' "$clean"
        set -l n (string match -r '(?i)^emotion\s+(\d+)$' "$clean")[2]
        if test -n "$n"
            echo "stock emotion $n"
        else
            echo "stock emotion"
        end
        return
    end
    if string match -qr '(?i)^stock\s+macro(\s+\d+)?$' "$interpreted"
        and string match -qr '(?i)^macro(\s+\d+)?$' "$clean"
        set -l n (string match -r '(?i)^macro\s+(\d+)$' "$clean")[2]
        if test -n "$n"
            echo "stock macro $n"
        else
            echo "stock macro"
        end
        return
    end

    if _agent_is_general_chat "$cmd"
        echo (_agent_route_general_chat "$cmd")
        return
    end

    if string match -qr '(?i)(install|get|setup).*(with|via|using)\s+apt|\bapt\s+install' "$clean"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            echo "install_apt $app"
            return
        end
    end
    if string match -qr '(?i)(install|get|setup).*(with|via|using)\s+brew|\bhomebrew\s+install|\bbrew\s+install' "$clean"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            echo "install_brew $app"
            return
        end
    end
    if string match -qr '(?i)(install|get|setup).*(flatpak|flathub)' "$clean"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            echo "install_flatpak $app"
            return
        end
    end
    if string match -qr '(?i)(install|get|setup).*snap' "$clean"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            echo "install_snap $app"
            return
        end
    end
    if string match -qr '(?i)((search|query|find).*(flatpak|snap))' "$clean"
        set -l q (string replace -r -i '^.*\bfor\s+' '' "$cmd" | string trim)
        echo "search_stores $q"
        return
    end
    if string match -qr '(?i)^(install|get|setup)\s+' "$clean"
        and not string match -qr '(flatpak|flathub|snap|apt|brew|homebrew)' "$clean"
        if _agent_is_python_pip_install "$cmd"
            echo (_agent_parse_install_uv "$cmd")
            return
        end
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"; and not _install_target_is_package_file "$app"
            echo "install_app $app"
            return
        end
    end
    if string match -qr '(?i)(intel|graphics|gpu).*(driver|issue)|driver has known|recommended driver' "$clean"
        set -l app (_agent_parse_install_app_name "$cmd")
        test -z "$app"; and set app ""
        if string match -qr '(?i)^fix\b' "$clean"; or string match -qr 'intel.*graphics' "$clean"
            echo "fix_graphics_driver"
            return
        end
    end
    if string match -qr '(?i)(weather|forecast|temp|rain|sunny|cloudy|snow|storm|umbrella|will it rain|is it going to rain|is it raining)' "$clean"
        echo "weather"
        return
    end
    set -l skill_first (string split -f 1 " " -- "$interpreted")[1]
    if test "$skill_first" = download_file
        if string match -qr '(?i)(intel|graphics|gpu).*(driver|issue)|driver has known|recommended driver' "$clean"
            echo "fix_graphics_driver"
            return
        end
    end
    if test "$skill_first" = install_package
        set -l pkg (string replace -r '^install_package\s+' '' "$interpreted" | string trim -c "'\"")
        if test -n "$pkg"; and not _install_target_is_package_file "$pkg"
            echo "install_app $pkg"
            return
        end
    end

    echo ""
end

function agent_route --description "Show how agent would route a request (no execution)"
    set -l cmd (string join " " $argv)
    if test -z "$cmd"
        echo "Usage: agent_route <natural language request>"
        echo "Example: agent_route \"install telegram from flatpak\""
        return 1
    end
    set -l guess (_agent_guess_route "$cmd")
    set -l parts (string split "|" -- "$guess")
    printf '%s\n' (set_color --bold cyan)"Route plan:"(set_color normal)
    echo "  Kind:   $parts[1]"
    echo "  Action: $parts[2]"
    echo "  Why:    $parts[3]"
end

function install_flatpak --description "Search Flathub and install a Flatpak app by name"
    if test (count $argv) -eq 0
        echo "Usage: install_flatpak <app name>"
        echo "Example: install_flatpak telegram"
        return 1
    end
    if not command -v flatpak >/dev/null
        echo (set_color red)"flatpak is not installed."(set_color normal)
        return 1
    end
    set -l query (string join " " $argv)
    echo (set_color cyan)"Searching Flathub for: $query"(set_color normal)
    set -l line (flatpak search "$query" 2>/dev/null | grep -v -i '^No matches' | head -1)
    if test -z "$line"
        echo (set_color yellow)"No Flatpak matches. Try: search_stores $query"(set_color normal)
        return 1
    end
    set -l app_id (echo "$line" | awk -F'\t' '{print $3}')
    if test -z "$app_id"
        set app_id (echo "$line" | tr '\t' ' ' | awk '{print $3}')
    end
    echo (set_color green)"Installing: $app_id"(set_color normal)
    echo (set_color brblack)"  $line"(set_color normal)
    flatpak install -y flathub "$app_id"
end

function install_apt --description "Install a package with apt (sudo)"
    if test (count $argv) -eq 0
        echo "Usage: install_apt <package>"
        echo "Example: install_apt telegram"
        echo "Example: agent \"install telegram with apt\""
        return 1
    end
    set -l pkg (string join " " $argv | string trim)
    switch $pkg
        case telegram
            set pkg telegram-desktop
        case code vscode
            set pkg code
        case chrome google-chrome
            set pkg google-chrome-stable
    end
    echo (set_color cyan)"Installing via apt: $pkg"(set_color normal)
    if not command -v apt >/dev/null
        echo (set_color red)"apt not found on this system."(set_color normal)
        return 1
    end
    sudo apt update
    sudo apt install -y $pkg
end

function install_snap --description "Search Snap Store and install a snap package by name"
    if test (count $argv) -eq 0
        echo "Usage: install_snap <app name>"
        echo "Example: install_snap telegram"
        return 1
    end
    if not command -v snap >/dev/null
        echo (set_color red)"snap is not installed."(set_color normal)
        return 1
    end
    set -l query (string join " " $argv)
    echo (set_color cyan)"Searching Snap for: $query"(set_color normal)
    set -l line (snap find "$query" 2>/dev/null | head -2 | tail -1)
    if test -z "$line"
        echo (set_color yellow)"No Snap matches. Try: search_stores $query"(set_color normal)
        return 1
    end
    set -l snap_name (echo "$line" | awk '{print $1}')
    echo (set_color green)"Installing snap: $snap_name"(set_color normal)
    sudo snap install "$snap_name"
end

function install_uv --description "Install Python packages with uv pip (--cpu/--cuda for PyTorch wheels)"
    set -l pkgs
    set -l use_cpu false
    set -l use_cuda false
    for arg in $argv
        switch $arg
            case --cpu --for-cpu
                set use_cpu true
            case --cuda --gpu --for-gpu
                set use_cuda true
            case '-*'
                echo (set_color red)"Unknown option: $arg"(set_color normal)
                return 1
            case '*'
                set -a pkgs $arg
        end
    end

    if test (count $pkgs) -eq 0
        echo "Usage: install_uv [--cpu|--cuda] <package> [package...]"
        echo "Example: install_uv --cpu torch"
        echo "Example: agent \"install torch for cpu\""
        return 1
    end

    if not type -q uv
        echo (set_color red)"uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"(set_color normal)
        return 1
    end

    if test -f .venv/bin/activate.fish
        source .venv/bin/activate.fish
    else if test -f venv/bin/activate.fish
        source venv/bin/activate.fish
    end

    set -l index_url ""
    if test "$use_cpu" = true
        set index_url https://download.pytorch.org/whl/cpu
    else if test "$use_cuda" = true
        set index_url https://download.pytorch.org/whl/cu124
    end

    # torch + torchvision must come from the same PyTorch index or imports break
    if contains -- torch $pkgs; or contains -- pytorch $pkgs
        contains -- torchvision $pkgs; or set -a pkgs torchvision
        contains -- torchaudio $pkgs; or set -a pkgs torchaudio
    end

    echo (set_color --bold cyan)"Installing with uv pip: "(string join " " $pkgs)(set_color normal)
    if test -n "$index_url"
        echo (set_color brblack)"  index: $index_url"(set_color normal)
    end

    if test -n "$index_url"
        uv pip install $pkgs --index-url $index_url
    else
        uv pip install $pkgs
    end
    set -l st $status

    if test $st -eq 0; and type -q pip
        pip freeze >requirements.txt 2>/dev/null
    end
    return $st
end

function install_brew --description "Search Homebrew and install a formula or cask by name"
    if test (count $argv) -eq 0
        echo "Usage: install_brew <app name>"
        echo "Example: install_brew fish"
        echo "Example: agent \"install fish with brew\""
        return 1
    end

    if not command -v brew >/dev/null
        echo (set_color red)"Homebrew is not installed."(set_color normal)
        echo "Install Homebrew from: https://brew.sh"
        echo 'Run: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        return 1
    end

    set -l query (string join " " $argv | string trim)
    if _install_target_is_package_file "$query"
        echo (set_color yellow)"$query looks like a package file — using install_package"(set_color normal)
        install_package $argv
        return $status
    end

    echo (set_color --bold cyan)"Searching Homebrew for: $query"(set_color normal)
    echo ""

    set -l brew_pkg ""
    if brew info "$query" >/dev/null 2>&1
        set brew_pkg "$query"
        echo (set_color green)"Found: $brew_pkg"(set_color normal)
        echo ""
    else
        printf "━━━ Homebrew formulae ━━━\n"
        set -l formula_out (brew search --formulae "$query" 2>/dev/null)
        if test -n "$formula_out"
            printf '%s\n' $formula_out
            set brew_pkg (printf '%s\n' $formula_out | head -1)
        else
            echo (set_color yellow)"  No formula matches"(set_color normal)
        end
        echo ""

        if test -z "$brew_pkg"
            printf "━━━ Homebrew casks ━━━\n"
            set -l cask_out (brew search --cask "$query" 2>/dev/null)
            if test -n "$cask_out"
                printf '%s\n' $cask_out
                set brew_pkg (printf '%s\n' $cask_out | head -1)
            else
                echo (set_color yellow)"  No cask matches"(set_color normal)
            end
            echo ""
        end
    end

    if test -z "$brew_pkg"
        if _agent_is_python_pip_install "install $query"
            echo (set_color yellow)"No Homebrew match — trying uv pip..."(set_color normal)
            set -l uv_line (_agent_parse_install_uv "install $query")
            set -l uv_args (string split " " -- "$uv_line")
            install_uv $uv_args[2..-1]
            return $status
        end
        echo (set_color red)"No Homebrew matches for: $query"(set_color normal)
        return 1
    end

    echo (set_color green)"Installing via Homebrew: $brew_pkg"(set_color normal)
    brew install "$brew_pkg"
end

function install_app --description "Search package stores and install the best match (Homebrew on macOS; Flatpak/Snap/apt on Linux)"
    if test (count $argv) -eq 0
        echo "Usage: install_app <app name>"
        echo "Example: install_app LocalSend"
        echo "Example: agent \"install LocalSend\""
        return 1
    end

    set -l query (string join " " $argv | string trim)
    if _install_target_is_package_file "$query"
        echo (set_color yellow)"$query looks like a package file — using install_package"(set_color normal)
        install_package $argv
        return $status
    end

    if _arka_is_macos
        install_brew $argv
        return $status
    end

    echo (set_color --bold cyan)"Searching Flatpak, Snap, and apt for: $query"(set_color normal)
    echo ""

    set -l fp_id ""
    set -l fp_line ""
    if command -v flatpak >/dev/null
        printf "━━━ Flatpak ━━━\n"
        set -l fp_out (flatpak search "$query" 2>/dev/null | grep -v -i '^No matches' | head -8)
        if test -n "$fp_out"
            printf '%s\n' $fp_out
            set fp_line (printf '%s\n' $fp_out | head -1)
            set fp_id (echo "$fp_line" | awk -F'\t' '{print $3}')
            if test -z "$fp_id"
                set fp_id (echo "$fp_line" | tr '\t' ' ' | awk '{print $3}')
            end
        else
            echo (set_color yellow)"  No Flatpak matches"(set_color normal)
        end
        echo ""
    else
        echo (set_color yellow)"  flatpak not installed"(set_color normal)
        echo ""
    end

    set -l snap_name ""
    if command -v snap >/dev/null
        printf "━━━ Snap ━━━\n"
        set -l sp_out (snap find "$query" 2>/dev/null | head -8)
        if test -n "$sp_out"
            printf '%s\n' $sp_out
            set -l sp_line (printf '%s\n' $sp_out | tail -n +2 | head -1)
            if test -n "$sp_line"
                set snap_name (echo "$sp_line" | awk '{print $1}')
            end
        else
            echo (set_color yellow)"  No Snap matches"(set_color normal)
        end
        echo ""
    else
        echo (set_color yellow)"  snap not installed"(set_color normal)
        echo ""
    end

    set -l apt_pkg ""
    if command -v apt-cache >/dev/null
        printf "━━━ apt ━━━\n"
        set -l apt_out (apt-cache search --names-only "$query" 2>/dev/null | head -8)
        if test -z "$apt_out"
            set apt_out (apt-cache search "$query" 2>/dev/null | head -8)
        end
        if test -n "$apt_out"
            printf '%s\n' $apt_out
            set apt_pkg (printf '%s\n' $apt_out | head -1 | awk '{print $1}')
        else
            echo (set_color yellow)"  No apt matches"(set_color normal)
        end
        echo ""
    else
        echo (set_color yellow)"  apt-cache not available"(set_color normal)
        echo ""
    end

    if test -z "$fp_id"; and test -z "$snap_name"; and test -z "$apt_pkg"
        if _agent_is_python_pip_install "install $query"
            echo (set_color yellow)"No system package — trying uv pip..."(set_color normal)
            set -l uv_line (_agent_parse_install_uv "install $query")
            set -l uv_args (string split " " -- "$uv_line")
            install_uv $uv_args[2..-1]
            return $status
        end
        echo (set_color red)"No matches in Flatpak, Snap, or apt for: $query"(set_color normal)
        echo "Try: search_stores $query"
        return 1
    end

    if test -n "$fp_id"
        echo (set_color green)"Installing from Flatpak: $fp_id"(set_color normal)
        flatpak install -y flathub "$fp_id"
        return $status
    end

    if test -n "$snap_name"
        echo (set_color green)"Installing from Snap: $snap_name"(set_color normal)
        sudo snap install "$snap_name"
        return $status
    end

    echo (set_color green)"Installing from apt: $apt_pkg"(set_color normal)
    sudo apt update
    sudo apt install -y "$apt_pkg"
end

function _agent_call_name --description "Configured agent command name (AGENT_NAME or arka)"
    if test -n "$AGENT_NAME"
        echo (string trim -- "$AGENT_NAME")
    else
        echo arka
    end
end

function _agent_wake_phrases --description "Wake phrases to strip from speech/NL (internal)"
    set -l phrases
    if test -n "$AGENT_WAKE_WORDS"
        for p in (string split "," "$AGENT_WAKE_WORDS")
            set p (string trim -- "$p")
            test -n "$p"; and set -a phrases "$p"
        end
    end
    set -l name (_agent_call_name)
    if test "$name" != agent
        contains -- "$name" $phrases; or set -a phrases "$name"
    end
    contains -- agent $phrases; or set -a phrases agent
    printf '%s\n' $phrases
end

function _agent_stt_quick_map --description "Fix common STT mis-hearings before routing (internal)"
    set -l text (string trim -- "$argv[1]")
    test -z "$text"; and return
    if test "$STT_QUICK_MAP" = 0; or test "$STT_QUICK_MAP" = false
        echo "$text"
        return
    end
    python3 (_arka_py_script arka_stt_map.py) normalize "$text"
end

function _agent_strip_wake --description "Remove wake words from speech transcript or NL command"
    set -l cmd (string trim -- "$argv[1]")
    test -z "$cmd"; and return

    set -l phrases (_agent_wake_phrases)
    set -l rounds 0
    while test $rounds -lt 5
        set -l before "$cmd"
        set -l low (string lower "$cmd")
        for phrase in $phrases
            set -l p (string trim -- "$phrase")
            test -z "$p"; and continue
            set -l pl (string lower "$p")

            for prefix in "$pl," "$pl "
                if string match -qi "$prefix*" "$low"
                    set -l n (math (string length "$prefix") + 1)
                    set cmd (string trim -- (string sub -s $n "$cmd"))
                    set low (string lower "$cmd")
                end
            end
            if test "$low" = "$pl"
                set cmd ""
                set low ""
            end
            for prefix in "hey $pl," "hey $pl " "ok $pl," "ok $pl " "please $pl," "please $pl "
                if string match -qi "$prefix*" "$low"
                    set -l n (math (string length "$prefix") + 1)
                    set cmd (string trim -- (string sub -s $n "$cmd"))
                    set low (string lower "$cmd")
                end
            end
        end
        if string match -qi 'hey,*' "$low"
            set cmd (string trim -- (string sub -s 5 "$cmd"))
        else if string match -qi 'hey *' "$low"
            set cmd (string trim -- (string sub -s 5 "$cmd"))
        end
        set cmd (string trim -- "$cmd")
        test "$cmd" = "$before"; and break
        set rounds (math $rounds + 1)
    end

    echo "$cmd"
end

function _agent_register_call_name --description "Register AGENT_NAME as a command alias for agent"
    set -l name (_agent_call_name)
    if test "$name" = agent
        return 0
    end
    if not string match -qr '^[a-zA-Z][a-zA-Z0-9_-]*$' "$name"
        printf '%s%s%s\n' (set_color yellow) \
            "AGENT_NAME '$name' is not a valid command name; use letters, numbers, _, - only." \
            (set_color normal) >&2
        return 1
    end

    if functions -q "$name"
        switch (functions "$name" | head -1)
            case "*Named agent*"
                functions --erase "$name"
        end
    end

    function $name --description "Named agent ($name → agent; $name listen = wake word)"
        _arka_maybe_reload
        if test (count $argv) -ge 1
            switch $argv[1]
                case speak-lang lang
                    _arka_speak_lang $argv[2..-1]
                    return $status
                case speak-voice voice
                    _arka_speak_voice $argv[2..-1]
                    return $status
                case tts-setup
                    python3 (_arka_py_script edge_speak.py) setup
                    python3 (_arka_py_script indic_tts.py) setup
                    return $status
                case serve
                    _agent_remote_start
                    return $status
                case start up
                    if test (count $argv) -gt 1
                        agent $argv
                        return $status
                    end
                    _arka_start_all
                    return $status
                case autostart
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case install enable on
                                _arka_autostart_install
                            case remove disable off uninstall
                                _arka_autostart_remove
                            case '*'
                                echo "Usage: arka autostart install | remove"
                        end
                    else
                        echo "Usage: arka autostart install   # survive reboot"
                        echo "       arka autostart remove"
                    end
                    return $status
                case phone-env termux-env
                    _arka_phone_env
                    return $status
                case remote
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case start serve
                                _agent_remote_start
                            case stop
                                _agent_remote_stop
                            case status
                                _agent_remote_status
                            case '*'
                                _agent_remote_start
                        end
                    else
                        _agent_remote_start
                    end
                    return $status
                case remote-stop
                    _agent_remote_stop
                    return $status
                case remote-status
                    _agent_remote_status
                    return $status
                case listen start
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case stop off
                                _agent_listen_stop
                                return $status
                            case status
                                _agent_listen_status
                                return $status
                            case fg foreground
                                _agent_listen_start fg
                                return $status
                            case debug
                                _agent_listen_start debug
                                return $status
                            case mics devices
                                set -l wake_py (_arka_wake_python)
                                $wake_py (_arka_py_script arka_wake.py) --list-mics
                                return $status
                            case mic-test test-mic
                                set -l wake_py (_arka_wake_python)
                                $wake_py (_arka_py_script arka_wake.py) --mic-test
                                return $status
                        end
                    end
                    _agent_listen_start $argv[2..-1]
                    return $status
                case debug
                    _agent_listen_start debug
                    return $status
                case models stt
                    set -l wake_py (_arka_wake_python)
                    $wake_py (_arka_py_script arka_wake.py) --models
                    return $status
                case test-audio audio-test stt-test
                    _arka_test_audio $argv[2..-1]
                    return $status
                case voice hf-voice
                    if test (count $argv) -ge 2
                        bash $_ARKA_ROOT/arka_voice_hf.sh $argv[2..-1]
                    else
                        bash $_ARKA_ROOT/arka_voice_hf.sh status
                    end
                    return $status
                case log tail follow
                    tail -f ~/.cache/fish-agent/arka_listen.log
                    return $status
                case usage screen-time apps
                    set -l py (_arka_python)
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case start
                                $py (_arka_py_script arka_usage.py) start
                            case stop
                                $py (_arka_py_script arka_usage.py) stop
                            case gnome
                                $py (_arka_py_script arka_usage.py) gnome
                            case '*'
                                app_usage $argv[2..-1]
                        end
                    else
                        app_usage today
                    end
                    return $status
                case disk storage space
                    set -l rest $argv[2..-1]
                    if test (count $rest) -ge 1; and contains -- $rest[1] usage breakdown
                        set rest $rest[2..-1]
                    end
                    disk_breakdown $rest
                    return $status
                case ask question
                    if test (count $argv) -ge 2
                        arka_ask $argv[2..-1]
                    else
                        echo "Usage: $name ask [--deep] [--youtube] [--speak] <question>"
                    end
                    return $status
                case predict predictions forecast
                    if test (count $argv) -ge 2
                        predictions $argv[2..-1]
                    else
                        predictions
                    end
                    return $status
                case stock stocks market
                    if test (count $argv) -ge 2
                        stock $argv[2..-1]
                    else
                        stock help
                    end
                    return $status
                case agent smart
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case remember mem memory
                                agent_remember $argv[3..-1]
                            case recall
                                agent_recall $argv[3..-1]
                            case trace last
                                agent_trace
                            case why explain
                                agent_why
                            case resume loop
                                agent_resume $argv[3..-1]
                            case research
                                agent_research $argv[3..-1]
                            case nudge
                                agent_nudge
                            case watch
                                agent_watch $argv[3..-1]
                            case routine schedule
                                agent_routine $argv[3..-1]
                            case fanout parallel
                                agent_fanout $argv[3..-1]
                            case code repo
                                agent_code $argv[3..-1]
                            case handoff queue
                                agent_handoff $argv[3..-1]
                            case browser web
                                agent_browser $argv[3..-1]
                            case meeting
                                meeting_agent $argv[3..-1]
                            case study
                                study_agent $argv[3..-1]
                            case inbox
                                inbox_agent $argv[3..-1]
                            case research youtube yt
                                set -l ycmd (_agent_build_youtube_research_cmd (string join " " $argv[3..-1]))
                                _agent_dispatch_one "$ycmd"
                            case compare
                                compare_agent $argv[3..-1]
                            case product product-reviewer product_reviewer
                                product_reviewer $argv[3..-1]
                            case price-check price_check
                                price_check $argv[3..-1]
                            case ask
                                arka_ask $argv[3..-1]
                            case speak-research speak_research yt-speak
                                speak_research $argv[3..-1]
                            case memory semantic
                                semantic_memory $argv[3..-1]
                            case supermemory sm cloud-memory
                                supermemory $argv[3..-1]
                            case voice session
                                voice_session $argv[3..-1]
                            case handoff-notify notify
                                handoff_notify $argv[3..-1]
                            case predict predictions forecast
                                predictions $argv[3..-1]
                            case stock stocks market
                                stock $argv[3..-1]
                            case help
                                echo "Usage: $name agent remember|recall|trace|why|resume|research|nudge|watch|routine|fanout|code|handoff|browser|meeting|study|inbox|compare|ask|speak-research|predict|stock"
                            case '*'
                                agent_research $argv[2..-1]
                        end
                    else
                        echo "Usage: $name agent remember|research|resume|watch|handoff|code|..."
                        echo "  $name agent remember I prefer Gemini for coding"
                        echo "  $name agent research --deep how does TurboQuant work"
                        echo "  $name agent resume list"
                    end
                    return $status
                case pdf document docs
                    set -l py (_arka_python)
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case formats types
                                $py (_arka_py_script arka_pdf_rag.py) formats
                            case status
                                $py (_arka_py_script arka_pdf_rag.py) status
                            case list ls
                                pdf_list
                            case ingest upload add
                                if test (count $argv) -ge 3
                                    pdf_ingest $argv[3]
                                else
                                    echo "Usage: $name pdf ingest <path>"
                                    return 1
                                end
                            case ask query
                                if test (count $argv) -ge 4; and test "$argv[3]" = --doc
                                    pdf_ask --doc $argv[4] $argv[5..-1]
                                else if test (count $argv) -ge 4; and test "$argv[3]" = -d
                                    pdf_ask -d $argv[4] $argv[5..-1]
                                else
                                    pdf_ask $argv[3..-1]
                                end
                            case codebase-ingest codebase
                                if test (count $argv) -ge 3
                                    codebase_ingest $argv[3..-1]
                                else
                                    echo "Usage: $name pdf codebase-ingest <dir> [-n name]"
                                    return 1
                                end
                            case '*'
                                pdf_ask $argv[2..-1]
                        end
                    else
                        $py (_arka_py_script arka_pdf_rag.py) status
                    end
                    return $status
                case rag turboquant
                    set -l py (_arka_python)
                    if test (count $argv) -ge 2
                        switch $argv[2]
                            case setup install
                                $py (_arka_py_script arka_turboquant_install.py) install
                            case check status
                                $py (_arka_py_script arka_turboquant_install.py) check
                            case '*'
                                echo "Usage: $name rag setup|check"
                                echo "  setup — clone Firmamento TurboQuant + editable install (no PyTorch)"
                                echo "  check — verify install (warns if PyPI turboquant/torch is present)"
                                return 1
                        end
                    else
                        $py (_arka_py_script arka_turboquant_install.py) check
                    end
                    return $status
                case aie enhance internet-enhance internet_enhance
                    if test (count $argv) -ge 2
                        internet_enhance $argv[2..-1]
                    else
                        internet_enhance status
                    end
                    return $status
                case whatsapp wa
                    if test (count $argv) -ge 3; and test "$argv[2]" = inbox
                        whatsapp_listen $argv[3..-1]
                    else if test (count $argv) -ge 2
                        whatsapp_listen $argv[2..-1]
                    else
                        whatsapp_listen status
                    end
                    return $status
                case remind
                    if test (count $argv) -ge 2
                        remind $argv[2..-1]
                    else
                        remind status
                    end
                    return $status
                case routines routine schedule
                    if test (count $argv) -ge 2
                        routines $argv[2..-1]
                    else
                        routines list
                    end
                    return $status
                case yt-bulk ytbulk youtube-bulk youtube_bulk yt_bulk
                    if test (count $argv) -ge 2
                        youtube_bulk $argv[2..-1]
                    else
                        youtube_bulk status
                    end
                    return $status
                case summarize summary
                    set -l sum_text (string join " " $argv[2..-1] | string trim)
                    if test (count $argv) -ge 2; and string match -qr '(?i)\b(emails?|gmail|gmails|mail|inbox)\b' "$sum_text"
                        set -l gcmd (_agent_build_gmail_cmd "$sum_text" summarize)
                        _agent_dispatch_one $gcmd
                        return $status
                    end
                    if test (count $argv) -ge 3
                        switch $argv[2]
                            case folder dir directory
                                folder_summarize $argv[3..-1]
                            case youtube yt research
                                set -l ycmd (_agent_build_youtube_research_cmd (string join " " $argv[3..-1]))
                                _agent_dispatch_one "$ycmd"
                            case youtube yt
                                set -l raw_argv $argv[3..-1]
                                set -l text (string join " " $raw_argv | string trim)
                                if test -z "$text"
                                    echo "Usage: $name summarize youtube <video-id|PLid> [--limit N]"
                                    echo "Example: $name summarize youtube PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige"
                                    return 1
                                end
                                set -l first $raw_argv[1]
                                set first (string replace -r -i '^(?:this|the)$' '' "$first" | string trim)
                                set -l url "$first"
                                if not string match -qr '^https?://' "$first"
                                    if string match -qr '^PL[\w-]+$' "$first"
                                        set url "https://www.youtube.com/playlist?list=$first"
                                    else if string match -qr '^[\w-]{11}$' "$first"
                                        set url "https://www.youtube.com/watch?v=$first"
                                    end
                                end
                                set -l pl_args --url $url
                                for a in $raw_argv[2..-1]
                                    set -a pl_args $a
                                end
                                playlist_summarize $pl_args
                            case playlist
                                playlist_summarize $argv[3..-1]
                            case '*'
                                _arka_summarize_media $argv[2..-1]
                        end
                    else if test (count $argv) -ge 2
                        _arka_summarize_media $argv[2..-1]
                    else
                        _arka_summarize_media
                    end
                    return $status
                case research
                    if test (count $argv) -ge 3; and contains -- $argv[2] youtube yt
                        set -l ycmd (_agent_build_youtube_research_cmd (string join " " $argv[3..-1]))
                        _agent_dispatch_one "$ycmd"
                    else if test (count $argv) -ge 2
                        agent_research $argv[2..-1]
                    else
                        echo "Usage: $name research youtube <query> [--limit N] [--focus Q]"
                        echo "       $name research <question>   — unified doc/web/media research"
                        echo "       $name youtube research <query>   — same (default 2 videos)"
                    end
                    return $status
                case download dl
                    if test (count $argv) -lt 2
                        echo "Usage: $name download <url-or-playlist-id> [--range A-B] [--start N] [--end N]"
                        echo "Example: $name download PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige"
                        echo "Example: $name download PLxxx --range 6-9"
                        echo "Example: $name download 'https://youtube.com/playlist?list=PLxxx'"
                        return 1
                    end
                    set -l args $argv[2..-1]
                    set -l url_args
                    set -l dl_flags
                    set -l i 1
                    while test $i -le (count $args)
                        switch $args[$i]
                            case --audio --wait --channel
                                set -a dl_flags $args[$i]
                            case --start --end --range --limit --quality
                                if test $i -lt (count $args)
                                    set -a dl_flags $args[$i] $args[(math $i + 1)]
                                    set i (math $i + 1)
                                end
                            case '*'
                                set -a url_args $args[$i]
                        end
                        set i (math $i + 1)
                    end
                    set -l text (string join " " $url_args | string trim)
                    if test -z "$text"
                        echo "Usage: $name download <url-or-playlist-id> [--range A-B]"
                        return 1
                    end
                    set text (string replace -r -i '^(?:this|the)\s+' '' "$text" | string trim)
                    set -l url "$text"
                    if not string match -qr '^https?://' "$text"
                        if string match -qr '^PL[\w-]+$' "$text"
                            set url "https://www.youtube.com/playlist?list=$text"
                        else if string match -qr '^[\w-]{11}$' "$text"
                            set url "https://www.youtube.com/watch?v=$text"
                        end
                    end
                    if string match -qr '(?i)playlist\?list=|/playlist' "$url"
                        youtube_bulk download $url --wait $dl_flags
                    else if string match -qr '(?i)youtube\.com|youtu\.be' "$url"
                        youtube_download $url $dl_flags
                    else if string match -qr '^https?://' "$url"
                        download_file $url
                    else
                        download_file $url
                    end
                    return $status
                case youtube yt
                    if test (count $argv) -lt 3
                        echo "Usage: $name youtube research <query> [--limit N] [--focus Q]"
                        echo "       $name youtube playlist_summarize <playlist-url|PLid> [--limit N]"
                        echo "       $name youtube transcript <url> [--summarize]"
                        echo "       $name youtube download <url>"
                        echo "Example: $name youtube research react"
                        echo "Example: $name youtube playlist_summarize PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige --limit 5"
                        return 1
                    end
                    switch $argv[2]
                        case research yt-research search
                            if test (count $argv) -ge 4
                                youtube_research $argv[3..-1] --index
                            else
                                echo "Usage: $name youtube research <query> [--limit N]"
                                return 1
                            end
                        case playlist_summarize playlist summarize digest
                            if test (count $argv) -lt 4
                                echo "Usage: $name youtube playlist_summarize <playlist-url|PLid> [--limit N] [-q question]"
                                echo "       $name youtube playlist_summarize --url <playlist-url> [--limit N]"
                                echo "       $name youtube playlist_summarize --folder <downloaded-playlist-dir>"
                                echo "Example: $name youtube playlist_summarize 'https://youtube.com/playlist?list=PLxxx' --limit 5"
                                return 1
                            end
                            set -l raw_argv $argv[3..-1]
                            if contains -- --url $raw_argv; or contains -- --folder $raw_argv
                                _arka_youtube_tools_ready; or return 1
                                playlist_summarize $raw_argv
                                return $status
                            end
                            set -l first $raw_argv[1]
                            set first (string replace -r -i '^(?:this|the)$' '' "$first" | string trim)
                            set -l url "$first"
                            if string match -qr '^PL[\w-]+$' "$first"
                                set url "https://www.youtube.com/playlist?list=$first"
                            else if not string match -qr '^https?://' "$first"
                                echo "Usage: $name youtube playlist_summarize <playlist-url|PLid> [--limit N]"
                                return 1
                            end
                            set -l pl_args --url $url
                            for a in $raw_argv[2..-1]
                                set -a pl_args $a
                            end
                            _arka_youtube_tools_ready; or return 1
                            playlist_summarize $pl_args
                            return $status
                        case transcript captions
                            if test (count $argv) -ge 4
                                youtube_transcript $argv[3..-1]
                            else
                                echo "Usage: $name youtube transcript <url>"
                                return 1
                            end
                        case download dl
                            if test (count $argv) -ge 4
                                youtube_download $argv[3..-1]
                            else
                                echo "Usage: $name youtube download <url>"
                                return 1
                            end
                        case bulk
                            if test (count $argv) -ge 4
                                youtube_bulk $argv[3..-1]
                            else
                                youtube_bulk status
                            end
                        case '*'
                            echo "Unknown: $name youtube $argv[2]"
                            echo "Usage: $name youtube research|playlist_summarize|transcript|download|bulk ..."
                            return 1
                    end
                    return $status
                case queue deep-queue
                    if test (count $argv) -ge 2
                        deep_queue $argv[2..-1]
                    else
                        deep_queue list
                    end
                    return $status
                case brief morning daily
                    daily_brief $argv[2..-1]
                    return $status
                case setup init
                    set -l py python3
                    if test -x "$_ARKA_ROOT/venv-arka/bin/python3"
                        set py "$_ARKA_ROOT/venv-arka/bin/python3"
                    end
                    $py -m arka setup $argv[2..-1]
                    return $status
                case doctor
                    set -l py (_arka_python)
                    $py -m arka doctor
                    return $status
                case personalize onboard onboarding
                    personalize $argv[2..-1]
                    return $status
                case wifi wireless
                    wifi_info $argv[2..-1]
                    return $status
                case compute cores cpu gpu
                    set -l py (_arka_python)
                    $py (_arka_py_script arka_compute.py)
                    return $status
                case refetch update sync
                    set -l py (_arka_python)
                    set -l flags $argv[2..-1]
                    if not set -q flags[1]
                        set flags --install
                    end
                    $py -m arka refetch $flags
                    _arka_reload_config
                    return $status
                case skills plugins extensions
                    set -l py (_arka_python)
                    if test (count $argv) -lt 2
                        $py (_arka_py_script arka_skills.py) list
                        return $status
                    end
                    switch $argv[2]
                        case list ls
                            $py (_arka_py_script arka_skills.py) list
                        case install add
                            if test (count $argv) -lt 3
                                echo "Usage: $name skills install <git-url|path>"
                                return 1
                            end
                            $py (_arka_py_script arka_skills.py) install $argv[3..-1]
                            _arka_load_third_party_skills
                        case refresh reload rescan
                            $py (_arka_py_script arka_skills.py) refresh
                            _arka_load_third_party_skills
                        case info show
                            if test (count $argv) -lt 3
                                echo "Usage: $name skills info <skill-name>"
                                return 1
                            end
                            $py (_arka_py_script arka_skills.py) info $argv[3]
                        case '*'
                            echo "Usage: $name skills list|install <path|git-url>|refresh|info <name>"
                            return 1
                    end
                    return $status
                case supermemory sm memory-cloud
                    supermemory $argv[2..-1]
                    return $status
                case reload refresh relink
                    _arka_reload_command $argv[2..-1]
                    return $status
                case ai-skill-model skill-model skill-models
                    ai-skill-model $argv[2..-1]
                    return $status
                case select_model model_select best_model model_advisor
                    select_model $argv[2..-1]
                    return $status
                case ai-models
                    ai-models $argv[2..-1]
                    return $status
                case ai-pref
                    ai-pref $argv[2..-1]
                    return $status
                case ai-status
                    ai-status
                    return $status
                case stop down
                    if test (count $argv) -gt 1
                        agent $argv
                        return $status
                    end
                    _arka_stop_all
                    return $status
                case status
                    _arka_status_all
                    return $status
                case tell explain describe
                    if test (count $argv) -ge 2
                        set -l raw (string join " " $argv[2..-1])
                        if _agent_is_describe_screen_request "$raw"
                            set -l scmd (_agent_build_describe_screen_cmd "$raw")
                            set -l show $raw
                            echo (set_color yellow)"💡 [Screen → describe_screen $show]"(set_color normal)
                            _agent_dispatch_one "$scmd"
                            return $status
                        end
                        if _agent_is_describe_image_request "$raw"
                            set -l dcmd (_agent_build_describe_image_cmd "$raw")
                            set -l show $raw
                            echo (set_color yellow)"💡 [Image → describe_image $show]"(set_color normal)
                            _agent_dispatch_one "$dcmd"
                            return $status
                        end
                        if _agent_is_github_repo_request "$raw"
                            set -l gr (_agent_route_github_repo "$raw")
                            if test -n "$gr"
                                echo (set_color yellow)"💡 [GitHub repo activity]"(set_color normal)
                                _agent_dispatch_one "$gr"
                                return $status
                            end
                        end
                        if _agent_is_competitions_request "$raw"
                            set -l cr (_agent_route_competitions "$raw")
                            if test -n "$cr"
                                echo (set_color yellow)"💡 [Competitions search]"(set_color normal)
                                _agent_dispatch_one "$cr"
                                return $status
                            end
                        end
                        if _agent_is_bookmarks_request "$raw"
                            set -l br (_agent_route_bookmarks "$raw")
                            if test -n "$br"
                                echo (set_color yellow)"💡 [Bookmarks]"(set_color normal)
                                _agent_dispatch_one "$br"
                                return $status
                            end
                        end
                        if _agent_is_repo_health_request "$raw"
                            set -l rh (_agent_route_repo_health "$raw")
                            if test -n "$rh"
                                echo (set_color yellow)"💡 [Repo health]"(set_color normal)
                                _agent_dispatch_one "$rh"
                                return $status
                            end
                        end
                        if _agent_is_data_ask_request "$raw"
                            set -l da (_agent_route_data_ask "$raw")
                            if test -n "$da"
                                echo (set_color yellow)"💡 [Data Q&A]"(set_color normal)
                                _agent_dispatch_one "$da"
                                return $status
                            end
                        end
                        if _agent_is_generate_data_request "$raw"
                            set -l gd (_agent_route_generate_data "$raw")
                            if test -n "$gd"
                                echo (set_color yellow)"💡 [Generate data]"(set_color normal)
                                _agent_dispatch_one "$gd"
                                return $status
                            end
                        end
                        if _agent_is_docker_status_request "$raw"
                            set -l dr (_agent_route_docker_status "$raw")
                            if test -n "$dr"
                                echo (set_color yellow)"💡 [Docker status]"(set_color normal)
                                _agent_dispatch_one "$dr"
                                return $status
                            end
                        end
                        if _agent_is_clipboard_history_request "$raw"
                            set -l ch (_agent_route_clipboard_history "$raw")
                            if test -n "$ch"
                                echo (set_color yellow)"💡 [Clipboard history]"(set_color normal)
                                _agent_dispatch_one "$ch"
                                return $status
                            end
                        end
                        set -l q $raw
                        set q (string replace -r -i '^me\s+about\s+' '' "$q")
                        set q (string replace -r -i '^me\s+' '' "$q")
                        set q (string replace -r -i '^about\s+' '' "$q")
                        set -l full (string trim -- "tell me $q")
                        if _agent_is_system_info_question "$full"
                            set -l route (_agent_route_system_info "$full")
                            _agent_run_skill_line "$route"
                            return $status
                        end
                        set -l topic (_agent_normalize_knowledge_q "$q")
                        test -z "$topic"; and set topic "$q"
                        if _agent_is_investment_question "$topic"
                            predictions --domain stocks --deep (string escape --style=script -- $topic)
                            return $status
                        end
                        web_answer (_agent_normalize_knowledge_q "tell me about $q")
                        return $status
                    end
                    echo "Usage: $name tell about <topic>"
                    echo "Example: $name tell about computer evolution"
                    return 1
                case write draft compose essay
                    if test (count $argv) -ge 2
                        set -l full_cmd (string join " " $argv[1..-1])
                        if _agent_is_gmail_draft_request "$full_cmd"
                            set -l gcmd (_agent_build_gmail_draft_cmd "$full_cmd")
                            if test -n "$gcmd"
                                echo (set_color yellow)"💡 [Gmail draft]"(set_color normal)
                                _agent_dispatch_one "$gcmd"
                                return $status
                            end
                        end
                        web_essay (_agent_normalize_essay_topic "write "(string join " " $argv[2..-1]))
                        return $status
                    end
                    echo "Usage: $name write an essay about <topic>"
                    echo "Example: $name write an essay about computer vision"
                    return 1
                case speak say read aloud
                    _arka_speak_ask $argv[2..-1]
                    return $status
            end
        end
        agent $argv
    end
    complete -c "$name" -w agent
end

function _arka_speak_ask --description "Answer a question via agent and read the reply aloud (internal)"
    if test (count $argv) -lt 1
        set -l call (_agent_call_name)
        echo "Usage: $call speak <question>"
        echo "Example: $call speak what are the top places in india"
        return 1
    end
    set -l q (string join " " $argv)

    if _agent_is_translate_request "$q"
        set -l parsed (_agent_parse_translate_nl "$q")
        if test -n "$parsed"
            set -l parts (string split \t "$parsed" --max 2)
            set -l lang $parts[1]
            set -l text $parts[2]
            set -l py (_arka_python)
            set -l translated ($py (_arka_py_script arka_survival_lang.py) --quiet $lang $text 2>/dev/null)
            if test -z "$translated"
                return 1
            end
            echo "$text → $translated"
            if _agent_speak_enabled
                set -l prev_speak_lang ""
                if set -q SPEAK_LANG
                    set prev_speak_lang $SPEAK_LANG
                end
                set -l tts_lang (_agent_speak_lang_for_target $lang)
                if test -n "$tts_lang"
                    set -gx SPEAK_LANG $tts_lang
                end
                set -gx ARKA_TTS_QUIET 1
                speak_aloud "$translated" 2>/dev/null
                if test -n "$prev_speak_lang"
                    set -gx SPEAK_LANG $prev_speak_lang
                else
                    set -e SPEAK_LANG
                end
                set -e ARKA_TTS_QUIET
            end
            return 0
        end
    end

    set -l out (agent $argv)
    set -l st $status
    printf '%s\n' "$out"
    if test -n "$out"
        _agent_speak_reply "$out"
    end
    return $st
end

function _agent_strip_color --description "Remove ANSI color codes for TTS (internal)"
    printf '%s' "$argv[1]" | sed 's/\x1b\[[0-9;]*m//g'
end

function _agent_voice_enabled --description "True when running from arka listen / voice (internal)"
    if set -q VOICE; and test "$VOICE" = 1
        return 0
    end
    if set -q AGENT_VOICE; and test "$AGENT_VOICE" = 1
        return 0
    end
    return 1
end

function _agent_with_voice_context --description "Prepend multi-turn voice context for LLM skills (internal)"
    set -l question (string join " " $argv)
    if _agent_voice_enabled; and set -q VOICE_CONTEXT; and test -n "$VOICE_CONTEXT"
        printf '%s\n\nCurrent question: %s' "$VOICE_CONTEXT" "$question"
        return 0
    end
    echo "$question"
end

function _agent_voice_speak --description "Speak text when voice mode is on (internal)"
    if not _agent_voice_enabled
        return 0
    end
    test -z "$argv[1]"; and return 0
    speak_aloud "$argv[1]" 2>/dev/null
end

function _agent_speak_enabled --description "True if voice replies are enabled (internal)"
    if set -q AGENT_SPEAK
        test "$AGENT_SPEAK" = 0 -o "$AGENT_SPEAK" = false; and return 1
    end
    return 0
end

function _agent_extract_speech_text --description "Pull speakable answer body from agent output (internal)"
    set -l raw (_agent_strip_color "$argv[1]")
    test -z "$raw"; and return

    # Prefer content inside answer blocks (may share a line with 🔎 / routing text)
    if string match -q '*━━━ Answer ━━━*' "$raw"
        set raw (string replace -r '.*━━━ Answer ━━━\s*' '' "$raw" | string split '━━━')[1]
    else if string match -q '*━━━ PDF answer ━━━*' "$raw"
        set raw (string replace -r '.*━━━ PDF answer ━━━\s*' '' "$raw" | string split '━━━')[1]
    else if string match -q '*📄*' "$raw"
        set raw (string replace -r '.*━━━ 📄 [^━]+ ━━━\s*' '' "$raw" | string split '━━━')[1]
    end

    # Drop routing / progress noise lines
    set -l cleaned
    for line in (string split \n -- "$raw")
        set -l t (string trim -- "$line")
        test -z "$t"; and continue
        if string match -qr '^(💡|→|▶|🔎)' "$t"
            continue
        end
        if string match -qr '(?i)^(offline routing|running skill|interpreted:)' "$t"
            continue
        end
        set -a cleaned $line
    end
    set raw (string join \n $cleaned)

    set -l spoken
    for line in (string split \n -- "$raw")
        set -l t (string trim -- "$line")
        test -z "$t"; and continue
        set t (string replace -r '^\[(FROM SEARCH|FROM MEMORY)\]\s*' '' "$t")
        set t (string replace -r '^🔎\s*' '' "$t")
        set t (string replace -r '(?i)^model:\s*' '' "$t")
        set t (string trim -- "$t")
        test -z "$t"; and continue
        if string match -qr '(?i)^(offline routing|running skill|interpreted:|model:)' "$t"
            continue
        end
        if string match -q '*━━━*' "$t"
            continue
        end
        set t (string replace -a -r '\*\*([^*]+)\*\*' '$1' "$t")
        set t (string replace -r '^\d+\.\s+' '' "$t")
        set t (string replace -r ':\s*-\s+' ', ' "$t")
        set t (string replace -r ':\s*$' '' "$t")
        set t (string trim -- "$t")
        test -z "$t"; and continue
        set -a spoken $t
    end

    set raw (string join ' ' $spoken)
    set raw (string replace -a -r '\s*\d+\.\s+' ', ' "$raw")
    set raw (string replace -a -r '\s*:\s*-\s+' ', ' "$raw")
    set raw (string replace -a -r '\s+-\s+' ', ' "$raw")
    set raw (string replace -a -r '\.{2,}' '' "$raw")
    set raw (string replace -a -r '\s+' ' ' "$raw" | string trim)
    echo "$raw"
end

function _agent_speak_reply --description "Speak agent output aloud (internal)"
    if not _agent_speak_enabled
        return 0
    end
    set -l raw "$argv[1]"
    test -z "$raw"; and return 0

    set -l py (_arka_python)
    set -l text ($py (_arka_py_script arka_talents.py) voice-format "$raw" 2>/dev/null)
    test -z "$text"; and set text (_agent_extract_speech_text "$raw")
    test -z "$text"; and return 0

    if not speak_aloud "$text"
        echo (set_color yellow)"⚠ Could not speak aloud — run: arka tts-setup"(set_color normal) >&2
        return 1
    end
end

function agent_hear --description "Run agent on speech transcript; speaks the reply"
    set -gx VOICE 1
    set -l text (_agent_stt_quick_map (string join " " $argv))
    if test -z "$text"
        set -l call (_agent_call_name)
        echo "Usage: agent_hear <transcribed phrase>"
        echo "Example: agent_hear hey $call install torch for cpu"
        echo ""
        echo "Voice replies: AGENT_SPEAK=1 (default). Set AGENT_SPEAK=0 to disable."
        echo "Multi-turn: say follow-ups; 'end conversation' to clear session."
        return 1
    end
    set -l stripped (_agent_strip_wake "$text")
    if test -z "$stripped"
        set -l call (_agent_call_name)
        speak_aloud "I didn't catch a command after $call." 2>/dev/null
        echo (set_color yellow)"No command after wake word."(set_color normal)
        return 1
    end

    if _agent_try_listen_control "$stripped"
        return $status
    end

    set -l py (_arka_python)
    set -l action ($py (_arka_py_script arka_talents.py) voice-field action "$stripped" 2>/dev/null)
    test -z "$action"; and set action run

    switch $action
        case clear
            _arka_talents voice-clear
            speak_aloud "Conversation cleared." 2>/dev/null
            return 0
        case status
            set -l voice_st ($py (_arka_py_script arka_talents.py) voice-status 2>/dev/null)
            printf '%s\n' "$voice_st"
            speak_aloud "$voice_st" 2>/dev/null
            return 0
        case help
            set -l help ($py (_arka_py_script arka_talents.py) voice-help 2>/dev/null)
            printf '%s\n' "$help"
            speak_aloud "$help" 2>/dev/null
            return 0
    end

    set -l route_text ($py (_arka_py_script arka_talents.py) voice-field route_text "$stripped" 2>/dev/null)
    test -z "$route_text"; and set route_text "$stripped"
    set -l llm_ctx ($py (_arka_py_script arka_talents.py) voice-field llm_context "$stripped" 2>/dev/null)
    set -l ack ($py (_arka_py_script arka_talents.py) voice-field ack "$stripped" 2>/dev/null)

    if test -n "$llm_ctx"
        set -gx VOICE_CONTEXT "$llm_ctx"
    else
        set -e VOICE_CONTEXT 2>/dev/null
    end

    if test -n "$ack"
        speak_aloud "$ack" 2>/dev/null &
    end

    set -l out (agent $route_text 2>&1)
    set -l st $status
    set -e VOICE_CONTEXT 2>/dev/null
    printf '%s\n' "$out"
    $py (_arka_py_script arka_talents.py) voice-record --user "$stripped" --assistant "$out" 2>/dev/null
    if test $st -eq 0
        _agent_speak_reply "$out"
    else if test -n "$out"
        _agent_speak_reply "$out"
    else
        _agent_speak_reply "Sorry, that failed."
    end
    return $st
end

function _arka_wake_python --description "Python for wake listener venv (internal)"
    set -l py $_ARKA_ROOT/venv-arka/bin/python3
    if test -x "$py"
        echo "$py"
    else
        echo python3
    end
end

function _agent_try_listen_control --description "Handle listen/debug/stop voice or CLI cmds (internal)"
    set -l clean (string lower (string trim -- "$argv[1]"))
    switch $clean
        case debug 'listen debug' 'enable debug' 'debug mode' 'turn on debug' 'debug listen' 'start debug'
            _agent_listen_start debug
            return 0
        case 'listen fg' 'listen foreground' fg foreground 'live listen' 'listen live'
            _agent_listen_start fg
            return 0
        case listen 'start listening' 'start listen'
            _agent_listen_start
            return 0
        case stop 'stop listen' 'stop listening'
            _agent_listen_stop
            return 0
        case status 'listen status' 'listener status'
            _agent_listen_status
            return 0
        case 'listen models' 'stt models' 'vosk models'
            set -l wake_py (_arka_wake_python)
            $wake_py (_arka_py_script arka_wake.py) --models
            return 0
    end
    return 1
end

function _arka_local_test --description "Run a local dev test script (internal)"
    set -l script $argv[1]
    if test -z "$script"
        echo "Usage: _arka_local_test <script.py> [args…]"
        return 1
    end
    if not test -f "$script"
        echo (set_color red)"Local test not found:"(set_color normal) " $script"
        echo "Copy from examples/local/ into local/ (gitignored)."
        return 1
    end
    set -l py (_arka_python)
    $py $script $argv[2..-1]
end

function _arka_test_audio --description "Test Arka STT accuracy from an audio/video file (internal)"
    if test (count $argv) -lt 1
        set -l call (_agent_call_name)
        echo "Usage: $call test-audio <file.mp4|wav|mp3> [--expected phrase] [--full] [--no-wake] [--run]"
        echo "Example: $call test-audio ~/Videos/voice-test.mp4 --expected \"play an music\" --full"
        return 1
    end
    _arka_local_test $_ARKA_ROOT/local/tests/test_wake_media.py $argv
end

function _agent_pid_alive --description "True if pid is a running process (internal)"
    set -l pid (string trim -- $argv[1])
    test -z "$pid"; and return 1
    if _arka_is_macos
        ps -p $pid >/dev/null 2>&1
        return $status
    end
    kill -0 $pid 2>/dev/null
end

function _agent_listen_start --description "Start continuous wake-word listener (internal)"
    set -l call (_agent_call_name)
    set -l script (_arka_py_script arka_wake.py)
    set -l pidfile ~/.cache/fish-agent/arka_listen.pid
    set -l logfile ~/.cache/fish-agent/arka_listen.log

    set -l foreground 0
    set -l debug 0
    for flag in $argv
        switch $flag
            case debug -d
                set debug 1
            case fg foreground
                set foreground 1
                set debug 1
        end
    end

    if not test -f "$script"
        echo (set_color red)"Missing $script"(set_color normal)
        return 1
    end

    if test $foreground -eq 0
        if test -f "$pidfile"
            set -l pid (cat "$pidfile" 2>/dev/null)
            if test -n "$pid"; and _agent_pid_alive "$pid"
                if test $debug -eq 1
                    echo (set_color cyan)"Restarting $call listener with debug …"(set_color normal)
                    kill "$pid" 2>/dev/null
                    rm -f "$pidfile"
                else
                    echo (set_color yellow)"$call listener already running (pid $pid)"(set_color normal)
                    echo (set_color brblack)"  debug: $call debug   or   $call listen debug"(set_color normal)
                    return 0
                end
            end
        end
    end

    set -l wake_py (_arka_wake_python)
    mkdir -p ~/.cache/fish-agent
    set -l stt_hint "Vosk"
    if set -q ASSEMBLYAI_API_KEY; and test -n "$ASSEMBLYAI_API_KEY"
        if not set -q STT; or contains -- (string lower "$STT") auto assemblyai aai
            set stt_hint "AssemblyAI → Sarvam → Vosk"
        end
    else if set -q SARVAM_API_KEY; and test -n "$SARVAM_API_KEY"
        if not set -q STT; or contains -- (string lower "$STT") auto sarvam
            set stt_hint "Sarvam → Vosk"
        end
    else if set -q GROQ_API_KEY; and test -n "$GROQ_API_KEY"
        if not set -q STT; or contains -- (string lower "$STT") auto groq
            set stt_hint "Groq Whisper + Vosk wake"
        end
    end
    echo (set_color cyan)"Starting $call wake listener ($stt_hint, first run may download model)..."(set_color normal)
    $wake_py "$script" --check; or begin
        echo (set_color red)"Wake listener setup failed."(set_color normal)
        return 1
    end

    if _agent_tts_parler_needed
        echo (set_color brblack)"Starting Indic Parler-TTS (first run downloads ~3.7GB model)..."(set_color normal)
        _agent_tts_parler_start
    end

    _agent_usage_start

    set -l py_args
    if test $debug -eq 1
        set -gx LISTEN_DEBUG 1
        set py_args --debug
    end

    if test $foreground -eq 1
        if _arka_is_macos
            echo (set_color green)"Debug listen — live STT in this terminal"(set_color normal)
            echo (set_color brblack)"  Stop: hold Control and press C (not Command+C), or run 'arka listen stop' in another tab"(set_color normal)
        else
            echo (set_color green)"Debug listen — live STT in this terminal (Ctrl+C to stop)"(set_color normal)
        end
        echo (set_color brblack)"  hear [wake~] partial   hear [wake=] final   hear [cmd=] command"(set_color normal)
        $wake_py "$script" $py_args
        return $status
    end

    if test $debug -eq 1
        nohup env LISTEN_DEBUG=1 $wake_py "$script" --debug >>"$logfile" 2>&1 &
    else
        nohup $wake_py "$script" >>"$logfile" 2>&1 &
    end
    disown
    sleep 1

    if test -f "$pidfile"; and _agent_pid_alive (string trim (cat "$pidfile"))
        set -l lang en-IN
        if set -q SPEAK_LANG
            set lang $SPEAK_LANG
        end
        echo (set_color green)"Listening for '$call' — say: hey $call, what's the weather"(set_color normal)
        echo (set_color brblack)"  log: $logfile  |  stop: $call stop"(set_color normal)
        if test $debug -eq 1
            echo (set_color brblack)"  debug: tail -f $logfile   or   $call listen fg"(set_color normal)
        else
            echo (set_color brblack)"  debug: $call debug   or   $call listen fg"(set_color normal)
        end
        return 0
    end

    echo (set_color red)"Listener failed to start. Check: $logfile"(set_color normal)
    tail -5 "$logfile" 2>/dev/null
    return 1
end

function _agent_listen_stop --description "Stop wake-word listener (internal)"
    set -l call (_agent_call_name)
    set -l pidfile ~/.cache/fish-agent/arka_listen.pid
    if not test -f "$pidfile"
        echo (set_color yellow)"$call listener is not running"(set_color normal)
        return 0
    end
    set -l pid (cat "$pidfile" 2>/dev/null)
    if test -z "$pid"; or not _agent_pid_alive "$pid"
        rm -f "$pidfile"
        echo (set_color yellow)"$call listener is not running"(set_color normal)
        return 0
    end
    kill "$pid" 2>/dev/null
    rm -f "$pidfile"
    _agent_tts_parler_stop
    echo (set_color green)"Stopped $call listener (pid $pid)"(set_color normal)
end

function _agent_listen_status --description "Wake listener status (internal)"
    set -l call (_agent_call_name)
    set -l pidfile ~/.cache/fish-agent/arka_listen.pid
    set -l logfile ~/.cache/fish-agent/arka_listen.log
    if test -f "$pidfile"
        set -l pid (string trim (cat "$pidfile" 2>/dev/null))
        if test -n "$pid"; and _agent_pid_alive "$pid"
            set -l lang en-IN
            if set -q SPEAK_LANG
                set lang $SPEAK_LANG
            end
            echo (set_color green)"$call listener: running (pid $pid)"(set_color normal)
            echo (set_color brblack)"  log: $logfile  |  voice lang: $lang"(set_color normal)
            return 0
        end
    end
    echo (set_color yellow)"$call listener: stopped"(set_color normal)
    echo "Start with: $call listen"
    return 1
end

function arka_listen --description "Start Arka wake-word listener (alias for arka listen)"
    _agent_listen_start
end

function arka_start --description "Start all Arka services (remote + wake listener)"
    _arka_start_all
end

function arka_stop --description "Stop all Arka services"
    _arka_stop_all
end

function arka_status --description "Show all Arka service status"
    _arka_status_all
end

function arka_speak_lang --description "Set or list Arka voice language (alias for arka speak-lang)"
    _arka_speak_lang $argv
end

function agent --description "Run commands safely: executes safe commands automatically, prompts for dangerous ones"
    _arka_maybe_reload
    set -l cmd (_agent_strip_wake (string trim -- (string join " " -- $argv)))

    if test (count $argv) -gt 0; and test -z "$cmd"
        set -l call (_agent_call_name)
        echo (set_color yellow)"No command after wake word. Example: $call install torch for cpu"(set_color normal)
        return 1
    end
    
    set -l clean_cmd (string lower "$cmd")

    if string match -qr '(?i)^speak\s+' "$clean_cmd"
        set cmd (string replace -r -i '^speak\s+' '' "$cmd")
        set clean_cmd (string lower "$cmd")
    end

    if _agent_is_skills_help_request "$clean_cmd"
        _arka_skills_help_show
        if _agent_voice_enabled
            set -l py (_arka_python)
            set -l speak_text ($py (_arka_py_script arka_talents.py) voice-help 2>/dev/null)
            test -n "$speak_text"; and _agent_speak_reply "$speak_text"
        end
        return 0
    end

    if test (count $argv) -eq 0
        or string match -qr '(?i)^(skills|help|\?|list skills|show skills|agent skills)\s*$' "$clean_cmd"

        if _agent_voice_enabled
            set -l py (_arka_python)
            set -l help ($py (_arka_py_script arka_talents.py) voice-help 2>/dev/null)
            printf '%s\n' "$help"
            _agent_speak_reply "$help"
            return 0
        end
        
        set -l call (_agent_call_name)
        echo (set_color --bold blue)"━━━ Antigravity Agent Custom Skills ━━━"(set_color normal)
        echo ""
        if test "$call" != agent
            echo (set_color cyan)"💡 Callable as: "(set_color --bold)"$call"(set_color normal)" or "(set_color --bold)"agent"(set_color normal)" (same router)"(set_color normal)
        else
            echo (set_color cyan)"💡 Set "(set_color --bold)"AGENT_NAME"(set_color normal)" in $_ARKA_CFG/.env to call this agent by a custom name (speech / multi-agent)."(set_color normal)
        end
        echo (set_color cyan)"💡 Natural language: $call install torch for cpu"(set_color normal)
        echo ""
        
        echo (set_color --bold yellow)"🎵 Music & Entertainment:"(set_color normal)
        echo "  play_spotify <song>    - Play music (xdg-open default Brave / desktop app)"
        echo "  spotify_control <cmd>  - Control playback (MPRIS + DOM; Premium needed for API libs)"
        echo "  play_song [name]       - Search music by name, else play random"
        echo "  stop_music             - Stop/pause song (mpv + Spotify/MPRIS)"
        echo "  play_youtube <query>   - Search and play any video/channel on YouTube via mpv"
        echo "  play_movie [title|folder] - Play by name search or folder path"
        echo ""
        
        echo (set_color --bold yellow)"📁 Files & Folders:"(set_color normal)
        echo "  list_folders [path]    - List subfolder names only"
        echo "  show_folder [path]     - Show files and folders inside a directory"
        echo "  list_files [path] [n]  - List files (optional search depth)"
        echo "  search_files <pat> [dir] - Find files by name pattern"
        echo "  find_files_by_size <NL>   - Find files by size (e.g. less than 100mb)"
        echo "  open_file <file>       - Open file(s) with default app"
        echo ""
        
        echo (set_color --bold yellow)"🛠 Productivity & Utilities:"(set_color normal)
        echo "  open_app <app-name>    - Search and open any desktop application on Ubuntu (fuzzy match)"
        echo "  cheat <tool> <query>   - Instantly fetch code cheat sheets from cht.sh"
        echo "  qr_code <url/text>     - Generate a UTF-8 QR code directly in the terminal"
        echo "  shorten_url <url>      - Shorten a URL via TinyURL and copy to clipboard"
        echo "  pomodoro [f] [b]       - Timer with visual progress bar, alerts, notifications"
        echo "  timer <duration>       - Countdown timer (e.g. 5m, 30s, 1h)"
        echo "  remind <when> <msg>    - Reminder (idle/shutdown aware; list|cancel|status)"
        echo "  routines add daily 9am \"task\" - Schedule daily/hourly tasks (list|install|remove)"
        echo "  todo [action] [task]   - Quick terminal Todo list manager"
        echo "  clipboard [text]       - Read from or write to the system clipboard"
        echo "  translate <lang> <txt> - Translate text to target language via LLM"
        echo "  generate_password [l]  - Generate a secure random password and copy it"
        echo "  generate_password save <name> [len] - Generate + store encrypted by name"
        echo "  generate_password set <name> <pw>    - Store your own password by name"
        echo "  generate_password get <name>        - Retrieve stored password"
        echo "  pass save/set/get/list                - Alias for password vault"
        echo "  weather [location]     - Show weather summary for your local area or a city"
        echo ""
        
        echo (set_color --bold yellow)"🌐 Web & Navigation:"(set_color normal)
        echo "  search_web <query>     - Open a google search for <query> in your browser"
        echo "  open_urls <url1> ...   - Open one or more URLs in your default browser"
        echo "  open_finance           - Open top financial/market tracking websites"
        echo "  open_news              - Open top global and local news websites"
        echo ""
        
        echo (set_color --bold yellow)"📄 Document RAG (PrivateGPT):"(set_color normal)
        echo "  doc_ingest / pdf_ingest <file>  - Ingest PDF, Office, text, code, …"
        echo "  doc_list / pdf_list               - List ingested documents"
        echo "  doc_ask / pdf_ask [--doc DOC] <q> - Ask or summarize any ingested file"
        echo "  data_ask / query_data <file|folder> [q] - Ask questions about CSV, JSON, TSV, etc."
        echo "  drawing_ask <file> <q>           - Vision analysis of blueprints, drawings, scans"
        echo "  describe_image <path|url> [q]    - Describe photos via local vLLM vision"
        echo "  describe_screen [question]       - 10s countdown, capture display, describe"
        echo "  arka pdf status|list|ingest|ask|formats"
        echo "  NL: ingest readme.md  |  summarize notes.docx  |  ask config.fish about routing"
        echo ""
        
        echo (set_color --bold yellow)"💻 System & Diagnostics:"(set_color normal)
        echo "  system_monitor         - Beautiful real-time resource usage card (CPU, RAM, Disk)"
        echo "  system_info            - Fast diagnostic overview of OS, kernel, CPU, GPU, memory, disk, IP"
        echo "  select_model           - Recommend LLM profiles from PC resources (--apply to save)"
        echo "  ip_info                - Show public IP address and geolocation info"
        echo "  speedtest              - Perform a quick terminal internet speed test"
        echo "  port_scan              - Check what local network ports are currently in use"
        echo "  disk_usage [path]      - Analyze space usage of the current directory tree"
        echo "  disk_breakdown [path]  - Space by videos, pictures, documents (CSV in ~/.cache/fish-agent/)"
        echo "  screenshot             - Take a full screenshot and save to Pictures"
        echo "  set_wallpaper <image>  - Set GNOME desktop background (light + dark)"
        echo ""
        
        echo (set_color --bold yellow)"🐙 Development & AI:"(set_color normal)
        echo "  git_summary            - Beautiful git repository overview (status, branches, commits)"
        echo "  pr_check diff|ci|explain|babysit - PR diff, CI status, failure diagnosis, merge-ready loop"
        echo "  open_project [query]   - Search and launch VS Code on a local project repo"
        echo "  crypto_price [coins]   - Get real-time crypto prices (BTC, ETH, etc.) beautifully"
        echo "  currency_convert <amt> <from> <to> - Live currency conversion (USD, EUR, INR, …)"
        echo "  convert / currency       - Aliases for currency_convert"
        echo "  kalshi search <topic>    - Kalshi prediction market search + odds"
        echo "  kalshi market <TICKER>   - One Kalshi market quote"
        echo "  kalshi trending          - Top Kalshi markets by 24h volume"
        echo "  kalshi status            - Kalshi exchange status"
        echo "  sports_score [league]  - Live scores: IPL, cricket, NFL, NBA, EPL, F1, …"
        echo "  live_scores            - Alias for sports_score"
        echo "  lint_python <file>     - Lint Python code automatically using ruff or flake8"
        echo "  browse_web <task>      - Automate browser navigation and action using AI"
        echo "  generate_image <prompt> - Generate images using Gemini API (gemini-2.5-flash-image)"
        echo "  generate_video <prompt> - Real AI video (needs POLLINATIONS_API_KEY or Gemini billing)"
        echo "  compose_video --topic '…' [--llm] - YouTube info video (Unsplash + ffmpeg + TTS)"
        echo "  compose_slides --topic '…' [-f format] [--llm] - Presentation deck (pptx, pdf, html, md, json)"
        echo "  convert_media <file> --to <fmt> - Convert images, video, or slides (Pillow/ffmpeg)"
        echo "  excuse                 - Get a hilarious offline programmer excuse"
        echo "  bored                  - Suggest a quick developer break task or exercise"
        echo "  create_skill <name> <desc> - Dynamically generate a new skill using AI"
        echo "  fix_venv [venv]        - Recreate a virtual environment by deleting and re-creating it"
        echo ""
        
        echo (set_color --bold yellow)"🔌 Third-party plugins:"(set_color normal)
        echo "  arka skills list       - Installed plugins from ~/.config/arka/skills/"
        echo "  arka skills install <path|git-url> - Add a plugin (skill.json + run.py or *.fish)"
        echo "  arka skills refresh    - Rescan plugin folders"
        echo "  NL: demo echo hello    - Routes via plugin triggers (voice + text)"
        echo ""
        
        echo (set_color --bold yellow)"🤖 Automation (~/Projects/python/products/automation):"(set_color normal)
        echo "  search_stores <query>  - Search Flatpak, Snap, and apt for apps"
        if _arka_is_macos
            echo "  install_app <name>     - Search Homebrew and install best match"
            echo "  install_brew <name>    - Install package with Homebrew (brew)"
        else
            echo "  install_app <name>     - Search Flatpak/Snap/apt and install best match"
        end
        echo "  install_uv [--cpu] <pkg> - Install Python packages with uv pip (PyTorch CPU/CUDA)"
        echo "  install_apt <pkg>      - Install package with apt (sudo)"
        echo "  install_flatpak <app>  - Install app from Flathub"
        echo "  install_snap <app>     - Install app from Snap Store"
        echo "  agent_route <request>  - Preview skill/shell/LLM routing (no run)"
        echo "  route_learn list       - Show learned NL → skill routes"
        echo "  route_learn learn \"phrase\" \"skill\" - Teach a custom route"
        echo "  NL: teach route \"phrase\" to \"skill\"  - Learn routing in plain English"
        echo "  download_file <url|name> - Download URL (resume) or check Downloads for file"
        echo "  extract_and_run <zip>   - Extract from Downloads and run (e.g. Unreal Editor)"
        echo "  create_desktop_app [unreal] - Add app menu launcher (.desktop) for Unreal Engine"
        echo "  fix_graphics_driver [url] - Fix Intel/GPU driver warnings (Mesa + vendor link)"
        echo "  install_package <file> - Install .deb/.appimage/.tar.gz/.rpm packages"
        echo "  auto_click             - Auto-click when cursor shape changes (loading detection)"
        echo "  auto_copy              - Auto-copy text selections to clipboard on paste (X11)"
        echo "  decrypt_pdf <path> <pw> - Decrypt password-protected PDF files"
        echo "  pdf_tools merge|split|… - Full PDF toolkit (merge, compress, OCR, protect, …)"
        echo "  classify_files         - Auto-sort files by extension (images, docs, code)"
        echo "  google setup|login     - Google Calendar + Gmail (browser OAuth sign-in)"
        echo "  google gmail|calendar  - Read mail or list events (after login)"
        echo "  mcp list|status|tools  - Model Context Protocol servers and tools"
        echo "  arka mcp add <name>    - Add stdio or HTTP MCP server"
        echo "  agent_hub list|sync    - Shared hub for ollama launch agents"
        echo "  arka agent_hub launch  - Launch agent with ARKA_HUB_* env vars"
        echo "  gemini_cli <prompt>    - Google Gemini CLI agent (npm @google/gemini-cli)"
        echo "  arka gemini status     - Check Gemini CLI install (same as gemini_cli status)"
        echo "  cleanup_downloads      - Remove .zip/.deb/.tar.gz clutter from Downloads"
        echo "  watch_zip              - Watch a folder and auto-extract new .zip files"
        echo "  monitor_x <handle>     - Monitor a Twitter/X profile for new tweets"
        echo "  internet_enhance|aie   - Artificial Internet Enhancements (start/stop/status/cleanup)"
        echo "  youtube_bulk|yt_bulk   - Bulk download YouTube playlists/channels (web UI + CLI)"
        echo "  youtube_download       - Download a single YouTube video/shorts (yt-dlp)"
        echo "  youtube_transcript     - Fetch/summarize YouTube video captions"
        echo "  media_transcript       - Transcribe/summarize local mp3, mp4, wav, …"
        echo "  summarize_url <url>    - Summarize a web page or article"
        echo "  post_x <url>           - Shorten URL (<=40 words); draft by default, --post when authed"
        echo "  post_x install         - Install bird CLI (@steipete/bird; for --post with bird cookies)"
        echo "  daily_brief            - Weather + news headlines (--url-limit for excerpts)"
        echo "  wifi_info              - Current Wi-Fi network and signal"
        echo "  generate_image <prompt> - Generate images with Gemini"
        echo "  ascii_art HELLO        - ASCII banner (figlet / pyfiglet)"
        echo "  ascii_art --from-image photo.jpg - Image to ASCII art"
        echo "  chart line AAPL MSFT --range 3mo  - Stock price chart (matplotlib PNG)"
        echo "  chart bar --data 'Apple:230,Samsung:210' - Bar graph from numbers"
        echo "  drawing_ask plan.pdf <question>   - Blueprint/drawing vision (Gemini)"
        echo "  describe_image photo.jpg          - Photo caption via vLLM vision"
        echo "  describe_screen [question]        - 10s countdown, capture screen, describe"
        echo "  generate_video <prompt> - Real AI video (POLLINATIONS_API_KEY or Gemini billing required)"
        echo ""
        echo (set_color cyan)"  arka aie|yt-bulk|queue|brief|wifi|agent — same via subcommands"(set_color normal)
        echo ""
        echo (set_color --bold yellow)"🤖 Agentic (memory, research, automation):"(set_color normal)
        echo "  agent_remember <fact>     - Long-term memory (Supermemory API + local cache)"
        echo "  agent_recall [query]      - Recall memories (cloud search or local)"
        echo "  supermemory status        - Show memory backend (api vs local)"
        echo "  supermemory remember|recall - Explicit Supermemory commands"
        echo "  semantic_memory           - TurboQuant semantic index on local memories"
        echo "  agent_research [--deep]   - Unified TurboQuant + web + media research"
        echo "  agent_trace / agent_why   - Explain last routing decision"
        echo "  agent_resume list         - Resume interrupted agent_loop"
        echo "  agent_handoff add|run     - Phone ↔ PC task queue"
        echo "  agent_watch / agent_routine - Condition watches & scheduled tasks"
        echo "  agent_fanout / agent_code - Parallel jobs & repo-scoped coding agent"
        echo "  transcript_ask / media_ask - Q&A on video/audio transcripts"
        echo "  rag_setup / rag_status    - TurboQuant RAG backend"
        echo "  predictions [--domain antiques|stocks|strategy] [--deep] <topic> - Opportunity analysis talent"
        echo "  profession ask <domain> <q>       - Domain-aware answer (health, nutrition, startup, …)"
        echo "  profession install <path|git>     - Add third-party profession domain (profession.json)"
        echo "  profession plugins list           - Installed profession plugins"
        echo "  profession setup [domain]       - Clone repos: investor, nutrition, startup, engineer"
        echo "  stock news|prices|analyze TICKER|dashboard - stock_analysis project bridge"
        echo "  arka_ask / speak_research / semantic_memory / supermemory - Unified brain & memory"
        echo ""
        return 0
    end

    set -l first_word $argv[1]
    set -l available_skills (_agent_all_skills)

    # 1. Agent loop (run → feedback → correct)
    if test "$first_word" = loop; or test "$first_word" = agent_loop
        agent_loop $argv[2..-1]
        return $status
    end

    # 2. Direct Skill Execution
    if contains -- "$first_word" $available_skills
        $argv
        return $status
    end

    if _arka_is_third_party_skill "$first_word"
        _arka_run_third_party_skills $first_word $argv[2..-1]
        return $status
    end

    if _agent_try_listen_control "$cmd"
        return $status
    end



    # 4. Natural Language Interpretation
    set -l interpreted ""
    set -l route_source none
    set -l words (string split " " "$cmd")
    set -l args ""
    if test (count $words) -gt 1
        set args (string join " " -- $words[2..-1])
    end

    set -l route_mode (_arka_route_mode)

    if _agent_is_investment_question "$cmd"
        set -l topic (_agent_strip_query_prefix "$cmd")
        set interpreted "predictions --domain stocks --deep "(string escape --style=script -- $topic)
        set route_source offline
    end

    if test -z "$interpreted"; and set -l g_route (_agent_route_google "$cmd")
        set interpreted $g_route
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_gmail_summarize_request "$cmd"
        set interpreted (_agent_build_gmail_cmd "$cmd" summarize)
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_currency_request "$cmd"
        set interpreted (_agent_build_currency_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_remind_request "$cmd"
        set interpreted (_agent_build_remind_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_routines_request "$cmd"
        set interpreted (_agent_build_routines_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_file_size_find "$cmd"
        set interpreted (_agent_route_file_size_find "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_chart_request "$cmd"
        set interpreted (_agent_build_chart_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_model_select_request "$cmd"
        set interpreted (_agent_build_model_select_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_ascii_art_request "$cmd"
        set interpreted (_agent_build_ascii_art_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_drawing_ask_request "$cmd"
        set interpreted (_agent_build_drawing_ask_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_describe_screen_request "$cmd"
        set interpreted (_agent_build_describe_screen_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_describe_image_request "$cmd"
        set interpreted (_agent_build_describe_image_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_download_request "$cmd"
        set interpreted (_agent_build_download_cmd "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"; and _agent_is_clipboard_history_request "$cmd"
        set interpreted (_agent_route_clipboard_history "$cmd")
        set route_source offline
    end

    if test -z "$interpreted"
        set -l offline (_agent_offline_route_cmd "$cmd")
        if test -n "$offline"
            set interpreted $offline
            set route_source offline
        end
    end

    if test -z "$interpreted"; and test "$route_mode" = ai -o "$route_mode" = ai_only
        set interpreted (_agent_llm_route "$cmd" "$available_skills")
        if test -n "$interpreted"
            set route_source llm
            echo (set_color yellow)"💡 [AI routing]"(set_color normal)
        end
    end

    if test -z "$interpreted"; and test "$route_mode" != ai_only
    # 1. Try Local Offline / symbolic translation match
    if string match -qr '(?i)^(?:agent\s+)?loop\s+' "$clean_cmd"
        set -l loop_goal (string replace -r -i '^(?:agent\s+)?loop\s+' '' "$cmd" | string trim)
        if _agent_matches_graphics_driver "$loop_goal"
            echo (set_color yellow)"💡 [Driver fix — using fix_graphics_driver, not agent_loop]"(set_color normal)
            set interpreted (_agent_route_graphics_driver "$cmd")
            set route_source offline
        else
            agent_loop $loop_goal
            return $status
        end
    else if _agent_play_route_ambiguous "$clean_cmd"
        set interpreted (_agent_route_play_ambiguous "$cmd" "$available_skills")
        if test -n "$interpreted"
            if test "$(_arka_route_mode)" = symbolic_only
                set route_source offline
                echo (set_color yellow)"💡 [Offline routing — play/media tie-break]"(set_color normal)
            else
                set route_source llm
                echo (set_color yellow)"💡 [AI routing — ambiguous play/media request]"(set_color normal)
            end
        end
    else if string match -qr '(play.*spotify|spotify)' "$clean_cmd"
        set -l song_query (string replace -r -i '^play\s+(?:song\s+)?(?:on\s+)?spotify(?:\s+of)?\s*' '' "$cmd")
        set song_query (string replace -r -i '^play\s+(?:song\s+)?' '' "$song_query")
        set song_query (string replace -r -i '\s+on\s+spotify(\s|$)' ' ' "$song_query")
        set song_query (string replace -r -i '\s+on\s+spotify$' '' "$song_query")
        set song_query (string replace -r -i '^of\s+' '' "$song_query")
        set song_query (_spotify_normalize_query $song_query)
        set interpreted "play_spotify $song_query"
    else if string match -qr '(?i)(whatsapp\s+inbox|inbox\s+whatsapp|whatsapp\s+listen|listen\s+whatsapp)' "$clean_cmd"
        if string match -qr '(?i)\bstop\b' "$clean_cmd"
            set interpreted "whatsapp_listen stop"
        else if string match -qr '(?i)\b(status|state)\b' "$clean_cmd"
            set interpreted "whatsapp_listen status"
        else if string match -qr '(?i)\b(fg|foreground|debug|log)\b' "$clean_cmd"
            set -l mode fg
            if string match -qr '(?i)\bdebug\b' "$clean_cmd"
                set mode debug
            else if string match -qr '(?i)\blog\b' "$clean_cmd"
                set mode log
            end
            set interpreted "whatsapp_listen $mode"
        else
            set interpreted "whatsapp_listen"
        end
    else if string match -qr '(whatsapp|message.*whatsapp)' "$clean_cmd"
        set -l wa_parts (_parse_whatsapp_nl "$cmd")
        if test (count $wa_parts) -ge 2; and test -n "$wa_parts[1]"
            set -l wa_target $wa_parts[1]
            set -l wa_msg $wa_parts[2]
            if test -n "$wa_msg"
                set interpreted "send_whatsapp $wa_target $wa_msg"
            else
                set interpreted "send_whatsapp $wa_target"
            end
        else
            set interpreted "send_whatsapp"
        end
    else if string match -qr '(?i)^(stop|pause|kill)\s+(?:the\s+|this\s+|that\s+|playing\s+)?(?:song|songs|music|audio|playback|player|spotify|it)\b' "$clean_cmd"
        set interpreted "stop_music"
    else if _agent_is_youtube_research_request "$clean_cmd"
        set interpreted (_agent_build_youtube_research_cmd "$cmd")
        set route_source offline
    else if string match -qr '(?i)(play\s+.*youtube|play\s+(?:a\s+|an\s+)?(?:video|episode|anime)|watch\s+(?:a\s+|an\s+)?|watch\s+.*youtube)' "$clean_cmd"
        and not string match -qr '(?i)(summarize|summary|transcript|research|digest|caption|download|transcribe|playlist)' "$clean_cmd"
        set -l youtube_query (string replace -r -i '^play\s+(?:a\s+|an\s+)?(?:video\s+|episode\s+|anime\s+)?(?:on\s+)?youtube(?:\s+of)?\s*' '' "$cmd")
        set youtube_query (string replace -r -i '^play\s+(?:video\s+|episode\s+|anime\s+)?(?:a\s+|an\s+)?' '' "$youtube_query")
        set youtube_query (string replace -r -i '\s+on\s+youtube$' '' "$youtube_query")
        set youtube_query (string replace -r -i '^of\s+' '' "$youtube_query")
        set youtube_query (string replace -r -i '^watch\s+(?:a\s+|an\s+)?' '' "$youtube_query")
        if test -n "$youtube_query"
            set interpreted "play_youtube $youtube_query"
        else
            set interpreted "play_youtube"
        end
    else if string match -qr '(play.*song|random.*song|local.*music)' "$clean_cmd"
        set -l song_query (string replace -r -i '^play\s+(?:a\s+)?(?:random\s+)?(?:local\s+)?song\s*' '' "$cmd" | string trim)
        if test -n "$song_query"
            set interpreted "play_song $song_query"
        else
            set interpreted "play_song"
        end
    else if string match -qr '(play.*movie|play.*film|play\s+(?:local\s+)?media|rplay|play\s+.+\s+(movie|film|video))' "$clean_cmd"
        set -l movie_query (_play_normalize_media_query "$cmd")
        if test -n "$movie_query"
            set interpreted "play_movie $movie_query"
        else
            set interpreted "play_movie"
        end
    else if string match -qr '(?i)^play\s+.+\s+(from|by)\s+' "$clean_cmd"
        set -l song_query (_play_normalize_media_query "$cmd")
        set interpreted "play_song $song_query"
    else if string match -qr '^play\s+\S' "$clean_cmd"
        set -l play_target (_play_normalize_media_query "$cmd")
        if string match -qr '(?i)(song|music)\b' "$clean_cmd"
            set interpreted "play_song $play_target"
        else if string match -qr '(?i)(spotify)' "$clean_cmd"
            set interpreted "play_spotify $play_target"
        else
            set interpreted "play_movie $play_target"
        end
    else if string match -qr '(list.*folder|show.*folder|folder.*names|what.*folders|name.*of.*folders)' "$clean_cmd"
        set -l folder_path ""
        set -l m (string match -r '(?i)(?:folders?\s+in|folders?\s+under|folders?\s+at)\s+(.+)$' -- "$cmd")
        if test (count $m) -ge 2
            set folder_path (string trim $m[2])
        end
        if test -n "$folder_path"
            set interpreted "list_folders $folder_path"
        else
            set interpreted "list_folders"
        end
    else if string match -qr '(what.*inside|inside.*folder|contents.*of|show.*contents|list.*inside)' "$clean_cmd"
        set -l folder_path ""
        set -l m (string match -r '(?i)(?:inside|contents of|what is in|what.s in)\s+(.+)$' -- "$cmd")
        if test (count $m) -ge 2
            set folder_path (string trim $m[2])
        end
        if test -n "$folder_path"
            set interpreted "show_folder $folder_path"
        else
            set interpreted "show_folder"
        end
    else if string match -qr '(?i)what\s+(?:is\s+)?in\s+(?:the\s+)?(?:folder|directory|downloads|documents|videos|desktop|home|music|pictures)\b' "$clean_cmd"
        set -l folder_path (string replace -r -i '^.*what\s+(?:is\s+)?in\s+(?:the\s+)?' '' "$cmd" | string trim)
        if test -n "$folder_path"
            set interpreted "show_folder $folder_path"
        else
            set interpreted "show_folder"
        end
    else if string match -qr '(?i)what\s+(?:is\s+)?in\s+(~|/|\./)' "$clean_cmd"
        set -l folder_path (string replace -r -i '^.*what\s+(?:is\s+)?in\s+' '' "$cmd" | string trim)
        set interpreted "show_folder $folder_path"
    else if _agent_is_file_size_find "$cmd"
        set interpreted (_agent_route_file_size_find "$cmd")
    else if string match -qr '(find.*file|search.*file|look.*for.*file|locate.*file)' "$clean_cmd"
        set -l file_pat (string replace -r -i '^.*(?:find|search|look for|locate)\s+(?:file\s+)?' '' "$cmd")
        set -l file_pat (string replace -r -i '\s+(?:in|under|from)\s+.+$' '' "$file_pat")
        set file_pat (string trim -- "$file_pat")
        if test -n "$file_pat"
            set interpreted "search_files $file_pat"
        else
            set interpreted "search_files"
        end
    else if string match -qr '(open.*file)' "$clean_cmd"
        set -l file_target (string replace -r -i '^open\s+(?:the\s+)?file\s+' '' "$cmd")
        set interpreted "open_file $file_target"
    else if string match -qr '(?i)(market sentiment|emotion|fear.?greed|crowd|who will (buy|sell)|investor mood|panic|fomo|bullish|bearish)' "$clean_cmd"
        set interpreted "predictions --domain stocks --deep "(string escape --style=script -- $cmd)
    else if string match -qr '(?i)(debt.?to.?equity|d/e ratio|fundamental|balance sheet|p/e ratio|roe|financial ratio|leverage ratio)' "$clean_cmd"
        set interpreted "predictions --domain stocks --deep "(string escape --style=script -- $cmd)
    else if string match -qr '(?i)(recent funding|venture capital|vc funding|series [a-z]|ipo listing|competition|competitor|market share|peer comparison)' "$clean_cmd"
        set interpreted "predictions --domain stocks --deep "(string escape --style=script -- $cmd)
    else if string match -qr '(?i)(disaster|earthquake|flood|cyclone|drought|oil.*price|war|sanction|natural resource|geopolit|which stock.*(rise|increase|surge)|predict.*stock)' "$clean_cmd"
        set interpreted "predictions --domain stocks --deep "(string escape --style=script -- $cmd)
    else if string match -qr '(?i)(where\s+(to|should\s+i)\s+invest|how\s+(to|can\s+i)\s+invest|invest\s+\d|make\s+(?:a\s+)?profit|best\s+(?:place|option|way|stock|fund)\s+to\s+(?:invest|put)|\d+\s+for\s+\d+\s*(?:day|week|month))' "$clean_cmd"
        set -l topic (_agent_strip_query_prefix "$cmd")
        set interpreted "predictions --domain stocks --deep "(string escape --style=script -- $topic)
    else if string match -qr '(?i)^macro(\s+\d+)?$' "$clean_cmd"
        set -l n (string match -r '(?i)^macro\s+(\d+)$' "$clean_cmd")[2]
        if test -n "$n"
            set interpreted "stock macro $n"
        else
            set interpreted "stock macro"
        end
    else if string match -qr '(?i)^emotion(\s+\d+)?$' "$clean_cmd"
        set -l n (string match -r '(?i)^emotion\s+(\d+)$' "$clean_cmd")[2]
        if test -n "$n"
            set interpreted "stock emotion $n"
        else
            set interpreted "stock emotion"
        end
    else if string match -qr '(?i)^(stock|market)\s+(news|prices|policy|strategy|volatility|dashboard|context|invest|macro|emotion|fundamentals|funding|competition)\b' "$clean_cmd"
        set -l stock_rest (string replace -r -i '^(?:stock|market)\s+' '' "$cmd" | string trim)
        set interpreted "stock $stock_rest"
    else if _agent_is_remind_request "$cmd"
        set interpreted (_agent_build_remind_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_routines_request "$cmd"
        set interpreted (_agent_build_routines_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_chart_request "$cmd"
        set interpreted (_agent_build_chart_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_model_select_request "$cmd"
        set interpreted (_agent_build_model_select_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_personalize_request "$cmd"
        set interpreted (_agent_build_personalize_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_ascii_art_request "$cmd"
        set interpreted (_agent_build_ascii_art_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_drawing_ask_request "$cmd"
        set interpreted (_agent_build_drawing_ask_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_describe_screen_request "$cmd"
        set interpreted (_agent_build_describe_screen_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_describe_image_request "$cmd"
        set interpreted (_agent_build_describe_image_cmd "$cmd")
        if test -n "$interpreted"
            set route_source offline
        end
    else if _agent_is_repo_health_request "$cmd"
        set interpreted (_agent_route_repo_health "$cmd")
        set route_source offline
    else if _agent_is_data_ask_request "$cmd"
        set interpreted (_agent_route_data_ask "$cmd")
        set route_source offline
    else if _agent_is_generate_data_request "$cmd"
        set interpreted (_agent_route_generate_data "$cmd")
        set route_source offline
    else if string match -qr '(?i)^(analyze|check)\s+(?:stock\s+)?[A-Z][A-Z0-9.-]{1,12}\b' "$clean_cmd"
        and not _agent_is_repo_health_request "$cmd"
        set -l stock_ticker (string upper (string match -r '(?i)([A-Z][A-Z0-9.-]{1,12})\s*$' "$cmd")[2])
        set interpreted "stock analyze $stock_ticker"
    else if string match -qr '(?i)(predict|prediction|forecast|opportunit).*(antique|stock|market|strategy|invest|collectible|portfolio)|^(predict|forecast)\s+' "$clean_cmd"
        and not _agent_is_kalshi_request "$cmd"
        set -l pred_topic (string replace -r -i '^(?:predict|prediction|forecast|find|analyze|show)\s+(?:opportunities?\s+(?:in|for|about)\s+)?' '' "$cmd" | string trim)
        set -l pred_flags ""
        if string match -qr '(?i)\bantique|collectible|auction|vintage\b' "$clean_cmd"
            set pred_flags "--domain antiques"
        else if string match -qr '(?i)\bstock|share|equity|nifty|sensex|portfolio|market\b' "$clean_cmd"
            set pred_flags "--domain stocks"
        else if string match -qr '(?i)\bstrategy|future|roadmap|outlook\b' "$clean_cmd"
            set pred_flags "--domain strategy"
        end
        if test -n "$pred_topic"
            set interpreted "predictions $pred_flags "(string escape --style=script -- $pred_topic)
        else
            set interpreted "predictions $pred_flags"
        end
    else if _agent_is_generate_thumbnail_request "$clean_cmd"
        set interpreted (_agent_build_generate_thumbnail_cmd "$cmd")
        set route_source offline
    else if _agent_is_ascii_art_request "$clean_cmd"
        set interpreted (_agent_build_ascii_art_cmd "$cmd")
        set route_source offline
    else if _agent_is_generate_image_request "$clean_cmd"
        set interpreted (_agent_build_generate_image_cmd "$cmd")
        set route_source offline
    else if _agent_is_compose_slides_request "$clean_cmd"
        set interpreted (_agent_build_compose_slides_cmd "$cmd")
        set route_source offline
    else if _agent_is_convert_media_request "$clean_cmd"
        set interpreted (_agent_build_convert_media_cmd "$cmd")
        set route_source offline
    else if _agent_is_compose_video_request "$clean_cmd"
        set interpreted (_agent_build_compose_video_cmd "$cmd")
        set route_source offline
    else if string match -qr '(?i)^(generate|create|make|render|produce|animate|film)\s+(?:an?\s+)?(?:video|clip|animation|movie|animated\s+video)\b|^(animate|film)\s+' "$clean_cmd"
        set -l vid_prompt (_agent_parse_video_prompt "$cmd")
        if test -n "$vid_prompt"
            set interpreted "generate_video "(string escape --style=script -- $vid_prompt)
        else
            set interpreted "generate_video"
        end
    else if string match -qr '(?i)^(generate|create|make|draw|paint|sketch|show)\s+(?:an?\s+)?(?:image|picture|photo|art|drawing|sketch|painting|illustration|portrait|landscape)\b|^(draw|paint|sketch)\s+' "$clean_cmd"
        and not string match -qr '(?i)\bascii\s+(?:art|banner)\b' "$clean_cmd"
        and not string match -qr '(?i)\bfiglet\b' "$clean_cmd"
        set -l img_prompt (string replace -r -i '^(?:generate|create|draw|paint|make|sketch)\s+(?:an?\s+)?(?:image|picture|photo|art|drawing|painting|sketch|illustration|portrait|landscape)?\s*(?:of)?\s*' '' "$cmd" | string trim)
        if test -n "$img_prompt"
            set interpreted "generate_image "(string escape --style=script -- $img_prompt)
        else
            set interpreted "generate_image"
        end
    else if string match -qr '(?i)(save|store|remember)\s+(?:password|pass)\s+\S+\s+(?:for|as|named)\s+[a-zA-Z0-9._-]+' "$clean_cmd"
        set -l m (string match -r '(?i)(?:save|store|remember)\s+(?:password|pass)\s+(\S+)\s+(?:for|as|named)\s+([a-zA-Z0-9._-]+)' "$cmd")
        if test (count $m) -ge 3
            set interpreted "generate_password set $m[3] "(string escape --style=script -- $m[2])
        end
    else if string match -qr '(?i)(save|store|remember).*(password|pass).*(for|as|named)|generate.*password.*(for|named)\s+\S' "$clean_cmd"
        set -l pname (_agent_parse_password_name "$cmd")
        if test -n "$pname"
            set interpreted "generate_password save "(string escape --style=script -- $pname)
        else
            set interpreted "generate_password save"
        end
    else if string match -qr '(?i)(get|show|retrieve).*(password|pass).*(for|named)|what.*password.*(for|to)\s+\S' "$clean_cmd"
        set -l pname (_agent_parse_password_name "$cmd")
        if test -n "$pname"
            set interpreted "generate_password get "(string escape --style=script -- $pname)
        end
    else if string match -qr '(?i)\b(list|show)\s+(?:my\s+|saved\s+|stored\s+)?(?:passwords?|passcodes?)\b' "$clean_cmd"
        set interpreted "generate_password list"
    else if string match -qr '(?i)^(generate|create|make)\s+(?:a |an |the |me )?(?:new )?(password|passcode)\b' "$clean_cmd"
        set interpreted "generate_password"
    else if set -l media_route (_agent_route_media "$cmd")
        set interpreted $media_route
    else if set -l ytb_route (_agent_route_youtube_bulk "$cmd")
        set interpreted $ytb_route
    else if set -l ytd_route (_agent_route_youtube_download "$cmd")
        set interpreted $ytd_route
    else if string match -qr '(?i)(youtube.*transcript|transcript.*youtube|video transcript|get transcript.*youtube|summarize.*youtube.*video)' "$clean_cmd"
        set -l yt_target (string replace -r -i '^.*(?:transcript|summarize)\s+(?:for\s+|of\s+)?' '' "$cmd" | string trim)
        if string match -qr '(?i)summarize' "$clean_cmd"
            if test -n "$yt_target"
                set interpreted "youtube_transcript $yt_target --summarize"
            else
                set interpreted "youtube_transcript"
            end
        else if test -n "$yt_target"
            set interpreted "youtube_transcript $yt_target"
        else
            set interpreted "youtube_transcript"
        end
    else if _agent_is_post_x_request "$cmd"
        set interpreted (_agent_build_post_x_cmd "$cmd")
        set route_source offline
    else if string match -qr '(?i)(summarize (this |the )?(url|page|article|website|link)|summarize https?://|summary of https?://)' "$clean_cmd"
        set -l page_url (string match -r 'https?://[^\s]+' "$cmd")
        if test (count $page_url) -ge 1
            set interpreted "summarize_url $page_url[1]"
        else
            set interpreted "summarize_url"
        end
    else if _agent_is_daily_brief_request "$cmd"
        set interpreted "daily_brief $cmd"
    else if string match -qr '(?i)(wifi|wi-fi|wireless).*(info|network|signal|ssid)|what wifi|am i on wifi' "$clean_cmd"
        set interpreted "wifi_info"
    else if string match -qr '(?i)(live\s+(sports?\s+)?scores?|sports?\s+scores?|match\s+scores?|game\s+scores?|ipl\s+(live|score|scores)|nfl\s+scores?|nba\s+scores?|cricket\s+(live|score|scores)|soccer\s+scores?|football\s+scores?|who\s+is\s+winning|today\s*s?\s+(ipl|match|game)s?\s+score|what\s+(is|are)\s+(the\s+)?(live\s+)?(ipl|nfl|nba|cricket|soccer|football|sports?)\s+score)' "$clean_cmd"
        set -l sq (string replace -r -i '^(?:show|get|tell me|what is|what are|give me)\s+' '' "$cmd")
        set interpreted "sports_score $sq"
        set route_source offline
    else if string match -qr '(?i)\b(kalshi|prediction\s+market|kalshi\s+odds|kalshi\s+predictions?)\b' "$clean_cmd"
        set -l kc (_agent_build_kalshi_cmd "$cmd")
        if test -n "$kc"
            set interpreted $kc
            set route_source offline
        end
    else if set -l tp_match (_arka_match_third_party_skill "$cmd")
        if test -n "$tp_match"
            set interpreted $tp_match
            set route_source offline
        end
    else if string match -qr '(weather|forecast|temp|rain|rainy|sunny|cloudy|snow|snowing|storm|hurricane|umbrella|will it rain|is it going to rain|is it raining)' "$clean_cmd"
        set interpreted "hyperlocal_weather $cmd"
        set route_source offline
    else if _agent_is_remind_request "$cmd"
        set interpreted (_agent_build_remind_cmd "$cmd")
        set route_source offline
    else if _agent_is_routines_request "$cmd"
        set -l routine_cmd (_agent_build_routines_cmd "$cmd")
        set interpreted $routine_cmd
        set route_source offline
    else if string match -qr '(timer|countdown)' "$clean_cmd"
        set interpreted "timer $args"
    else if string match -qr '(?i)wallpaper|desktop\s+background|set\s+(?:this|it)\s+as\s+wallpaper|background\s+image' "$clean_cmd"
        set -l img ""
        for w in $words
            if string match -irq '\.(jpe?g|png|webp|gif|bmp|svg)$' -- "$w"
                set img $w
            end
        end
        if test -z "$img"
            set -l m (string match -r '(?i)(?:wallpaper|background)\s+(.+)$' -- "$cmd")
            if test (count $m) -ge 2
                set img (string trim -- $m[2])
            end
        end
        if test -n "$img"
            set interpreted "set_wallpaper $img"
        else
            set interpreted "set_wallpaper"
        end
        set route_source offline
    else if _agent_is_usage_question "$cmd"
        set -l period (_agent_parse_usage_period "$cmd")
        set interpreted "app_usage $period"
        set route_source offline
    else if _agent_is_essay_request "$cmd"
        set -l topic (_agent_normalize_essay_topic "$cmd")
        if test -z "$topic"
            set topic $cmd
        end
        set interpreted "web_essay $topic"
        set route_source offline
    else if string match -qr '^/' "$cmd"
        set -l forced (string trim (string replace -r '^/+?' '' "$cmd"))
        test -z "$forced"; and set forced $cmd
        set interpreted "deep_web_answer $forced"
        set route_source offline
    else if _agent_is_nearby_places_question "$cmd"
        set interpreted (_agent_build_nearby_cmd "$cmd")
        set route_source offline
    else if _agent_is_video_search_request "$cmd"
        set interpreted (_agent_build_video_search_cmd "$cmd")
        set route_source offline
    else if _agent_is_translate_request "$cmd"
        set interpreted (_agent_build_translate_cmd "$cmd")
        set route_source offline
    else if _agent_is_pr_check_request "$cmd"
        set interpreted (_agent_route_pr_check "$cmd")
        set route_source offline
    else if _agent_is_github_repo_request "$cmd"
        set interpreted (_agent_route_github_repo "$cmd")
        set route_source offline
    else if _agent_is_competitions_request "$cmd"
        set interpreted (_agent_route_competitions "$cmd")
        set route_source offline
    else if _agent_is_bookmarks_request "$cmd"
        set interpreted (_agent_route_bookmarks "$cmd")
        set route_source offline
    else if _agent_is_repo_health_request "$cmd"
        set interpreted (_agent_route_repo_health "$cmd")
        set route_source offline
    else if _agent_is_data_ask_request "$cmd"
        set interpreted (_agent_route_data_ask "$cmd")
        set route_source offline
    else if _agent_is_generate_data_request "$cmd"
        set interpreted (_agent_route_generate_data "$cmd")
        set route_source offline
    else if _agent_is_docker_status_request "$cmd"
        set interpreted (_agent_route_docker_status "$cmd")
        set route_source offline
    else if _agent_is_clipboard_history_request "$cmd"
        set interpreted (_agent_route_clipboard_history "$cmd")
        set route_source offline
    else if _agent_is_route_learn_request "$cmd"
        set interpreted (_agent_route_learn_management "$cmd")
        set route_source offline
    else if set -l learned_match (_arka_match_learned_route "$cmd")
        if test -n "$learned_match"
            set interpreted $learned_match
            set route_source learned
        end
    else if _agent_is_survival_lang_request "$cmd"
        set interpreted (_agent_build_survival_lang_cmd "$cmd")
        set route_source offline
    else if _agent_is_currency_request "$cmd"
        set interpreted (_agent_build_currency_cmd "$cmd")
        set route_source offline
    else if _agent_is_price_check_request "$cmd"
        set -l pq (string replace -r -i '^price_check\s+' '' "$cmd" | string trim)
        test -z "$pq"; and set pq $cmd
        set interpreted "price_check $pq"
        set route_source offline
    else if _agent_is_platform_howto_question "$cmd"
        set interpreted "platform_howto $cmd"
        set route_source offline
    else if _agent_is_knowledge_question "$cmd"
        set -l kq (_agent_normalize_knowledge_q "$cmd")
        if test -z "$kq"
            set kq $cmd
        end
        set interpreted "web_answer $kq"
        set route_source offline
    else if _agent_is_storage_breakdown_question "$cmd"
        set interpreted "disk_breakdown"
        set route_source offline
    else if _agent_is_places_question "$cmd"
        set interpreted "web_answer $cmd"
        set route_source offline
    else if _agent_is_pdf_ingest_request "$cmd"
        set -l pdf (_agent_parse_pdf_path "$cmd")
        if test -n "$pdf"
            set interpreted "pdf_ingest $pdf"
        else
            set interpreted "pdf_ingest"
        end
        set route_source offline
    else if _agent_is_pdf_question "$cmd"
        set -l pq (_agent_pdf_ask_cmd "$cmd")
        set interpreted $pq
        set route_source offline
    else if string match -qr '(?i)^(reset|clear)\s+(chat|session|memory)\b' "$clean_cmd"
        set interpreted "chat_reset"
        set route_source offline
    else if string match -qr '(?i)^deep\s+queue\s+(add|list|run|results)\b' "$clean_cmd"
        set -l qparts (string split " " "$cmd")
        set interpreted "deep_queue $qparts[3..-1]"
        set route_source offline
    else if set -l g_route (_agent_route_google "$cmd")
        set interpreted $g_route
        set route_source offline
    else if set -l chat_route (_agent_chat_intent_route "$cmd")
        set interpreted $chat_route
        set route_source offline
    else if set -l aie_route (_agent_route_aie "$cmd")
        set interpreted $aie_route
    else if set -l wa_route (_agent_route_whatsapp_inbox "$cmd")
        set interpreted $wa_route
        set route_source offline
    else if set -l ytb_route (_agent_route_youtube_bulk "$cmd")
        set interpreted $ytb_route
        set route_source offline
    else if set -l ytd_route (_agent_route_youtube_download "$cmd")
        set interpreted $ytd_route
        set route_source offline
    else if _agent_is_system_info_question "$cmd"
        set interpreted (_agent_route_system_info "$cmd")
        set route_source offline
    else if _agent_is_knowledge_question "$cmd"
        set -l kq (_agent_normalize_knowledge_q "$cmd")
        test -z "$kq"; and set kq $cmd
        set interpreted "web_answer $kq"
        set route_source offline
    else if _agent_is_files_preference_question "$cmd"
        set interpreted "files_preference_help $cmd"
        set route_source offline
    else if _agent_is_desktop_organize_request "$cmd"
        set interpreted "classify_files"
        set route_source offline
    else if _agent_is_general_chat "$cmd"
        set interpreted (_agent_route_general_chat "$cmd")
        set route_source offline
    else if _agent_is_advisory_question "$cmd"
        set interpreted "agent_ask $cmd"
        set route_source offline
    else if string match -qr '(?i)(?:take\s+(?:a\s+)?screenshot|save\s+(?:a\s+)?screenshot)' "$clean_cmd"
        set interpreted "screenshot"
    else if string match -qr '(?i)(system\s*monitor|system\s*status|show\s+(me\s+)?(system\s+)?(monitor|resources)|check\s+(cpu|ram|memory|disk|battery)|\b(cpu|ram|memory)\s+(usage|load|percent)|how\s+much\s+(cpu|ram|memory)\s+(left|free|used)|\buptime\b|\bbattery\b)' "$clean_cmd"
        set interpreted "system_monitor"
    else if string match -qr '(excuse|blame)' "$clean_cmd"
        set interpreted "excuse"
    else if string match -qr '(bored|break|suggest)' "$clean_cmd"
        set interpreted "bored"
    else if string match -qr '(shorten.*url|short.*link)' "$clean_cmd"
        set interpreted "shorten_url $args"
    else if string match -qr '(qr.*code|qr)' "$clean_cmd"
        set interpreted "qr_code $args"
    else if string match -qr '(crypto|bitcoin|ethereum|solana|btc)' "$clean_cmd"
        set interpreted "crypto_price $args"
    else if _agent_is_currency_request "$cmd"
        set interpreted (_agent_build_currency_cmd "$cmd")
        set route_source offline
    else if string match -qr '(pomodoro|tomato)' "$clean_cmd"
        set interpreted "pomodoro $args"
    else if _agent_is_pr_check_request "$cmd"
        set interpreted (_agent_route_pr_check "$cmd")
        set route_source offline
    else if string match -qr '(git|branch|commit)' "$clean_cmd"
        set interpreted "git_summary"
    else if set -l prof_route (_agent_route_profession "$cmd")
        if test -n "$prof_route"
            set interpreted $prof_route
            set route_source offline
        end
    else if string match -qr '(project|open.*project)' "$clean_cmd"
        set interpreted "open_project $args"
    else if string match -qr '(finance|stocks)' "$clean_cmd"
        set interpreted "open_finance"
    else if string match -qr '(news)' "$clean_cmd"
        set interpreted "open_news"
    else if string match -qr '(speedtest|internet.*speed)' "$clean_cmd"
        set interpreted "speedtest"
    else if string match -qr '(port|open.*port)' "$clean_cmd"
        set interpreted "port_scan"
    else if string match -qr '(disk|space)' "$clean_cmd"
        if _agent_is_storage_breakdown_question "$cmd"
            set interpreted "disk_breakdown"
        else
            set interpreted "disk_usage $args"
        end
    else if string match -qr '(todo)' "$clean_cmd"
        set interpreted "todo $args"
    else if string match -qr '(?i)(save|store|remember)\s+(?:password|pass)\s+\S+\s+(?:for|as|named)\s+[a-zA-Z0-9._-]+' "$clean_cmd"
        set -l m (string match -r '(?i)(?:save|store|remember)\s+(?:password|pass)\s+(\S+)\s+(?:for|as|named)\s+([a-zA-Z0-9._-]+)' "$cmd")
        if test (count $m) -ge 3
            set interpreted "generate_password set $m[3] "(string escape --style=script -- $m[2])
        end
    else if string match -qr '(?i)(save|store|remember).*(password|pass).*(for|as|named)|generate.*password.*(for|named)\s+\S' "$clean_cmd"
        set -l pname (_agent_parse_password_name "$cmd")
        if test -n "$pname"
            set interpreted "generate_password save "(string escape --style=script -- $pname)
        else
            set interpreted "generate_password save"
        end
    else if string match -qr '(?i)(get|show|retrieve).*(password|pass).*(for|named)|what.*password.*(for|to)\s+\S' "$clean_cmd"
        set -l pname (_agent_parse_password_name "$cmd")
        if test -n "$pname"
            set interpreted "generate_password get "(string escape --style=script -- $pname)
        end
    else if string match -qr '(password)' "$clean_cmd"
        set interpreted "generate_password $args"
    else if string match -qr '(ip.*address|ip.*info|my.*ip)' "$clean_cmd"
        set interpreted "ip_info"
    else if string match -qr '(fix.*venv|recreate.*venv|reset.*venv)' "$clean_cmd"
        set interpreted "fix_venv $args"
    else if string match -qr '(bmi|body.*mass|calculate.*bmi)' "$clean_cmd"
        set -l numbers (string match -all -r '\b\d+\b' "$cmd")
        if test (count $numbers) -ge 2
            set interpreted "calculate_bmi $numbers[1] $numbers[2]"
        else
            set interpreted "calculate_bmi $args"
        end
    else if string match -qr '(cheat|cheat.*sheet)' "$clean_cmd"
        set interpreted "cheat $args"
    else if string match -qr '(?i)(install|get|setup).*(with|via|using)\s+brew|\bhomebrew\s+install|\bbrew\s+install' "$clean_cmd"
        and not string match -qr 'download\s+and\s+install' "$clean_cmd"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            set interpreted "install_brew $app"
        else
            set interpreted "install_brew"
        end
    else if string match -qr '(?i)(install|get|setup).*(flatpak|flathub)' "$clean_cmd"
        and not string match -qr 'download\s+and\s+install' "$clean_cmd"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            set interpreted "install_flatpak $app"
        else
            set interpreted "install_flatpak"
        end
    else if string match -qr '(?i)(install|get|setup).*(with|via|using)\s+apt|\bapt\s+install' "$clean_cmd"
        and not string match -qr 'download\s+and\s+install' "$clean_cmd"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            set interpreted "install_apt $app"
        else
            set interpreted "install_apt"
        end
    else if string match -qr '(?i)(install|get|setup).*snap' "$clean_cmd"
        and not string match -qr 'download\s+and\s+install' "$clean_cmd"
        set -l app (_agent_parse_install_app_name "$cmd")
        if test -n "$app"
            set interpreted "install_snap $app"
        else
            set interpreted "install_snap"
        end
    else if string match -qr '(flatpak.*snap|snap.*flatpak|search.*flatpak|search.*snap|query.*flatpak|query.*snap|find.*(?:flatpak|snap)|look.*(?:flatpak|snap))' "$clean_cmd"
        set -l store_query $cmd
        set store_query (string replace -r -i '^(?:query|search|find|look for)\s+' '' "$store_query")
        set store_query (string replace -r -i '^.*\bfor\s+' '' "$store_query")
        set store_query (string replace -r -i '\b(?:flatpak|snap|flathub|and|or)\b' ' ' "$store_query")
        set store_query (string replace -r '\s+' ' ' -- "$store_query" | string trim)
        if test -n "$store_query"
            set interpreted "search_stores $store_query"
        else
            set interpreted "search_stores"
        end
    else if string match -qr '(?i)(create|add|make).*(desktop|launcher|shortcut|menu|entry).*(unreal|unreal\s*engine)' "$clean_cmd"
        set interpreted "create_desktop_app unreal"
    else if string match -qr '(?i)(desktop|launcher|shortcut|menu\s*entry).*(for|of)\s+(?:the\s+)?(?:unreal|unreal\s*engine)' "$clean_cmd"
        set interpreted "create_desktop_app unreal"
    else if string match -qr '(?i)unreal.*(desktop|launcher|shortcut|app\s*menu)' "$clean_cmd"
        set interpreted "create_desktop_app unreal"
    else if string match -qr '(?i)^(remember|memorize|store|don\'t forget|dont forget|keep in mind)\s+(that\s+)?' "$clean_cmd"
        set -l mem (_arka_memory_detect_fact "$cmd")
        test -z "$mem"; and set mem (string replace -r -i '^(?:remember|memorize|store|don\'t forget|dont forget|keep in mind)\s+(?:that\s+)?' '' "$cmd")
        set interpreted "agent_remember $mem"
    else if string match -qr '(?i)^(recall|what do you remember)' "$clean_cmd"
        set -l rq (string replace -r -i '^(?:recall|what do you remember about)\s*' '' "$cmd")
        set interpreted "agent_recall $rq"
    else if _arka_memory_probe "$cmd"
        set interpreted "agent_remember $_arka_last_mem_fact"
    else if _agent_is_youtube_research_request "$clean_cmd"
        if string match -qr '(?i)\b(speak|tell me|read aloud|say)\b' "$clean_cmd"
            set -l yq (_agent_parse_youtube_research_query "$cmd")
            if test -n "$yq"
                set interpreted "speak_research $yq"
            else
                set interpreted "speak_research"
            end
        else
            set interpreted (_agent_build_youtube_research_cmd "$cmd")
        end
    else if string match -qr '(?i)^(arka ask|unified ask|ask arka)\s+' "$clean_cmd"
        set -l aq (string replace -r -i '^(?:arka ask|unified ask|ask arka)\s+' '' "$cmd")
        set interpreted "arka_ask $aq"
    else if string match -qr '(?i)(speak|tell me).*youtube.*(research|summary|summarize)' "$clean_cmd"
        set -l sq (_agent_parse_youtube_research_query "$cmd")
        test -z "$sq"; and set sq $cmd
        set interpreted "speak_research $sq"
    else if string match -qr '(?i)(research|investigate|deep dive)\s+' "$clean_cmd"
        set -l rq (string replace -r -i '^.*?(?:research|investigate|deep dive)\s+(?:on|about|into)?\s*' '' "$cmd")
        set interpreted "agent_research --deep $rq"
    else if string match -qr '(?i)(why did you route|why did you choose|agent why)' "$clean_cmd"
        set interpreted "agent_why"
    else if string match -qr '(?i)(resume (the )?loop|continue (the )?agent loop)' "$clean_cmd"
        set interpreted "agent_resume"
    else if string match -qr '(?i)(handoff|queue (this )?for later)' "$clean_cmd"
        set -l ht (string replace -r -i '^.*?(?:handoff|queue(?:\s+this)?(?:\s+for later)?)\s*' '' "$cmd")
        set interpreted "agent_handoff add $ht"
    else if string match -qr '(?i)compare\s+.+\s+(vs|versus|and)\s+' "$clean_cmd"
        set -l cm (string match -r '(?i)compare\s+(.+?)\s+(?:vs|versus|and)\s+(.+)$' -- "$cmd")
        if test (count $cm) -ge 3
            set interpreted "compare_agent $cm[2] $cm[3]"
        end
    else if _agent_is_price_check_request "$cmd"
        set -l pq (string replace -r -i '^price_check\s+' '' "$cmd" | string trim)
        test -z "$pq"; and set pq $cmd
        set interpreted "price_check $pq"
    else if string match -qr '(?i)\b(?:product\s+reviewer|review\s+this\s+product|check\s+(?:the\s+)?ingredients|ingredient\s+check|analyze\s+ingredients|ingredients?\s+review)\b' "$clean_cmd"
        set -l pq (string replace -r -i '^(?:product\s+reviewer|review\s+this\s+product|check\s+(?:the\s+)?ingredients|ingredient\s+check|analyze\s+ingredients|ingredients?\s+review)\s*' '' "$cmd" | string trim)
        if test -n "$pq"
            set interpreted "product_reviewer $pq"
        else
            set interpreted "product_reviewer"
        end
    else if string match -qr '(?i)\b(?:is\s+this|are\s+these)\s+.+\s+good\s+for\s+' "$clean_cmd"
        set interpreted "product_reviewer $cmd"
    else if string match -qr '(?i)\bis\s+.+\s+(?:vegan|cruelty[- ]free|safe\s+for\s+sensitive\s+skin)\b' "$clean_cmd"
        set interpreted "product_reviewer $cmd"
    else if _agent_matches_graphics_driver "$clean_cmd"
        set interpreted (_agent_route_graphics_driver "$cmd")
    else if string match -qr '(extract\s+this\s+and\s+run|extract\s+and\s+run|extract.*\brun\b|unzip.*\brun\b)' "$clean_cmd"
        set -l ex_m (string match -r '(?i)extract\s+(?:this\s+)?(?:and\s+)?run\s+(.+)$' -- "$cmd")
        if test (count $ex_m) -lt 2
            set ex_m (string match -r '(?i)unzip\s+(.+?)\s+and\s+run' -- "$cmd")
        end
        if test (count $ex_m) -ge 2
            set interpreted "extract_and_run "(string trim -- $ex_m[2])
        else
            set interpreted "extract_and_run"
        end
    else if string match -qr '(?i)^(?:download\s+|wget\s+|curl\s+-o\s+|download\s+(?:this|the)\s+)' "$clean_cmd"
        and not string match -qr 'download\s+and\s+install' "$clean_cmd"
        set -l dl_cmd (_agent_build_download_cmd "$cmd")
        if test -n "$dl_cmd"
            set interpreted $dl_cmd
            set route_source offline
        end
    else if string match -qr '(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)\b' "$clean_cmd"
        set -l ls_m (string match -r '(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)(?:\s+(\S+))?' -- "$cmd")
        if test (count $ls_m) -ge 3
            set -l ls_extra ""
            if test (count $ls_m) -ge 4
                set ls_extra $ls_m[4]
            end
            set interpreted "life_sciences $ls_m[3] $ls_extra"
            set route_source offline
        else
            set interpreted "life_sciences list"
            set route_source offline
        end
    else if string match -qr '(?i)\b(install|setup)\s+(pubmed|single[- ]cell(?:[- ]rna[- ]qc)?|nextflow(?:[- ]development)?|scvi(?:[- ]tools)?)\b' "$clean_cmd"
        set -l plug_m (string match -r '(?i)\b(?:install|setup)\s+(pubmed|single[- ]cell(?:[- ]rna[- ]qc)?|nextflow(?:[- ]development)?|scvi(?:[- ]tools)?)\b' -- "$cmd")
        if test (count $plug_m) -ge 2
            set -l plug (string lower -- $plug_m[2])
            switch $plug
                case "single-cell" "single cell" "single-cell-rna-qc" "single cell rna qc"
                    set plug "single-cell-rna-qc"
                case "nextflow" "nextflow-development"
                    set plug "nextflow-development"
                case "scvi" "scvi-tools"
                    set plug "scvi-tools"
            end
            set interpreted "life_sciences install $plug"
            set route_source offline
        end
    else if string match -qr '(install|setup|download\s+and\s+install)' "$clean_cmd"
        and not string match -qr '(?i)(flatpak|flathub|snap|with\s+apt|via\s+apt|brew|homebrew)' "$clean_cmd"
        if _agent_is_python_pip_install "$cmd"
            set interpreted (string trim -- (_agent_parse_install_uv "$cmd"))
        else
            set -l pkg_target (_agent_parse_install_app_name "$cmd")
            if test -z "$pkg_target"
                set pkg_target (string replace -r -i '^(?:download\s+and\s+)?(?:install|setup)\s+' '' "$cmd")
                set pkg_target (string trim -c "'\"" -- "$pkg_target")
            end
            if _install_target_is_package_file "$pkg_target"
                set interpreted "install_package $pkg_target"
            else if test -n "$pkg_target"
                set interpreted "install_app $pkg_target"
            else
                set interpreted "install_app"
            end
        end
    else if string match -qr '(auto.*click|click.*auto|cursor.*click)' "$clean_cmd"
        set interpreted "auto_click"
    else if string match -qr '(auto.*copy|copy.*selection|auto.*clipboard)' "$clean_cmd"
        set interpreted "auto_copy"
    else if string match -qr '(decrypt.*pdf|pdf.*decrypt|unlock.*pdf)' "$clean_cmd"
        set interpreted "decrypt_pdf $args"
    else if string match -qr '(classify.*file|sort.*file|organize.*file|auto.*sort)' "$clean_cmd"
        set interpreted "classify_files"
    else if string match -qr '(cleanup.*download|clean.*download|delete.*junk|remove.*clutter)' "$clean_cmd"
        set interpreted "cleanup_downloads"
    else if string match -qr '(watch.*zip|auto.*extract|zip.*watch)' "$clean_cmd"
        set interpreted "watch_zip"
    else if string match -qr '(monitor.*twitter|monitor.*x\b|watch.*tweet|track.*tweet|notify.*tweet)' "$clean_cmd"
        set -l handle (string replace -r -i '^.*(?:monitor|watch|track|notify).*(?:twitter|x|tweet)\s*@?\s*' '' "$cmd" | string trim)
        if test -n "$handle"
            set interpreted "monitor_x $handle"
        else
            set interpreted "monitor_x"
        end
    else if string match -qr '(open|launch|start)\s+(.+)' "$clean_cmd"
        set -l match_groups (string match -r '(?:open|launch|start)\s+(.+)' "$clean_cmd")
        set -l target_app $match_groups[2]
        if not string match -qr '(project|news|finance|url)' "$target_app"
            set interpreted "open_app $target_app"
        end
    end
    end

    if test -n "$interpreted"; and test "$route_source" = none
        set route_source offline
        echo (set_color yellow)"💡 [Offline routing]"(set_color normal)
    end

    if test -z "$interpreted"; and test "$route_mode" = symbolic
        set interpreted (_agent_llm_route "$cmd" "$available_skills")
        if test -n "$interpreted"
            set route_source llm
            echo (set_color yellow)"💡 [AI routing]"(set_color normal)
        end
    end

    # If LLM just echoed the original input, treat as no interpretation
    if test "$interpreted" = "$cmd"
        set interpreted ""
    else if test -n "$interpreted"
        set -l interp_first (string split -f 1 " " -- "$interpreted")
        if _agent_is_skill "$interp_first"
            # Already routed to a skill — do not wrap again in web_answer
        else if _agent_is_general_chat "$interpreted"
            set interpreted (_agent_route_general_chat "$interpreted")
            if test "$route_source" = none
                set route_source corrected
            end
        else if not _agent_is_skill "$interp_first"; and _agent_is_general_chat "$cmd"
            echo (set_color yellow)"💡 [Chat routing — not shell]"(set_color normal)
            set interpreted (_agent_route_general_chat "$cmd")
            set route_source corrected
        end
    end

    # Reject weak LLM skill matches (e.g. system_monitor for "install telegram")
    if test "$route_source" != offline; and test -n "$interpreted"
        set -l fixed (_agent_correct_interpretation "$cmd" "$interpreted")
        if test -n "$fixed"
            if test "$fixed" != "$interpreted"
                echo (set_color yellow)"💡 [Rule-corrected routing]"(set_color normal)
                set route_source corrected
            end
            set interpreted $fixed
        else if not _agent_skill_matches_request "$cmd" "$interpreted"
            echo (set_color yellow)"⚠ LLM skill '$interpreted' does not match request; use agent_route to preview routing"(set_color normal)
            set interpreted ""
        end
    end

    # 5. Handle Interpreted Result
    if test -n "$interpreted"; and test "$interpreted" != "impossible"
        echo (set_color blue)"→ Interpreted: $interpreted"(set_color normal)
        _agent_trace_log "$cmd" "$interpreted" "$route_source"
        _agent_dispatch "$interpreted"
    else if _agent_is_usage_question "$cmd"
        set -l period (_agent_parse_usage_period "$cmd")
        echo (set_color yellow)"💡 [App usage → local tracker]"(set_color normal)
        app_usage $period
    else if _agent_is_essay_request "$cmd"
        echo (set_color yellow)"💡 [Essay request → web_essay]"(set_color normal)
        set -l topic (_agent_normalize_essay_topic "$cmd")
        if test -z "$topic"
            web_essay $argv
        else
            web_essay $topic
        end
    else if _agent_is_storage_breakdown_question "$cmd"
        echo (set_color yellow)"💡 [Storage breakdown → disk_breakdown]"(set_color normal)
        disk_breakdown
    else if _agent_is_pdf_ingest_request "$cmd"
        echo (set_color yellow)"💡 [PDF ingest → PrivateGPT]"(set_color normal)
        set -l pdf (_agent_parse_pdf_path "$cmd")
        if test -n "$pdf"
            pdf_ingest $pdf
        else
            pdf_ingest $argv
        end
    else if _agent_is_pdf_question "$cmd"
        echo (set_color yellow)"💡 [PDF question → pdf_ask]"(set_color normal)
        set -l doc (_agent_parse_pdf_doc "$cmd")
        set -l q (_agent_normalize_pdf_question "$cmd")
        test -z "$q"; and set q $cmd
        if test -n "$doc"
            pdf_ask --doc "$doc" $q
        else
            pdf_ask $q
        end
    else if _agent_is_knowledge_question "$cmd"
        echo (set_color yellow)"💡 [Factual question → web_answer]"(set_color normal)
        set -l kq (_agent_normalize_knowledge_q "$cmd")
        if test -z "$kq"
            web_answer $argv
        else
            web_answer $kq
        end
    else if set -l g_route (_agent_route_google "$cmd")
        echo (set_color yellow)"💡 [Google → $g_route]"(set_color normal)
        _agent_dispatch_one "$g_route"
    else if _agent_is_remind_request "$cmd"
        set -l rem_cmd (_agent_build_remind_cmd "$cmd")
        echo (set_color yellow)"💡 [Remind → $rem_cmd]"(set_color normal)
        _agent_dispatch_one "$rem_cmd"
    else if _agent_is_routines_request "$cmd"
        set -l routine_cmd (_agent_build_routines_cmd "$cmd")
        echo (set_color yellow)"💡 [Routine → $routine_cmd]"(set_color normal)
        _agent_dispatch_one "$routine_cmd"
    else if _agent_is_file_size_find "$cmd"
        set -l size_cmd (_agent_route_file_size_find "$cmd")
        echo (set_color yellow)"💡 [File size → $size_cmd]"(set_color normal)
        _agent_dispatch_one "$size_cmd"
    else if _agent_is_chart_request "$cmd"
        set -l chart_cmd (_agent_build_chart_cmd "$cmd")
        echo (set_color yellow)"💡 [Chart → $chart_cmd]"(set_color normal)
        _agent_dispatch_one "$chart_cmd"
    else if _agent_is_model_select_request "$cmd"
        set -l model_cmd (_agent_build_model_select_cmd "$cmd")
        echo (set_color yellow)"💡 [Model advisor → $model_cmd]"(set_color normal)
        _agent_dispatch_one "$model_cmd"
    else if _agent_is_personalize_request "$cmd"
        set -l personalize_cmd (_agent_build_personalize_cmd "$cmd")
        echo (set_color yellow)"💡 [Personalize → $personalize_cmd]"(set_color normal)
        _agent_dispatch_one "$personalize_cmd"
    else if _agent_is_ascii_art_request "$cmd"
        set -l ascii_cmd (_agent_build_ascii_art_cmd "$cmd")
        echo (set_color yellow)"💡 [ASCII → $ascii_cmd]"(set_color normal)
        _agent_dispatch_one "$ascii_cmd"
    else if _agent_is_drawing_ask_request "$cmd"
        set -l drawing_cmd (_agent_build_drawing_ask_cmd "$cmd")
        echo (set_color yellow)"💡 [Drawing → $drawing_cmd]"(set_color normal)
        _agent_dispatch_one "$drawing_cmd"
    else if _agent_is_describe_screen_request "$cmd"
        set -l screen_cmd (_agent_build_describe_screen_cmd "$cmd")
        echo (set_color yellow)"💡 [Screen → $screen_cmd]"(set_color normal)
        _agent_dispatch_one "$screen_cmd"
    else if _agent_is_describe_image_request "$cmd"
        set -l image_cmd (_agent_build_describe_image_cmd "$cmd")
        echo (set_color yellow)"💡 [Image → $image_cmd]"(set_color normal)
        _agent_dispatch_one "$image_cmd"
    else if _agent_is_files_preference_question "$cmd"
        echo (set_color yellow)"💡 [Image save locations]"(set_color normal)
        files_preference_help $argv
    else if _agent_is_desktop_organize_request "$cmd"
        echo (set_color yellow)"💡 [Organize files → classify_files]"(set_color normal)
        classify_files
    else if _agent_is_advisory_question "$cmd"
        echo (set_color yellow)"💡 [Advisory question → AI]"(set_color normal)
        agent_ask $argv
    else if _agent_is_general_chat "$cmd"
        set -l route (_agent_route_general_chat "$cmd")
        set -l chat_skill (string split -f 1 " " -- "$route")
        echo (set_color yellow)"💡 [Chat → $chat_skill]"(set_color normal)
        _agent_dispatch_one "$route"
    else if _agent_looks_like_shell_cmd "$cmd"
        echo (set_color cyan)"▶ Running: $cmd"(set_color normal)
        _agent_exec_shell_cmd "$cmd"
        return $status
    else
        echo (set_color yellow)"💡 [Chat → web_answer]"(set_color normal)
        web_answer $argv
    end
end

function agent_run --description "Alias for agent"
    agent $argv
end

function calculate_bmi --description "Calculate and display the Body Mass Index (BMI) given weight in kg and height in cm"
    set -l weight $argv[1]
    set -l height $argv[2]
    if test (count $argv) -ne 2
        echo (set_color red)"Error: You must provide both weight and height"(set_color normal)
        return 1
    end
    set -l height_in_m (math "$height / 100")
    set -l bmi (math -s 2 "$weight / ($height_in_m * $height_in_m)")
    echo (set_color cyan) "-------------------------------"
    echo (set_color cyan) "|         BMI Calculator         |"
    echo (set_color cyan) "-------------------------------"
    echo (set_color yellow) "Your weight: $weight kg"
    echo (set_color yellow) "Your height: $height cm"
    echo (set_color magenta) "Your BMI: $bmi"
    if test (python3 -c "print(1 if $bmi < 18.5 else 0)") -eq 1
        echo (set_color blue) "You are underweight"
    else if test (python3 -c "print(1 if $bmi < 25 else 0)") -eq 1
        echo (set_color green) "You are normal weight"
    else if test (python3 -c "print(1 if $bmi < 30 else 0)") -eq 1
        echo (set_color yellow) "You are overweight"
    else
        echo (set_color red) "You are obese"
    end
    echo (set_color cyan) "-------------------------------"
end


function search_stores --description "Search Flatpak, Snap, and apt for apps (tries multiple query terms)"
    set -l raw (string join " " $argv | string trim)
    if test -z "$raw"
        echo "Usage: search_stores <query>"
        echo "Example: search_stores photo editor"
        echo "Example: agent \"query flatpak and snap for photo editor\""
        return 1
    end

    # Strip command noise from natural language
    set -l query $raw
    set query (string replace -r -i '^(?:query|search|find|look for)\s+' '' "$query")
    set query (string replace -r -i '\b(?:flatpak|snap|flathub|apt|app\s*store|stores?)\b' '' "$query")
    set query (string replace -r -i '\b(?:and|or|on|in|from|for)\b' ' ' "$query")
    set query (string replace -r '\s+' ' ' -- "$query" | string trim)

    if test -z "$query"
        echo (set_color red)"No search terms left after parsing."(set_color normal)
        return 1
    end

    set -l terms $query
    set -l words (string split " " -- $query)
    if test (count $words) -gt 1
        set -a terms $words[1]
    end

    printf "Store search: %s\n" "$query"

    set -l seen
    for term in $terms
        if contains -- "$term" $seen
            continue
        end
        set -a seen $term

        printf "\n━━━ Flatpak: %s ━━━\n" "$term"
        if command -v flatpak >/dev/null
            set -l fp (flatpak search "$term" 2>/dev/null | grep -v -i '^No matches')
            if test -n "$fp"
                printf '%s\n' $fp
            else
                echo (set_color yellow)"  No Flatpak matches for '$term'"(set_color normal)
            end
        else
            echo (set_color yellow)"  flatpak not installed"(set_color normal)
        end

        printf "\n━━━ Snap: %s ━━━\n" "$term"
        if command -v snap >/dev/null
            set -l sp (snap find "$term" 2>/dev/null)
            if test -n "$sp"
                printf '%s\n' $sp
            else
                echo (set_color yellow)"  No Snap matches for '$term'"(set_color normal)
            end
        else
            echo (set_color yellow)"  snap not installed"(set_color normal)
        end

        printf "\n━━━ apt: %s ━━━\n" "$term"
        if command -v apt-cache >/dev/null
            set -l ap (apt-cache search --names-only "$term" 2>/dev/null | head -12)
            if test -z "$ap"
                set ap (apt-cache search "$term" 2>/dev/null | head -12)
            end
            if test -n "$ap"
                printf '%s\n' $ap
            else
                echo (set_color yellow)"  No apt matches for '$term'"(set_color normal)
            end
        else
            echo (set_color yellow)"  apt-cache not available"(set_color normal)
        end
    end
end

function _resolve_archive_path --description "Find archive in cwd, Downloads, or absolute path (internal)"
    set -l name (basename "$argv[1]")
    if test -f "$argv[1]"
        realpath "$argv[1]" 2>/dev/null; or echo "$argv[1]"
        return 0
    end
    for dir in "$PWD" "$HOME/Downloads"
        if test -f "$dir/$name"
            realpath "$dir/$name" 2>/dev/null; or echo "$dir/$name"
            return 0
        end
    end
    return 1
end

function _find_unreal_icon --description "Best launcher icon path for a UE install (internal)"
    set -l root "$argv[1]"
    set -l candidates \
        "$root/Engine/Programs/SubmitTool/Build/Mac/Resources/Assets.xcassets/AppIcon.appiconset/icon_128x128.png" \
        "$root/Engine/Build/Android/Java/res/drawable-xhdpi/icon.png" \
        "$root/Engine/Build/Android/Java/res/drawable-hdpi/icon.png" \
        "$root/Engine/Content/Editor/Slate/Icons/EditorAppIcon.png" \
        "$root/Engine/Content/Editor/Slate/Icons/VREditor/VR_Editor_Toolbar_Icon.png" \
        "$root/Engine/Content/Editor/Slate/About/UnrealLogo.svg"
    for ic in $candidates
        if test -f "$ic"
            echo "$ic"
            return 0
        end
    end
    return 1
end

function _install_unreal_menu_icon --description "Copy UE icon into hicolor theme; prints icon name (internal)"
    set -l src "$argv[1]"
    if not test -f "$src"
        return 1
    end
    set -l icon_name unreal-engine
    set -l size 128
    if string match -qr '\.svg$' -- "$src"
        set -l dest "$HOME/.local/share/icons/hicolor/scalable/apps/$icon_name.svg"
        mkdir -p (dirname "$dest")
        cp -f "$src" "$dest"
    else
        set -l dim (identify -format '%w' "$src" 2>/dev/null)
        switch $dim
            case 256 512
                set size $dim
            case 96
                set size 96
            case 40 48 64
                set size 64
            case 24 32
                set size 48
        end
        set -l dest "$HOME/.local/share/icons/hicolor/"$size"x"$size"/apps/$icon_name.png"
        mkdir -p (dirname "$dest")
        if test "$size" != "$dim"; and command -v convert >/dev/null
            convert "$src" -resize "{$size}x{$size}" "$dest"
        else
            cp -f "$src" "$dest"
        end
        # Also install 128px copy for launchers when source is smaller
        if test "$size" -lt 128; and command -v convert >/dev/null
            set -l dest128 "$HOME/.local/share/icons/hicolor/128x128/apps/$icon_name.png"
            mkdir -p (dirname "$dest128")
            convert "$src" -resize 128x128 "$dest128"
        end
    end
    if command -v gtk-update-icon-cache >/dev/null
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null
    end
    echo $icon_name
end

function _find_unreal_editor_paths --description "Print install_root<TAB>UnrealEditor path if found (internal)"
    for dir in $HOME/.local/share/Linux_Unreal* $HOME/.local/share/*[Uu]nreal*
        if test -d "$dir/Engine"
            set -l ed "$dir/Engine/Binaries/Linux/UnrealEditor"
            if test -x "$ed"
                printf '%s\t%s\n' "$dir" "$ed"
                return 0
            end
        end
    end
    for ed in (find "$HOME/.local/share" -maxdepth 6 -type f -name UnrealEditor 2>/dev/null)
        if not test -x "$ed"
            continue
        end
        set -l root (dirname "$ed")
        while not test -d "$root/Engine"
            set -l parent (dirname "$root")
            if test "$parent" = "$root"
                break
            end
            set root $parent
        end
        if test -d "$root/Engine"; and test -x "$root/Engine/Binaries/Linux/UnrealEditor"
            printf '%s\t%s\n' "$root" "$root/Engine/Binaries/Linux/UnrealEditor"
            return 0
        end
    end
    return 1
end

function create_desktop_app --description "Create a .desktop launcher in the app menu (Unreal Engine supported)"
    set -l query (string join " " $argv | string lower)
    set -l app_name ""
    set -l install_root ""
    set -l exec_bin ""

    if string match -qr 'unreal' "$query"; or test (count $argv) -eq 0
        set -l paths (_find_unreal_editor_paths)
        if test (count $paths) -eq 0
            printf '%s\n' (set_color red)"Unreal Editor not found under ~/.local/share/"(set_color normal)
            echo "  Extract it first: extract_and_run <Linux_Unreal_Engine_*.zip>"
            return 1
        end
        set install_root (echo $paths | awk -F'\t' '{print $1}')
        set exec_bin (echo $paths | awk -F'\t' '{print $2}')
        set app_name "Unreal Engine"
    else if test -x "$argv[1]"
        set exec_bin "$argv[1]"
        set install_root (dirname (dirname (dirname "$exec_bin")))
        if test -d "$install_root/Engine"
            set install_root "$install_root"
        else
            set install_root (dirname "$exec_bin")
        end
        set app_name (basename "$install_root")
    else
        echo "Usage: create_desktop_app [unreal]"
        echo "       create_desktop_app /path/to/binary"
        echo "Example: agent \"create a desktop app for unreal engine\""
        return 1
    end

    set -l desktop_dir "$HOME/.local/share/applications"
    mkdir -p "$desktop_dir"
    set -l desktop_id "unreal-engine.desktop"
    if not string match -qr 'unreal' "$query"
        set desktop_id (string replace -r '[^a-zA-Z0-9]+' '-' -- (string lower "$app_name"))".desktop"
    end
    set -l desktop_file "$desktop_dir/$desktop_id"

    set -l icon "unreal-engine"
    set -l ic (_find_unreal_icon "$install_root")
    if test -n "$ic"
        set -l installed (_install_unreal_menu_icon "$ic")
        if test -n "$installed"
            set icon "$installed"
        else
            set icon "$ic"
        end
    end

    printf '%s\n' \
        '[Desktop Entry]' \
        'Version=1.0' \
        'Type=Application' \
        "Name=$app_name" \
        'Comment=Unreal Editor' \
        "Exec=$exec_bin %f" \
        "Path=$install_root" \
        "Icon=$icon" \
        'Terminal=false' \
        'Categories=Development;IDE;' \
        'StartupWMClass=UnrealEditor' \
        > "$desktop_file"
    chmod +x "$desktop_file"

    if command -v update-desktop-database >/dev/null
        update-desktop-database "$desktop_dir" 2>/dev/null
    end

    printf '%s\n' (set_color green)"✓ Created launcher:"(set_color normal) " $desktop_file"
    echo "  Launch from your app menu as \"$app_name\", or: gtk-launch "(basename "$desktop_file" .desktop)
end

function extract_and_run --description "Extract an archive from Downloads/cwd and launch its main binary (e.g. Unreal Editor)"
    set -l archive_query (string join " " $argv | string trim)
    if test -z "$archive_query"
        echo "Usage: extract_and_run <archive.zip|.tar.gz|...>"
        echo "Example: extract_and_run Linux_Unreal_Engine_5.8.0_preview-1.zip"
        echo "Example: agent \"extract this and run Linux_Unreal_Engine_5.8.0_preview-1.zip\""
        return 1
    end

    set archive_query (string replace -r -i '^(?:extract\s+)?(?:this\s+)?(?:and\s+)?run\s+' '' "$archive_query")
    set -l archive (_resolve_archive_path "$archive_query")
    if test -z "$archive"
        printf '%s\n' (set_color red)"Archive not found: $archive_query"(set_color normal)
        echo "  Looked in: $PWD, $HOME/Downloads"
        return 1
    end

    set -l stem (basename "$archive")
    if string match -q '*.zip' -- "$archive"
        set stem (basename "$archive" .zip)
    else if string match -q '*.tar.gz' -- "$archive"
        set stem (basename "$archive" .tar.gz)
    else if string match -q '*.tgz' -- "$archive"
        set stem (basename "$archive" .tgz)
    else if string match -q '*.tar.xz' -- "$archive"
        set stem (basename "$archive" .tar.xz)
    end
    set -l extract_dir "$HOME/.local/share/$stem"
    set -l run_bin ""
    if test (count $argv) -ge 2
        set run_bin $argv[2]
    end

    set -l editor "$extract_dir/Engine/Binaries/Linux/UnrealEditor"
    if test -z "$run_bin"
        if test -x "$editor"
            set run_bin "$editor"
        else if test -d "$extract_dir"
            set run_bin (find "$extract_dir" -type f -name UnrealEditor 2>/dev/null | head -1)
        end
    end

    if test -n "$run_bin"; and test -x "$run_bin"
        printf '%s\n' (set_color green)"Already extracted at:"(set_color normal) " $extract_dir"
    else
        printf '%s\n' (set_color cyan)"Extracting (large archives take time):"(set_color normal)
        echo "  From: $archive"
        echo "  To:   $extract_dir"
        mkdir -p "$extract_dir"
        set -l ext (string lower "$archive")
        if string match -q '*.zip' -- "$ext"
            if command -v unzip >/dev/null
                unzip -o "$archive" -d "$extract_dir"
            else
                echo (set_color red)"Install unzip: sudo apt install unzip"(set_color normal)
                return 1
            end
        else if string match -q '*.tar.gz' -- "$ext"; or string match -q '*.tgz' -- "$ext"
            tar -xzf "$archive" -C "$extract_dir"
        else if string match -q '*.tar.xz' -- "$ext"
            tar -xJf "$archive" -C "$extract_dir"
        else
            echo (set_color red)"Unsupported archive type."(set_color normal)
            return 1
        end
        set run_bin "$extract_dir/Engine/Binaries/Linux/UnrealEditor"
        if not test -x "$run_bin"
            set run_bin (find "$extract_dir" -type f -name UnrealEditor 2>/dev/null | head -1)
        end
    end

    if test -z "$run_bin"; or not test -x "$run_bin"
        printf '%s\n' (set_color red)"No runnable binary found under $extract_dir"(set_color normal)
        echo "  Expected: Engine/Binaries/Linux/UnrealEditor"
        return 1
    end

    printf '%s\n' (set_color --bold green)"Launching:"(set_color normal) " $run_bin"
    set -l app_root (dirname (dirname (dirname "$run_bin")))
    if test -d "$extract_dir/Engine"
        set app_root "$extract_dir"
    end
    cd "$app_root"
    "$run_bin" &
    disown 2>/dev/null
end

function _graphics_driver_va_package --description "Intel VA driver package name without conflicts (internal)"
    if dpkg -l intel-media-va-driver-non-free 2>/dev/null | grep -q '^ii'
        echo intel-media-va-driver-non-free
        return
    end
    if dpkg -l intel-media-va-driver 2>/dev/null | grep -q '^ii'
        echo intel-media-va-driver
        return
    end
    if apt-cache show intel-media-va-driver-non-free &>/dev/null
        echo intel-media-va-driver-non-free
    else
        echo intel-media-va-driver
    end
end

function _graphics_driver_apt_install --description "Install Mesa/Intel packages one-by-one; return 0 if OK (internal)"
    set -l va_pkg (_graphics_driver_va_package)
    # One package per line so fish captures a proper list (not one long string).
    set -l pkgs mesa-vulkan-drivers mesa-utils vainfo $va_pkg

    if not command -v apt >/dev/null
        echo (set_color yellow)"apt not found."(set_color normal)
        return 1
    end

    sudo apt update

    set -l failed
    for pkg in $pkgs
        if dpkg -s "$pkg" &>/dev/null
            echo (set_color green)"  ✓ $pkg already installed"(set_color normal)
            continue
        end
        echo (set_color cyan)"  → sudo apt install -y $pkg"(set_color normal)
        set -l out (sudo apt install -y "$pkg" 2>&1)
        set -l st $status
        if test $st -eq 0
            echo (set_color green)"  ✓ $pkg"(set_color normal)
        else
            # Retry once (mirror/sync glitch)
            set out (sudo apt install -y "$pkg" 2>&1)
            set st $status
            if test $st -eq 0
                echo (set_color green)"  ✓ $pkg (retry ok)"(set_color normal)
            else
                echo (set_color yellow)"  ✗ $pkg"(set_color normal)
                printf '%s\n' $out | head -5 | sed 's/^/      /'
                set -a failed $pkg
            end
        end
    end

    if test (count $failed) -eq 0
        return 0
    end

    echo (set_color yellow)"  Some packages failed: $failed"(set_color normal)
    echo (set_color brblack)"  Trying combined install for remaining..."(set_color normal)
    if sudo apt install -y $failed
        return 0
    end
    return 1
end

function fix_graphics_driver --description "Handle Intel/GPU driver warnings: Linux Mesa fix + optional vendor URL"
    set -l cache "$HOME/.cache/fish-agent/last_nl.txt"
    set -l text ""
    if test -f "$cache"
        set text (cat "$cache")
    end
    if test (count $argv) -gt 0
        if string match -qr '^https?://' -- "$argv[1]"
            set -l url "$argv[1]"
            if test -z "$text"
                set text "Vendor URL: $url"
            end
        else
            set text (string join " " $argv)
        end
    end
    if test -z "$text"
        if type -q wl-paste
            set text (wl-paste 2>/dev/null)
        else if type -q xclip
            set text (xclip -selection clipboard -o 2>/dev/null)
        end
    end
    if test -z "$text"
        echo "Usage: fix_graphics_driver [vendor-url]"
        echo "       agent \"fix <paste Intel/GPU driver warning>\""
        echo "Paste the full error in agent, or copy it to clipboard and run: fix_graphics_driver"
        return 1
    end

    set -l url (_extract_first_url "$text")
    if test (count $argv) -gt 0; and string match -qr '^https?://' -- "$argv[1]"
        set url "$argv[1]"
    end

    set -l gpu_line ""
    set -l gpu_m (string match -r '(?i)Intel\(R\)[^\n\r]+|HD Graphics [0-9]+[^\n\r]*|UHD Graphics [0-9]+[^\n\r]*' "$text")
    if test (count $gpu_m) -ge 2
        set gpu_line (string trim -- $gpu_m[2])
    end

    echo (set_color --bold cyan)"━━━ Graphics driver assistant ━━━"(set_color normal)
    echo ""
    echo (set_color yellow)"Note:"(set_color normal) " Unreal and many Windows apps show Intel *Windows* driver versions."
    echo "  On Linux you use Mesa (i915/iris) — version numbers like 24.2.8 / 26.0.3 often do not apply."
    echo ""
    if test -n "$gpu_line"
        echo "  GPU: $gpu_line"
    end
    if string match -qr '(?i)installed:\s*([0-9.]+)' "$text"
        set -l inst_m (string match -r '(?i)installed:\s*([0-9.]+)' "$text")
        echo "  Reported (app): installed $inst_m[2]"
    end
    if string match -qr '(?i)recommended:\s*([0-9.]+|latest)' "$text"
        set -l rec_m (string match -r '(?i)recommended:\s*([^\n\r]+)' "$text")
        echo "  Reported (app): recommended "(string trim -- $rec_m[2])
    end
    echo ""

    echo (set_color --bold)"Linux GPU status:"(set_color normal)
    if command -v lspci >/dev/null
        lspci 2>/dev/null | grep -iE 'vga|3d|display'
    end
    if command -v glxinfo >/dev/null
        echo "  OpenGL: "(glxinfo 2>/dev/null | grep -m1 'OpenGL version' | string trim)
        echo "  Renderer: "(glxinfo 2>/dev/null | grep -m1 'OpenGL renderer' | string trim)
    else
        echo (set_color brblack)"  Install mesa-utils for glxinfo: sudo apt install mesa-utils"(set_color normal)
    end
    if test -r /sys/module/i915/version
        echo "  i915 module: "(cat /sys/module/i915/version)
    end
    echo ""

    set -l mesa_ok false
    if command -v glxinfo >/dev/null
        set -l renderer (glxinfo 2>/dev/null | grep -m1 'OpenGL renderer')
        if string match -qr 'Mesa.*Intel' "$renderer"
            set mesa_ok true
        end
    end
    if test "$mesa_ok" = true
        echo (set_color green)"  ✓ Mesa Intel driver is active — Linux graphics stack looks healthy."(set_color normal)
        echo (set_color brblack)"  Unreal’s Windows driver version check can usually be ignored."(set_color normal)
        echo ""
    end

    read -P (set_color --bold cyan)"Update Linux Mesa/Intel graphics packages? [Y/n]: "(set_color normal) -l apt_ok
    set -l apt_st 0
    if test -z "$apt_ok"; or string match -qi 'y*' "$apt_ok"
        echo (set_color brblack)"  VA driver: $(_graphics_driver_va_package) (never both -free and -non-free)"(set_color normal)
        _graphics_driver_apt_install
        set apt_st $status
        if test $apt_st -eq 0
            echo (set_color green)"  ✓ Graphics packages OK."(set_color normal)
        else if test "$mesa_ok" = true
            echo (set_color yellow)"  apt reported issues, but Mesa/OpenGL is already working — OK for Unreal."(set_color normal)
            set apt_st 0
        else
            echo (set_color yellow)"  apt install had issues — try: sudo apt install -y mesa-vulkan-drivers mesa-utils"(set_color normal)
        end
    end

    if test -n "$url"
        echo ""
        read -P (set_color --bold cyan)"Open vendor page in browser? [Y/n]: "(set_color normal) -l open_ok
        if test -z "$open_ok"; or string match -qi 'y*' "$open_ok"
            open_urls "$url"
            echo (set_color brblack)"  (Windows .exe drivers from Intel Download Center do not install on Linux.)"(set_color normal)
        end
    end

    echo ""
    if test "$mesa_ok" = true; and test $apt_st -eq 0
        echo (set_color green)"Done."(set_color normal) " Linux graphics are fine. Re-launch Unreal — dismiss the Windows driver warning if it still appears."
    else if test "$mesa_ok" = true
        echo (set_color green)"Done (with apt warnings)."(set_color normal) " Mesa works; re-launch Unreal and dismiss the driver dialog."
    else
        echo (set_color green)"Done."(set_color normal) " Re-launch Unreal/your app after any package updates."
    end
    return $apt_st
end

function download_file --description "Download a URL (resume) or check if a file is already in Downloads"
    set -l target (string join " " $argv | string trim)
    if test -z "$target"
        echo "Usage: download_file <url>"
        echo "       download_file <filename>   # checks ~/Downloads and cwd; uses clipboard URL if missing"
        echo "Example: download_file https://example.com/file.zip"
        echo "Example: agent \"download this Linux_Unreal_Engine_5.8.0_preview-1.zip\""
        return 1
    end

    set target (string replace -r -i '^(?:download\s+)?(?:this\s+)?(?:the\s+)?' '' "$target" | string trim)

    # Direct URL
    if string match -qr '^https?://' -- "$target"
        set -l out (basename (string split -m 1 '?' -- $target)[1])
        if test -z "$out" -o "$out" = /
            set out "download.bin"
        end
        if test -f "$out"
            echo (set_color yellow)"Resuming: $out"(set_color normal)
            curl -fL -C - --progress-bar -o "$out" "$target"
        else
            echo (set_color cyan)"Downloading → $out"(set_color normal)
            curl -fL --progress-bar -o "$out" "$target"
        end
        return $status
    end

    # Filename: already downloaded?
    set -l basename_target (basename "$target")
    set -l found ""
    for dir in "$PWD" "$HOME/Downloads"
        if test -f "$dir/$basename_target"
            set found "$dir/$basename_target"
            break
        end
    end

    if test -n "$found"
        set -l sz (du -h "$found" 2>/dev/null | cut -f1)
        printf '%s\n' (set_color --bold green)"Already downloaded:"(set_color normal) "$found ($sz)"
        echo (set_color brblack)"  Nothing to fetch. Use install_package to extract/install."(set_color normal)
        return 0
    end

    # Try clipboard for a download URL
    set -l clip ""
    if command -v xclip >/dev/null
        set clip (xclip -selection clipboard -o 2>/dev/null | string trim)
    else if command -v wl-paste >/dev/null
        set clip (wl-paste 2>/dev/null | string trim)
    end

    if string match -qr '^https?://' -- "$clip"
        echo (set_color cyan)"Using URL from clipboard..."(set_color normal)
        download_file "$clip"
        return $status
    end

    printf '%s\n' (set_color red)"Not found locally: $basename_target"(set_color normal)
    echo "  Copy the download link to your clipboard, then run again."
    echo "  Or: download_file 'https://...'"
    return 1
end

function install_package --description "Download, extract, and install Linux packages (.deb, .tar.gz, .appimage, .rpm) via automation project"
    python3 /home/s/Projects/python/products/automation/install_package.py $argv
end


# NemoClaw PATH setup
fish_add_path --path --append "/home/s/.local/bin"
fish_add_path --path --append "/home/s/.local/share/nvm/v22.22.2/bin"
# end NemoClaw PATH setup

# --- First Run Setup ---
set -g _ARKA_RELOAD_STAMP (_arka_reload_stamp)
_arka_load_third_party_skills 2>/dev/null
_agent_register_call_name
if status is-interactive
    if set -q USAGE_TRACK; and test "$USAGE_TRACK" = 1 -o "$USAGE_TRACK" = true
        _arka_usage_autostart_ensure 2>/dev/null
    end
    if set -q AGENT_NUDGE; and test "$AGENT_NUDGE" = 1 -o "$AGENT_NUDGE" = true
        agent_nudge --quiet 2>/dev/null
    end
    _arka_remind_autostart_ensure 2>/dev/null
    set -l _arka_remind_py (_arka_python)
    $_arka_remind_py (_arka_py_script arka_remind.py) check --quiet 2>/dev/null
    if set -q AUTO_START; and test "$AUTO_START" = 1 -o "$AUTO_START" = true
        _arka_start_all --quiet 2>/dev/null
    else if test "$AGENT_WAKE_AUTO" = 1 -o "$AGENT_WAKE_AUTO" = true
        _agent_listen_start 2>/dev/null
    else if set -q USAGE_TRACK; and test "$USAGE_TRACK" = 1 -o "$USAGE_TRACK" = true
        _agent_usage_start 2>/dev/null
    end
end
if not test -f $_ARKA_ROOT/.skills_setup_done
    if _arka_is_linux
        install_skill_deps
    else
        _arka_install_python_deps
    end
end


# Added by Antigravity CLI installer
set -gx PATH "/home/s/.local/bin" $PATH
