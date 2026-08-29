$ErrorActionPreference = "Stop"

function Find-Python {
    foreach ($cmd in @("python", "py", "python3")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($exe) {
            return $exe.Source
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python が見つかりません。以下からインストールしてください:"
    Write-Host "  https://www.python.org/downloads/"
    Write-Host "インストール時に 'Add python.exe to PATH' にチェックを入れてください。"
    exit 1
}

Write-Host "Python: $python"
& $python -m pip install --upgrade pip
Write-Host "CUDA 対応 PyTorch をインストール中..."
& $python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
& $python -m pip install -r "$PSScriptRoot\requirements.txt"
Write-Host ""
Write-Host "セットアップ完了。"
Write-Host "1. calibrate.bat  … 座標を1回だけ調整"
Write-Host "2. extract.bat    … フォルダ選択して CSV 出力"
