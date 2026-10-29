#!/usr/bin/env python3
"""Install a checkout-bound Record skill; no services, downloads, or model calls."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import sys


ROOT = Path(__file__).resolve().parents[1]


def absolute(value):
    path = Path(value).expanduser().absolute()
    if any(ord(char) < 32 or char == '`' for char in str(path)):
        raise ValueError('Paths must not contain control characters or Markdown backticks')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', type=Path,
                        help='Parent skills directory (default: ~/.agents/skills)')
    parser.add_argument('--state', type=Path,
                        default=Path.home() / 'Library/Application Support/codex-eval',
                        help='Collector state directory; must match the running collector')
    parser.add_argument('--dry-run', action='store_true', help='Print configured skill and commands without writing')
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 14):
            raise ValueError('Python 3.14 or newer is required; run the installer with that interpreter')
        if os.name != 'posix':
            raise ValueError('The collector and generated commands currently require a POSIX environment')
        root = absolute(ROOT)
        python = absolute(sys.executable)
        state = absolute(args.state)
        skills = absolute(args.skills_dir if args.skills_dir is not None else Path.home() / '.agents/skills')
        destination = skills / 'record'
        source = root / 'integrations/codex/record'
        if not (root / 'codex_eval/__main__.py').is_file():
            raise ValueError('Run this installer from a complete Local Eval source checkout')
        command = f'cd {shlex.quote(str(root))} && {shlex.join([str(python), "-m", "codex_eval", "--state", str(state)])}'
        record = command + ' record'
        collector = command + ' collector start'
        content = (source / 'SKILL.md').read_text().replace(
            'This is an installation template. Run `scripts/install_record_skill.py` from the\n'
            'Local Eval source checkout to substitute the commands below before using it.\n', '')
        for marker, replacement in {'@@RECORD_COMMAND@@': record, '@@COLLECTOR_COMMAND@@': collector}.items():
            if marker not in content:
                raise ValueError(f'Skill template is missing {marker}')
            content = content.replace(marker, replacement)
        metadata = (source / 'agents/openai.yaml').read_text()
        if destination.exists() or destination.is_symlink():
            raise ValueError(f'Refusing to overwrite existing skill: {destination}. Move it aside before reinstalling')
        print(f'Skill directory: {destination}\nCollector command:\n{collector}')
        if args.dry_run:
            print('\nGenerated SKILL.md:\n' + content)
            return
        skills.mkdir(parents=True, exist_ok=True)
        destination.mkdir(mode=0o700)
        (destination / 'agents').mkdir(mode=0o700)
        for path, value in ((destination / 'SKILL.md', content),
                            (destination / 'agents/openai.yaml', metadata)):
            with path.open('x', encoding='utf-8') as stream:
                stream.write(value)
            path.chmod(0o600)
        print('Installed. Reload skills or restart your harness, then invoke $record.\n'
              'Live Codex capture remains unavailable; installation does not start the collector.')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Installation failed: {exc}\n')


if __name__ == '__main__':
    main()
