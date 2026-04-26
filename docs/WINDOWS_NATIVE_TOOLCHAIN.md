# Windows-Native Development Toolchain

This document records the adopted Windows-native toolchain for the user's primary Java, JavaScript, TypeScript, and Python work.

Observed adoption date: 2026-04-27.

## Operating Rule

Use Codex App on Windows as the execution control plane and keep repo-specific commands in each repo's `AGENTS.md` and package scripts.

Load repo/runtime variables through `.env`:

```powershell
dotenv -e .env -- <command>
```

The PowerShell profile pins `dotenv` to npm `dotenv-cli` and reinserts the `--` command separator that PowerShell normally strips for functions. If that profile is not loaded, use:

```powershell
& "$env:APPDATA\npm\dotenv.cmd" -e .env -- <command>
```

## Runtime Roles

| Surface | Adopted tools | Role |
| --- | --- | --- |
| Package/bootstrap | Scoop, winget | User-space installs first; winget for packages not cleanly available through Scoop. |
| Java | Temurin JDK 21, Maven, Gradle, Visual Studio Build Tools | JDK baseline for Java work; Maven/Gradle for project builds; VS Build Tools for native dependency builds. |
| JavaScript | Node.js, npm, pnpm, corepack, Bun | Node/npm remain the compatibility baseline; pnpm is available for repos that require it; Bun is the fast runtime/package runner when a repo allows it. |
| TypeScript | TypeScript, tsx, Bun, Deno, Zod, zx, Biome | `tsc` for typechecking, `tsx` for script execution, Zod for runtime schemas, zx for shell-script ergonomics, Biome for JS/TS formatting/linting when a repo has no stricter local tool. |
| Python | Python 3.14/3.12, uv, ruff, micromamba, DirectML venv, shlex | Python remains checker/runtime default; `ruff` is the default formatter/linter, `shlex` is the built-in shell-quoting/parsing helper, micromamba only for binary/scientific isolation, DirectML venv for Windows GPU tests. |
| Native/build | Zig, Visual Studio Build Tools | Zig is available for native experiments and cross-toolchain work; VS Build Tools remain the MSVC/native dependency baseline. |
| Search/navigation | fzf, Everything CLI/HTTP | Fast local file narrowing in terminal and browser/API search against `C:\Users\anise\code`. |
| Cleanup/diagnostics | npkill, WizTree, Process Explorer/Sysinternals, PowerToys | Clean dependency bulk, inspect disk/process state, and operate Windows productivity tools. |
| Automation | AutoHotkey v2 | Windows UI automation only when a task explicitly needs it. |

## Installed Version Snapshot

| Tool | Observed version/status |
| --- | --- |
| Visual Studio Build Tools | 2026 BuildTools 18.4.3, VC toolchain present |
| Java | Temurin OpenJDK 21.0.10 |
| Maven | 3.9.15 |
| Gradle | 9.4.1 |
| Node.js | 24.14.1 |
| npm | 11.11.0 |
| corepack | 0.34.6 |
| pnpm | 10.33.2 |
| Bun | 1.3.13 |
| Deno | 2.7.13 |
| TypeScript | 6.0.3 |
| tsx | 4.21.0 |
| Zod | 4.3.6 |
| zx | 8.8.5 |
| ruff | 0.15.12 |
| Biome | 2.4.13 |
| Zig | 0.16.0 |
| micromamba | 2.5.0 |
| AutoHotkey | v2.0.24 |
| Everything | 1.4.1.1032 |
| Everything CLI | 1.1.0.37 |
| fzf | 0.72.0 |
| Sysinternals | 20260409 |
| PowerToys | 0.98.1 |

## `.env` Contract

Repo-local `.env` is ignored by Git. `.env.example` is the tracked template.

Current required keys:

```text
CANONICAL_EXECUTION_HOST
DEVMGMT_ROOT
DEV_WORKFLOW_ROOT
DEV_PRODUCT_ROOT
DEV_SCRATCH_ROOT
CODEX_CLI_BIN
CODEX_HOME
SCOOP_HOME
SCOOP_SHIMS
JAVA_HOME
MAVEN_HOME
GRADLE_HOME
GRADLE_USER_HOME
BUN_INSTALL
MICROMAMBA_ROOT_PREFIX
DIRECTML_PY312_VENV
EVERYTHING_HTTP_URL
EVERYTHING_INDEX_ROOT
```

