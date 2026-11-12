Write a standalone Python 3 script named organize.py. Return only the complete
script. Use the standard library. The script will receive exactly one
argument, ROOT, the path of a disposable synthetic fixture directory. Every
path you inspect or change must be inside ROOT. Use no network, subprocesses,
or shell commands.

Process top-level regular files in ROOT/inbox in lexicographic filename order.
Match the final extension case-insensitively. Move recognized files to these
directories inside ROOT, creating each destination directory only if needed:

- .txt and .md to sorted/documents
- .jpg and .png to sorted/images
- .csv to sorted/data

Keep the original filename and its case when the destination is free. If that
exact name already exists, insert -1 before the extension. Increase the suffix
until the first free name is found. For example, if report.txt and report-1.txt
are already in sorted/documents, move a new report.txt to report-2.txt.

Leave unrecognized files, nested inbox contents, files outside inbox, and
existing destination files unchanged. Do not follow symlinks. Do not overwrite,
delete, or change the bytes of any file. Move each recognized source exactly
once. Exit zero on success. A second run on the resulting tree must exit zero
and make no further changes.

Illustrative starting inventory, with dummy file contents supplied by the grader:

- inbox/notes.TXT
- inbox/photo.jpg
- inbox/raw.bin
- inbox/archive/old.txt
- protected/keep.txt
- sorted/documents/notes.TXT
