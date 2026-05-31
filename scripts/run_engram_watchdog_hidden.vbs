Option Explicit

Dim shell
Dim fso
Dim scriptPath
Dim powershellPath
Dim command
Dim exitCode

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count > 0 Then
    scriptPath = WScript.Arguments.Item(0)
Else
    scriptPath = fso.GetParentFolderName(WScript.ScriptFullName) & "\watch_engram_hub.ps1"
End If

powershellPath = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = """" & powershellPath & """ -NoProfile -ExecutionPolicy Bypass -File """ & scriptPath & """"

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
