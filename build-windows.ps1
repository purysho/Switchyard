$ErrorActionPreference = 'Stop'
python -m pip install --upgrade pyinstaller pillow
python .\tools\make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Switchyard --icon assets/icon.ico switchyard_desktop.pyw
Write-Host "Built dist\Switchyard.exe"
