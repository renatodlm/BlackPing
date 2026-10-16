# BlackPing
# Instalar ou atualizar:
#   irm https://raw.githubusercontent.com/renatodlm/BlackPing/main/install.ps1 | iex

function Install-BlackPing {
    $ErrorActionPreference = 'Stop'
    $Repo = 'https://github.com/renatodlm/BlackPing.git'
    $Dest = Join-Path $env:LOCALAPPDATA 'BlackPing'

    function Find-PythonExe {
        $root = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path $root) {
            $found = Get-ChildItem -Path $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\Python3\d+\\python.exe$' } |
                Sort-Object FullName -Descending |
                Select-Object -First 1
            if ($found) { return $found.FullName }
        }
        foreach ($name in @('python', 'python3')) {
            $cmd = Get-Command $name -ErrorAction SilentlyContinue
            if ($cmd -and $cmd.Source -and $cmd.Source -notmatch 'WindowsApps') {
                return $cmd.Source
            }
        }
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($py -and $py.Source -notmatch 'WindowsApps') {
            $listed = & py -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $listed -and (Test-Path $listed.Trim()) -and $listed -notmatch 'WindowsApps') {
                return $listed.Trim()
            }
        }
        return $null
    }

    function Find-GitExe {
        $cmd = Get-Command git -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { return $cmd.Source }
        $default = 'C:\Program Files\Git\cmd\git.exe'
        if (Test-Path $default) { return $default }
        return $null
    }

    function Install-WithWinget {
        param([string]$Id, [string]$Label)
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "$Label não encontrado e o winget não está disponível."
        }
        Write-Host "Instalando $Label..."
        & winget install --id $Id -e --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            & winget install --id $Id -e --accept-package-agreements --accept-source-agreements
        }
    }

    $python = Find-PythonExe
    if (-not $python) {
        Install-WithWinget -Id 'Python.Python.3.12' -Label 'Python 3.12'
        $python = Find-PythonExe
        if (-not $python) {
            throw "O Python não apareceu depois da instalação. Abra um PowerShell novo e rode o comando de novo."
        }
    }
    Write-Host "Python: $python"

    $git = Find-GitExe
    if (-not $git) {
        Install-WithWinget -Id 'Git.Git' -Label 'Git'
        $git = Find-GitExe
        if (-not $git) {
            throw "O Git não apareceu depois da instalação. Abra um PowerShell novo e rode o comando de novo."
        }
    }

    if (Test-Path (Join-Path $Dest '.git')) {
        Write-Host "Atualizando $Dest"
        & $git -C $Dest pull --ff-only origin main
        if ($LASTEXITCODE -ne 0) {
            throw "Não consegui atualizar $Dest. Apague essa pasta e rode o instalador de novo."
        }
    } elseif (Test-Path $Dest) {
        throw "A pasta $Dest já existe e não é o BlackPing. Mova ou apague essa pasta e tente de novo."
    } else {
        Write-Host "Baixando BlackPing..."
        & $git clone --depth 1 --branch main $Repo $Dest
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao clonar $Repo"
        }
    }

    $venvPython = Join-Path $Dest '.venv\Scripts\python.exe'
    $venvPythonw = Join-Path $Dest '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path $venvPython)) {
        Write-Host "Criando ambiente Python..."
        & $python -m venv (Join-Path $Dest '.venv')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            throw "Não consegui criar o ambiente em $Dest\.venv"
        }
    }

    Write-Host "Instalando dependencias..."
    & $venvPython -m pip install -r (Join-Path $Dest 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao instalar as dependencias."
    }

    $launcher = $venvPythonw
    if (-not (Test-Path $launcher)) { $launcher = $venvPython }

    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcut = Join-Path $desktop 'BlackPing.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = $launcher
    $link.Arguments = '"' + (Join-Path $Dest 'main.py') + '"'
    $link.WorkingDirectory = $Dest
    $link.Description = 'Monitor de ping do Black Desert'
    $link.WindowStyle = 1
    $link.Save()

    Write-Host ""
    Write-Host "BlackPing instalado."
    Write-Host "Atalho: $shortcut"
    Write-Host "Para atualizar, rode este mesmo comando de novo."
}

Install-BlackPing
