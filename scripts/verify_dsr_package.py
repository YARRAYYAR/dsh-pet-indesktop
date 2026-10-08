"""Check the delivered macOS bundle against its source and unchanged HD assets."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from types import CodeType

from PyInstaller.archive.readers import CArchiveReader


MODULES = (
    'app', 'animation_thumbnail', 'branding', 'ceiling_geometry', 'codex_link', 'config',
    'context_menus.icons', 'context_menus.shared', 'decode_fanout', 'frame_edges',
    'ffmpeg_params', 'gui_stall_sampler', 'interaction', 'library', 'modern_settings_dialog', 'settings_actions',
    'settings_brand', 'settings_codex', 'settings_task_appearance', 'task_bubble', 'task_bubble_style', 'settings_commands', 'settings_navigation',
    'settings_pet_controls', 'settings_theme_qss', 'settings_widgets', 'top_flip',
    'ui_motion', 'webm_clip', 'window', 'window_optional_services', 'window_placement',
)


def structure(value):
    # File paths and line metadata differ after PyInstaller rewrites filenames.
    # Instructions, nested constants, symbols and exception tables must match.
    if isinstance(value, CodeType):
        fields = ('co_code', 'co_consts', 'co_names', 'co_varnames', 'co_freevars',
                  'co_cellvars', 'co_argcount', 'co_posonlyargcount',
                  'co_kwonlyargcount', 'co_flags', 'co_exceptiontable')
        return {field: structure(getattr(value, field)) for field in fields}
    if isinstance(value, (tuple, list)):
        return [structure(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((structure(item) for item in value), key=repr)
    if isinstance(value, bytes):
        return {'bytes': value.hex()}
    if value is Ellipsis:
        return {'constant': 'Ellipsis'}
    if isinstance(value, complex):
        return {'complex': repr(value)}
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    bundle = args.app.resolve()
    output = args.output or root / 'docs/evidence/dsr-pet/package-verification.json'
    checks, errors = {}, []
    try:
        info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
        binary = bundle / 'Contents/MacOS' / info['CFBundleExecutable']
        checks['info'] = {key: info[key] for key in ('CFBundleDisplayName',
                          'CFBundleShortVersionString', 'CFBundleVersion', 'CFBundleIdentifier')}
        checks['binary_sha256'] = digest(binary)
        checks['architecture'] = subprocess.check_output(['file', str(binary)], text=True).strip()
        assert 'arm64' in checks['architecture']
        archive = CArchiveReader(str(binary)).open_embedded_archive('PYZ.pyz')
        checks['source_modules'] = {}
        for name in MODULES:
            source = root / 'pet' / (name.replace('.', '/') + '.py')
            module = 'pet.' + name
            expected = compile(source.read_bytes(), module, 'exec')
            assert structure(archive.extract(module)) == structure(expected), module
            checks['source_modules'][module] = digest(source)
        excluded = [name for name in archive.toc if name == 'pet.chat' or name.startswith('pet.chat.')
                    or name.startswith('pet.dynamic_island') or name.startswith('pet.island_collision')]
        assert not excluded, excluded
        checks['excluded_modules'] = excluded
        checks['icons'] = {}
        for name in ('app-icon.png', 'app-icon-mac.png'):
            source = root / 'pet/resources' / name
            packaged = bundle / 'Contents/Resources/pet/resources' / name
            assert digest(packaged) == digest(source), name
            checks['icons'][name] = digest(source)
        icon_name = info['CFBundleIconFile']
        icon_path = bundle / 'Contents/Resources' / icon_name
        if not icon_path.suffix:
            icon_path = icon_path.with_suffix('.icns')
        assert digest(icon_path) == digest(root / 'assets/icon.icns'), 'Bundle ICNS differs'
        checks['icons']['bundle_icns'] = digest(icon_path)
        assert info['CFBundleDisplayName'] == 'seeky· pet'
        assets = root / 'assets/characters'
        checks['assets'] = []
        for source in sorted(assets.rglob('*.webm')):
            relative = source.relative_to(root)
            packaged = bundle / 'Contents/Resources' / relative
            value = digest(source)
            assert digest(packaged) == value, str(relative)
            checks['assets'].append({'path': str(relative), 'sha256': value})
        assert len(checks['assets']) == 106
        checks['hq_assets'] = []
        for source in sorted((root / 'assets/characters_hq').rglob('*.webm')):
            relative = source.relative_to(root)
            value = digest(source)
            assert digest(bundle / 'Contents/Resources' / relative) == value, str(relative)
            checks['hq_assets'].append({'path': str(relative), 'sha256': value})
        assert len(checks['hq_assets']) == 106
        index = Path('assets/characters_hq/shenshen/videos/quality-index.json')
        assert digest(root / index) == digest(bundle / 'Contents/Resources' / index)
        checks['settings_icons'] = {}
        for source in sorted((root / 'pet/resources/settings-icons').iterdir()):
            if source.is_file():
                relative = source.relative_to(root)
                value = digest(source)
                assert digest(bundle / 'Contents/Resources' / relative) == value, str(relative)
                checks['settings_icons'][str(relative)] = value
        notice = digest(root / 'THIRD_PARTY_NOTICES')
        assert digest(bundle / 'Contents/Resources/THIRD_PARTY_NOTICES') == notice
        checks['third_party_notice_sha256'] = notice
        assert info['CFBundleVersion'] == '4.2.1.8'
        result = subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)],
                                capture_output=True, text=True)
        checks['codesign'] = {'exit_status': result.returncode, 'output': result.stdout + result.stderr}
        assert result.returncode == 0, checks['codesign']['output']
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()),
                                 '--app', str(bundle), '--output', str(output)], 'cwd': str(root),
                                 'setup': 'Completed arm64 bundle and source tree; read-only verification',
                                 'assertions': 'Source bytecode matches; 106 source and 106 HQ hashes plus index and settings SVG/license match; pure modules excluded; signature valid; bundle version 4.2.1.8',
                                 'reset': 'Read-only; no configuration or application state changed',
                                 'checks': checks, 'errors': errors, 'exit_status': int(bool(errors))},
                                ensure_ascii=False, indent=2))
    print('PASS' if not errors else errors)
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
