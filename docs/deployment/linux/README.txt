Linux deployment notes
======================

Use ``mdview.1`` when packaging mdview for Linux distributions. Regenerate the
man page whenever CLI options change, using the shared POSIX help text at
``../posix/mdview-help.txt`` as the source of truth. Keep internal viewer
behavior and version strings aligned with the current release.
