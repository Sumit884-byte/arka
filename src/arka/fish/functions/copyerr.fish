function copyerr
    # This reads the piped input and sends it to the clipboard
    cat 2>&1 | xclip -selection clipboard
    echo "Error copied to clipboard!"
end
