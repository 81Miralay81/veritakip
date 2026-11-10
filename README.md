# Miralay IFS Explorer

Windows desktop MVP for locally saving and comparing selected IFS Applications 10.10 records.

## Build and download
GitHub Actions builds on every push to main and can be started manually from Actions. Download the EXE from the run's Artifacts section.

## Target PC requirements
- Windows 10/11 and PowerShell 5.1.
- IFS Applications 10.10 client installed and launched at least once under the same Windows user.
- IFS ClickOnce assemblies available under %LOCALAPPDATA%\Apps\2.0.
- An IFS account authorized to read the selected view.

## First use
1. Sign in to IFS normally.
2. Start the app and paste an IFS !IFS.COPYOBJECT block into a new source.
3. Save and verify the suggested key fields.
4. Press Şimdi Çek and authenticate in the normal IFS login dialog if requested.

## Safety and limitations
- Read-only SELECT only; no IFS data changes.
- Query requires copied key values and is capped at 20 rows. No unbounded table scans.
- Initial key inference is best-effort; verify the key fields are unique.
- API/function expressions in COPYOBJECT are not selected as columns.
- This MVP rechecks the copied record(s), not a full table-wide change feed.
- Scheduled execution requires Windows and the IFS login context; unattended login is not guaranteed.
- Passwords are never stored.

Snapshots are stored in %LOCALAPPDATA%\MiralayIFSExplorer\data.db.
