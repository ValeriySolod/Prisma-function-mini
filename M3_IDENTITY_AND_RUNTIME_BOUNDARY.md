# M.3 Mini Identity and Runtime Boundary

## 1. Authoritative identity

| Identity | Value |
|---|---|
| Application/internal name | `PrismaFunctionMini` |
| Display/product name | `Prisma Function Mini` |
| Executable | `PrismaFunctionMini.exe` |
| PyInstaller package directory | `PrismaFunctionMini` |
| Version-resource file | `PrismaFunctionMini.version` |
| PyInstaller specification | `PrismaFunctionMini.spec` |
| Installer definition | `PrismaFunctionMini.iss` |
| Installer base name | `PrismaFunctionMini-Setup-<version>-windows-x64` |
| Release archive | `PrismaFunctionMini-v<version>-windows-x64.zip` |
| Initial Mini version | `0.1.0` |

The installer uses a Mini-specific AppId,
`{118861B7-7FAB-4B85-B88A-F557D89A6986}`, so it does not upgrade or uninstall
the inherited PrismaFunction application.

## 2. Authoritative writable runtime layout

All production runtime writes belong below
`%LOCALAPPDATA%\PrismaFunctionMini`:

```text
%LOCALAPPDATA%\PrismaFunctionMini\
  data\prisma_function_mini.db
  data\result\prisma_function_mini.xlsx
  state\prisma_function_mini_state.json
  logs\prisma-function-mini.log
  temporary-downloads\
```

SQLite sidecars, rotated logs, staged workbook files, migration locks, and future
partial downloads must remain beside their corresponding Mini-owned target or
inside the Mini root. Source, package, and installation directories are not
writable runtime targets. M.10 will define temporary-download file lifecycle,
partial-file naming, validation, and cleanup; M.3 establishes only its directory
boundary.

## 3. Historical PrismaFunction data decision

`%LOCALAPPDATA%\PrismaFunction` is inherited historical user data and is
read-only to Mini. Mini does not scan, copy, move, rename, overwrite, delete,
rebuild, or reinterpret that root during startup, installation, upgrade,
uninstallation, or normal operation.

No automatic historical-data migration is approved. The old database combines
auction history with monitoring tables and old operation/workbook contracts, so
wholesale reuse is unsafe. A future explicit opt-in copy/transform decision may
be implemented only after the Mini storage and workbook contracts are approved
in M.5 and M.6. Such a migration must read the old root without modifying it,
write only to staged Mini-owned targets, validate transactionally, preserve
conflicts, and require its own focused tests and approval.

## 4. Validation boundary

Automated M.3 tests prove identity consistency, exact path construction,
Mini-only directory preparation, preservation of a populated old root, log
placement, package exclusion of runtime artifacts, version-resource identity,
and installer identity. They do not prove a packaged launch, installed upgrade,
uninstall, Microsoft Excel behavior, live PRISMA behavior, or clean-machine
operation; those remain M.14 and M.15 evidence.
