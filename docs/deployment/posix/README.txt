POSIX deployment assets
=======================

The POSIX directory hosts shared release notes for Linux and macOS builds. Use
``mdview-help.txt`` as the canonical ``--help`` output when generating man
pages or other terminal-facing references. Update this file by running the
mdview CLI in a virtual environment and capturing
``mdview.cli.format_help()``.

When releasing for Linux or macOS, copy the latest shared help text and ensure
the platform-specific man pages reflect the same options and defaults.
