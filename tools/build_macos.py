"""Build a self-contained arm64 .app with original WebM assets and Qt plugins."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def prepare_plugins() -> list[Path]:
    from PySide6.QtCore import QLibraryInfo
    source = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    files = []
    for group in ('platforms', 'imageformats'):
        for plugin in sorted((source / group).glob('*.dylib')):
            target = ROOT / 'qt-plugins' / group / plugin.name
            target.parent.mkdir(parents=True, exist_ok=True)
            # copyfile deliberately avoids inherited UF_HIDDEN: Qt skips hidden plugins.
            shutil.copyfile(plugin, target)
            target.chmod(0o755)
            if hasattr(os, 'chflags'):
                os.chflags(target, target.stat().st_flags & ~stat.UF_HIDDEN)
            files.append(target)
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--archive-name', default='DSH-Pet Smooth-macOS-arm64.zip')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This builder targets macOS arm64.')
    plugins = prepare_plugins()
    if args.prepare_only:
        return
    name = 'DSH-Pet Smooth'
    if Path(args.archive_name).name != args.archive_name or not args.archive_name.endswith('.zip'):
        parser.error('--archive-name must be a ZIP filename, without directories.')
    archive = ROOT / 'dist' / args.archive_name
    if archive.exists():
        parser.error(f'Archive already exists: {archive}; preserve or move it first.')
    # Documents may be FileProvider managed and gain FinderInfo during signing.
    # Sign and archive outside that directory, then copy only the sealed ZIP.
    staging = Path(tempfile.mkdtemp(prefix='dsh-pet-package-'))
    output = staging / f'{name}.app'
    command = [
        sys.executable, '-m', 'PyInstaller', '--clean', '--windowed', '--onedir',
        '--name', name, '--target-arch', 'arm64', '--paths', str(ROOT),
        '--distpath', str(staging), '--workpath', str(ROOT / 'build'),
        '--specpath', str(ROOT / 'build'), '--collect-all', 'imageio_ffmpeg',
        '--icon', str(ROOT / 'assets/app-icon.icns'),
        '--osx-bundle-identifier', 'com.yarrayyar.dsh-pet-smooth',
        '--add-data', f'{ROOT / "assets/characters"}:assets/characters',
        '--add-data', f'{ROOT / "assets/app-icon.png"}:assets',
        '--add-data', f'{ROOT / "assets/sounds"}:assets/sounds',
    ]
    for plugin in plugins:
        command.extend(['--add-binary', f'{plugin}:qt-plugins/{plugin.parent.name}'])
    command.append(str(ROOT / 'packaging/pet_entry.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    # Also protect bundled hook-collected plugins from inherited Finder hidden flags.
    for path in output.rglob('*'):
        if not path.is_symlink() and path.stat().st_flags & stat.UF_HIDDEN:
            os.chflags(path, path.stat().st_flags & ~stat.UF_HIDDEN)
    # Only the freshly generated bundle is cleaned; source assets stay untouched.
    subprocess.run(['xattr', '-cr', str(output)], check=True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(output)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(output)], check=True)
    staged_archive = staging / archive.name
    subprocess.run(['ditto', '-c', '-k', '--keepParent', '--norsrc', str(output), str(staged_archive)], check=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(staged_archive, archive)
    print(f'Verified bundle: {output}')
    print(f'Archive: {archive}')


if __name__ == '__main__':
    main()
