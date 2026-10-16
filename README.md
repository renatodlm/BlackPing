# BlackPing

Janela leve para ver o ping das conexões do Black Desert no Windows.

## Instalar

No PowerShell:

```powershell
irm https://raw.githubusercontent.com/renatodlm/BlackPing/main/install.ps1 | iex
```

O comando instala o Python se precisar, baixa este repositório em `%LOCALAPPDATA%\BlackPing` e cria o atalho **BlackPing** na área de trabalho. Rodar de novo atualiza o app.

## Abrir nesta pasta

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
```