Use `.env` for local root and tool locations. Do not hardcode these values inside scripts when a script can read the environment.

## Everything HTTP

Everything is configured for local development search:

```text
URL: http://127.0.0.1:8088/
Indexed root: C:\Users\anise\code
File download: disabled
```

Examples:

```powershell
es -n 20 Dev-Management
Invoke-WebRequest 'http://127.0.0.1:8088/?search=Dev-Management&count=20'
```

The HTTP server is loopback-bound so it is a local search surface, not a network file browser.

## Common Commands

```powershell
scoop update
scoop status
scoop install <app>
```

```powershell
java -version
mvn -version
gradle --version
```

```powershell
npm run <script>
bun run <script>
tsx scripts\some-script.ts
tsc --noEmit
```

```powershell
python -m venv .venv
uv pip install -r requirements.txt
micromamba create -n <name> python=3.12
```

```powershell
npkill
wiztree64
procexp
```

## Build Tools Boundary

Visual Studio Build Tools are installed and should be treated as native dependency support for Python wheels, Node native modules, and Java/JNI-adjacent builds.

Use a developer shell only when a build actually needs MSVC variables:

```powershell
& cmd.exe /c call 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat' '&&' where cl
```

## AI/GPU Boundary

DirectML is the Windows-native GPU path already verified under:

```text
C:\Users\anise\.venvs\directml-py312
```

Use it for Windows GPU smoke tests and ONNX Runtime DirectML checks. Do not use Intel IPEX as the default Windows path because the current Intel Extension for PyTorch line is end-of-life in 2026.

## Coding References

Use these references actively when writing or reviewing code:

- Zod: TypeScript runtime schemas at boundaries, config loading, CLI inputs, and JSON report parsing.
- zx by Google: JS/TS scripts that must call native commands, with clear quoting and process handling.
- Python `shlex`: built-in shell parsing/quoting helper for Python command construction; prefer it over ad hoc splitting.
- Airbnb JavaScript Style Guide: default JS readability/style reference when no repo-local rule overrides it.
- Google Python Style Guide: default Python readability/style reference when no repo-local rule overrides it.
- Refactoring.Guru: pattern-based refactoring vocabulary; use patterns only when they reduce real complexity.
- 30 seconds of code: small idiom/reference source for implementation options, not authority over repo contracts.
- Greptile: external AI code-review reference/service when available; the npm CLI package is currently macOS-only and is not installed on this Windows host.

## Code Guardrails

After code edits, run the matching local guardrail before final claims:

```powershell
ruff check .
```

```powershell
biome check .
```

```powershell
zig fmt --check <zig-files>
zig build test
```

Use repo-owned scripts first when present. These global tools are the fallback guardrails for repos that do not already define stricter lint/format/test commands.

## Windows Domain Knowledge

The global Windows-native knowledge list is recorded in:

```text
C:\Users\anise\code\Dev-Management\docs\WINDOWS_NATIVE_DOMAIN_KNOWLEDGE.md
```

## Sources

- Scoop official installer/docs: https://github.com/ScoopInstaller/Scoop
- Bun installation docs: https://bun.sh/docs/installation
- Everything HTTP docs: https://www.voidtools.com/support/everything/http/
- Everything command-line docs: https://www.voidtools.com/support/everything/command_line_options/
- dotenv-cli README: https://github.com/entropitor/dotenv-cli
- Zod docs: https://zod.dev/
- zx by Google: https://github.com/google/zx
- Python shlex docs: https://docs.python.org/3/library/shlex.html
- Airbnb JavaScript Style Guide: https://github.com/airbnb/javascript
- Google Python Style Guide: https://google.github.io/styleguide/pyguide.html
- Refactoring.Guru design patterns: https://refactoring.guru/design-patterns
- 30 seconds of code: https://www.30secondsofcode.org/
- Greptile docs: https://docs.greptile.com/
- Ruff docs: https://docs.astral.sh/ruff/
- Biome docs: https://biomejs.dev/
- Zig downloads/docs: https://ziglang.org/download/
- Microsoft PowerToys docs: https://learn.microsoft.com/en-us/windows/powertoys/
- Intel Extension for PyTorch installation guide/EOL notice: https://pytorch-extension.intel.com/
