"""Reference submission for the synthetic filesystem benchmark."""
from pathlib import Path
import sys


CATEGORIES = {'.txt': 'documents', '.md': 'documents',
              '.jpg': 'images', '.png': 'images', '.csv': 'data'}


def main(root):
    for source in sorted((root / 'inbox').iterdir()):
        category = CATEGORIES.get(source.suffix.lower())
        if not category or source.is_symlink() or not source.is_file():
            continue
        directory = root / 'sorted' / category
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / source.name
        index = 1
        while target.exists() or target.is_symlink():
            target = directory / f'{source.stem}-{index}{source.suffix}'
            index += 1
        source.rename(target)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
