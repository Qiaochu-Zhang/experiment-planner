from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]
datas = collect_data_files('experiment_planner')
hiddenimports = []
for package in ('ax', 'botorch', 'gpytorch', 'linear_operator'):
    hiddenimports += collect_submodules(package, filter=lambda name: '.tests' not in name and '.test_' not in name)
    datas += collect_data_files(package, include_py_files=False)
for package in ('ax-platform', 'botorch', 'torch'):
    datas += copy_metadata(package)
datas += [(str(root / 'docs' / 'user_guide.md'), 'help')]
a = Analysis([str(root / 'packaging/windows/launcher.py')], pathex=[str(root / 'src')],
    binaries=[], datas=datas, hiddenimports=hiddenimports,
    excludes=['IPython', 'ipywidgets', 'jupyter', 'pytest', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ExperimentPlanner',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ExperimentPlanner')
