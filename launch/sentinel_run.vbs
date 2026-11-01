' sentinel_run.vbs -- run one poll without flashing a console window.
' Task Scheduler starts this GUI host; WScript.Shell.Run uses window style 0.
Option Explicit
Dim fso, shell, here, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
command = fso.BuildPath(here, "sentinel_run.cmd")
shell.Run "cmd.exe /c """ & command & """", 0, False
