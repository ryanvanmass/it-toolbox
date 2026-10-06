#!/bin/sh
# CFBundleExecutable of IT Toolbox.app (installed as Contents/MacOS/it-toolbox
# by packaging/macos/build.sh).
#
# An app launched from Finder/the Dock gets launchd's minimal PATH
# (/usr/bin:/bin:/usr/sbin:/sbin), not the user's shell PATH -- so gcloud,
# rclone, sdl-freerdp etc. from Homebrew or the Cloud SDK installer would be
# invisible to the app's shutil.which() lookups. Borrow the login shell's
# PATH (what a Terminal-launched copy would see), with Homebrew's bin dirs
# appended as a fallback in case the shell profile doesn't add them. The
# marker strips anything a chatty profile prints before it.
login_path=$("${SHELL:-/bin/zsh}" -l -c 'printf "__IT_TOOLBOX_PATH__%s" "$PATH"' 2>/dev/null </dev/null)
case "$login_path" in
    *__IT_TOOLBOX_PATH__*) login_path=${login_path##*__IT_TOOLBOX_PATH__} ;;
    *) login_path= ;;
esac
PATH="${login_path:-$PATH}:/opt/homebrew/bin:/usr/local/bin"
export PATH

# The bundle is code-signed with every .pyc already compiled (build.sh);
# writing new ones into it at runtime would change its sealed contents.
export PYTHONDONTWRITEBYTECODE=1

# Contents/MacOS/python is a symlink to the bundled interpreter, so the
# running process's executable path sits in Contents/MacOS/ -- what macOS
# uses to associate the process with this bundle (Dock name/icon, menu bar
# title) rather than treating it as a bare "python".
exec "$(dirname "$0")/python" -m it_toolbox "$@"
