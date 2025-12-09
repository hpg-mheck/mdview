Windows deployment notes
=======================

Provide ``mdview --help`` output alongside packaging artifacts so cmd.exe and
PowerShell users see the same guidance as POSIX environments. Mirror the
shared help text in ``../posix/mdview-help.txt`` and note any pager
differences for Windows terminals. Include a brief example invocation using
``type`` or ``more`` when ``less`` is unavailable.
