# Ollama paused (2026-10-24)

Operator ruling: Ollama is paused, not uninstalled. Nothing was deleted (program
files in `%LOCALAPPDATA%\Programs\Ollama`, models and the Startup shortcut are intact).

## Found

- Autostart: the shortcut `Ollama.lnk` in the user Startup folder
  (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`), target
  `%LOCALAPPDATA%\Programs\Ollama\ollama app.exe`. Its Task Manager state lived in
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder`,
  value `Ollama.lnk` = `02 00 00 00 00 00 00 00 00 00 00 00` (enabled).
- Not present: HKLM/HKCU `Run` and `RunOnce` (64- and 32-bit views), the common
  Startup folder, scheduled tasks, services.
- Running: `ollama app.exe` (PID 7284), which started `ollama.exe serve` (PID 19524,
  listening on `[::]:11434`).

## Changed

- `StartupApproved\StartupFolder\Ollama.lnk` set to `03 00 00 00` + disable
  timestamp, which is what Task Manager's "Disable" writes.
- Both processes stopped. Afterwards `Get-Process ollama*` was empty and nothing
  listened on port 11434.

## Revert

```powershell
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder' -Name 'Ollama.lnk' -Type Binary -Value ([byte[]](2,0,0,0,0,0,0,0,0,0,0,0))
```

That re-enables it from the next logon. To start it now as well:
`Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"`. Ollama loading a
model competes with llama-server for the 16 GB of VRAM.
