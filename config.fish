# Arka Fish — sources canonical config from the package tree
set -l _arka_cfg (path dirname (status filename))/src/arka/fish/config.fish
if not test -f "$_arka_cfg"
    set _arka_cfg (path dirname (status filename))/src/arka/bundled/config.fish
end
if test -f "$_arka_cfg"
    source "$_arka_cfg"
else
    echo "Arka config missing — run: python scripts/sync_bundled.py" >&2
end
