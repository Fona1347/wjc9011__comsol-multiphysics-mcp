TL;DR: Follow-up diagnostics narrowed the COMSOL MCP startup issue to two separate causes. With redirected runtime directories enabled, COMSOL server starts and reports a port, but `mph.Client(port=...)` fails with a server login error. Without redirected directories, COMSOL fails earlier because the user-profile configuration directory is not writable from the Codex sandbox.

# COMSOL MCP Start Timeout Follow-up Report

## Implemented

- Added `login_mode` support to `comsol_start`, `SessionManager.start`, and the MCP-owned `ManagedComsolServer`.
- Supported COMSOL login modes are `auto`, `never`, `force`, and `info`.
- Added non-sensitive login diagnostics for `login.properties` candidates. Reports include path, existence, size, modified time, and access flags only; file contents are never read or returned.
- Added startup failure classification:
  - `server_login_failed`
  - `login_or_credentials_failed`
  - `license_checkout_failed`
  - `filesystem_or_process_permission_failed`
  - `port_or_connection_failed`
  - `server_start_timeout`
  - `server_started_client_connect_failed`
  - `user_profile_permissions_suspect`
  - `unknown_start_failure`
- Added `login_mode`, `failure_category`, `server_diagnostics`, and login file metadata to startup failure returns and JSON reports.
- Added lightweight process cleanup recommendations to preflight. Preflight remains diagnostic-only and does not kill unknown COMSOL or Java processes.
- Added equivalent failure classification to `comsol_connect` so manually started servers produce clearer errors.

## Verification

Static and mock checks:

```text
.\.venv\python.exe -m compileall src tests
manual extended session smoke tests passed
git diff --check
```

`pytest` was not run because the current `.venv` still does not have `pytest` installed.

Preflight result:

```text
COMSOL backend 6.4: available
.comsol_runtime prefs directory writable: true
C:\Users\Huayun\.comsol\v64\tomcat\logs writable: false
C:\Users\Huayun\.comsol\v64\configuration writable: false
C:\Users\Huayun\.comsol\v64\workspace writable: false
runtime prefs login.properties exists: true
user root login.properties exists: true
ports 2036-2040: not occupied
```

## Startup Matrix Findings

### Redirected runtime directories, random port

Command shape:

```text
comsol_start(version="6.4", cores=2, timeout_seconds=45,
             mode="client-server", port=0,
             redirect_user_dirs=true, login_mode="auto")
```

Result:

```text
failure_category: server_login_failed
server reported port: yes
COMSOL/Java residual processes: none after cleanup
latest report: dev_log/comsol_start_timeout_20260522_181306.json
```

Interpretation: COMSOL server startup itself is no longer timing out. The server reaches the port-ready stage, then `mph.Client(port=...)` fails with "用户名或密码错误".

### Fixed port 2036

Command shape:

```text
comsol_start(version="6.4", cores=2, timeout_seconds=90,
             mode="client-server", port=2036,
             redirect_user_dirs=true, login_mode="auto")
```

Result:

```text
failure_category: server_login_failed
```

Interpretation: the random-port path is not the cause. Fixed 2036 reaches the same login failure.

### Stand-alone mode

Command shape:

```text
comsol_start(version="6.4", cores=2, timeout_seconds=90,
             mode="stand-alone", redirect_user_dirs=true)
```

Result:

```text
success: true
version: 6.4
standalone: true
```

Interpretation: COMSOL Java/JVM and license access can work in stand-alone mode. The remaining failure is specific to COMSOL Multiphysics Server / client-server login.

### No redirected runtime directories

Command shape:

```text
comsol_start(version="6.4", cores=2, timeout_seconds=25,
             mode="client-server", port=0,
             redirect_user_dirs=false, login_mode="auto")
```

Result:

```text
failure_category: filesystem_or_process_permission_failed
latest report: dev_log/comsol_start_timeout_20260522_181336.json
```

Key server output:

```text
Invalid Configuration Location
The configuration area at 'C:\Users\Huayun\.comsol\v64\configuration\comsol' is not writable.
Please choose a writable location using the '-configuration' command line option.
```

Interpretation: redirected runtime directories are required in the Codex sandbox. Disabling redirect reproduces the original user-profile write-permission blocker.

## Current Diagnosis

The original "black-box timeout" is resolved for the MCP-owned start path. There are now two clear buckets:

- User-profile write permissions cause startup failure when COMSOL is allowed to use `C:\Users\Huayun\.comsol\v64`.
- With `.comsol_runtime` redirect enabled, server startup succeeds, but client-server authentication fails.

The most likely remaining fix is to resolve COMSOL Multiphysics Server credentials/login policy, or avoid client-server mode when possible by using `mode="stand-alone"` for workflows that do not need external server semantics.

## Recommended Next Actions

- Restart the Codex MCP server so the live tool schema exposes `login_mode` and the updated diagnostics.
- For immediate modeling work, try `comsol_start(version="6.4", cores=2, mode="stand-alone")`; this was the only successful real startup path in the matrix.
- For client-server mode, reset or initialize COMSOL Multiphysics Server credentials in a normal user PowerShell/COMSOL session, then retry:

```text
D:\Softwares_02\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe -port 2036 -multi on
```

- After manual server startup succeeds, test MCP `comsol_connect(host="localhost", port=2036)` and inspect the returned `failure_category` if it still fails.
