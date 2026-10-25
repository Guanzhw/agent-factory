"""Package an already built research demo without rebuilding or changing its assets."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-head', required=True, help='Exact commit used to produce the supplied build')
    parser.add_argument('--html-output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    fixture = root / 'scripts/research_demo_delivery'
    files = {str(path.relative_to(args.build)): path.read_bytes() for path in (args.build / 'assets').rglob('*') if path.is_file()}
    index = (args.build / 'index.html').read_text().replace('"/assets/', '"./assets/')
    index = index.replace('<head>', '<head><script src="./synthetic-fetch.js"></script>', 1)
    files['index.html'] = index.encode()
    for name in ('synthetic-fetch.js', 'README.md'):
        files[name] = (fixture / name).read_bytes()
    licenses = [(root / 'LICENSE').read_text()]
    for package in ('react', 'react-dom', 'scheduler', 'chart.js', '@kurkle/color', '@tabler/icons-react'):
        directory = root / 'node_modules' / package
        candidates = sorted(directory.glob('LICENSE*'))
        licenses.append(f'\n\n--- {package} ---\n' + candidates[0].read_text())
    files['LICENSES.txt'] = '\n'.join(licenses).encode()
    files['BUILD.json'] = json.dumps({'sourceHead': args.source_head, 'identity': 'offline synthetic fixture', 'assetsSha256': {name: hashlib.sha256(value).hexdigest() for name, value in files.items() if name.startswith('assets/')}}, indent=2).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, 'w', ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    print(f'{args.output}: {args.output.stat().st_size} bytes')
    if args.html_output:
        standalone = index.replace('<script src="./synthetic-fetch.js"></script>', '<script>' + files['synthetic-fetch.js'].decode() + '</script>')
        standalone = re.sub(r'<script type="module" crossorigin src="\./([^" ]+)"></script>', lambda match: '<script type="module">' + files[match[1]].decode() + '</script>', standalone)
        standalone = re.sub(r'<link rel="stylesheet" crossorigin href="\./([^" ]+)">', lambda match: '<style>' + files[match[1]].decode() + '</style>', standalone)
        # License text is inert text, retained in the single-file distribution.
        notice = json.dumps({'build': json.loads(files['BUILD.json']), 'licenses': files['LICENSES.txt'].decode()}, ensure_ascii=False).replace('<', '\u003c')
        standalone = standalone.replace('</body>', '<script type="application/json" id="distribution-notice">' + notice + '</script></body>')
        args.html_output.write_text(standalone)
        print(f'{args.html_output}: {args.html_output.stat().st_size} bytes')


if __name__ == '__main__':
    main()
