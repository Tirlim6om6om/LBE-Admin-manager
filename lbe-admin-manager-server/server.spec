# -*- mode: python ; coding: utf-8 -*-

a = Analysis(['server.py'],
             pathex=['path_to_your_script'],  # Замените на путь к вашему скрипту
             binaries=[
                 ('AdbWinApi.dll', '.'),
                 ('AdbWinUsbApi.dll', '.'),
                 ('avcodec-61.dll', '.'),
                 ('avformat-61.dll', '.'),
                 ('avutil-59.dll', '.'),
                 ('libusb-1.0.dll', '.'),
                 ('SDL2.dll', '.'),
                 ('swresample-5.dll', '.'),
                 ('scrcpy-server', '.'),
                 ('scrcpy.exe', '.'),
                 ('scrcpy-console.bat', '.'),
                 ('scrcpy-noconsole.vbs', '.'),
                 ('bindings.json', '.'),
                 ('icon.png', '.'),
                 ('open_a_terminal_here.bat', '.'),
             ],
             datas=[
                 ('uploads/', 'uploads'),  # Включаем папку uploads
             ],
             hiddenimports=[
                 'zeroconf._handlers.answers',
                 'zeroconf._utils.ipaddress',
                 'flask',
                 'flask.json',  # Include Flask's JSON module
                 'flask.request',  # Include request module
                 'flask.jsonify',  # Include jsonify module
                 'subprocess',  # Include subprocess module
                 'os',  # Include os module
                 'json',  # Include json module
                 're',  # Include re module
                 'urllib.parse',  # Include urllib.parse module
             ],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=None,
             noarchive=False)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)