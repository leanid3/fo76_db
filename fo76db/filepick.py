"""Системное окно выбора папки или файла для «Настройки → Пути игры». Сервер работает на этом же компьютере, поэтому окно
открывает он: Linux — zenity или kdialog, Windows — PowerShell (диалоги Windows Forms), macOS — osascript."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class PickError(Exception):
    pass


def _start(start: str) -> str:
    p = Path(start).expanduser() if start else Path.home()
    while p != p.parent and not p.is_dir():
        p = p.parent
    return str(p)


def _command(folder: bool, start: str, title: str) -> list[str]:
    title = (title or ("Выберите папку" if folder else "Выберите файл"))[:120]
    if sys.platform == "win32":
        kind = "FolderBrowserDialog" if folder else "OpenFileDialog"
        prop = "SelectedPath" if folder else "FileName"
        script = ("Add-Type -AssemblyName System.Windows.Forms; "
                  f"$d = New-Object System.Windows.Forms.{kind}; $d.{prop} = '{start.replace(chr(39), chr(39) * 2)}'; "
                  + ("$d.Description = $env:FO76_TITLE; " if folder else "$d.Title = $env:FO76_TITLE; ")
                  + "if ($d.ShowDialog() -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                  + f"Write-Output $d.{prop} }}")
        return ["powershell", "-NoProfile", "-STA", "-Command", script]
    if sys.platform == "darwin":
        what = "choose folder" if folder else "choose file"
        prompt = title.replace("\\", "\\\\").replace('"', '\\"')  # AppleScript: строка в кавычках
        return ["osascript", "-e", f'POSIX path of ({what} with prompt "{prompt}")']
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", *(["--directory"] if folder else []), f"--title={title}", f"--filename={start}/"]
    if shutil.which("kdialog"):
        return ["kdialog", "--getexistingdirectory" if folder else "--getopenfilename", start, "--title", title]
    raise PickError("Не найден системный диалог выбора (нужен zenity или kdialog) — введите путь вручную")


def pick(folder: bool, start: str = "", title: str = "") -> str:
    """Путь, выбранный пользователем; пустая строка, если окно закрыли без выбора."""
    start = _start(start)
    env = {**os.environ, "FO76_TITLE": title or ("Выберите папку" if folder else "Выберите файл")}
    try:
        r = subprocess.run(_command(folder, start, title), capture_output=True, text=True, encoding="utf-8",
                           timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return ""
    except OSError as e:
        raise PickError(f"Не удалось открыть окно выбора: {e}")
    return r.stdout.strip().splitlines()[-1].strip() if r.returncode == 0 and r.stdout.strip() else ""
