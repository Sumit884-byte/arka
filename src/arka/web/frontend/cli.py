"""CLI for Arka web frontends (`arka frontend start`, `arka frontend ollama`, `arka frontend open-webui`, `arka frontend all`)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def frontend_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "web" / "arka-ui"


def ollama_ui_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "web" / "ollama-ui"


def open_webui_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "web" / "open-webui"


def _bootstrap_env() -> None:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass


def _remote_url() -> str:
    return (
        os.environ.get("ARKA_BACKEND_URL")
        or os.environ.get("ARKA_REMOTE_URL")
        or os.environ.get("REMOTE_URL")
        or "http://127.0.0.1:8765"
    ).rstrip("/")


def _bridge_port() -> int:
    return int(os.environ.get("ARKA_BRIDGE_PORT", "8766"))


def _vite_port() -> int:
    return int(os.environ.get("ARKA_FRONTEND_PORT", "5173"))


def _ollama_bridge_port() -> int:
    return int(os.environ.get("ARKA_OLLAMA_BRIDGE_PORT", "8767"))


def _ollama_vite_port() -> int:
    return int(os.environ.get("ARKA_OLLAMA_FRONTEND_PORT", "5174"))


def _open_webui_bridge_port() -> int:
    return int(os.environ.get("ARKA_OPEN_WEBUI_BRIDGE_PORT", "8769"))


def _open_webui_port() -> int:
    return int(os.environ.get("ARKA_OPEN_WEBUI_PORT", "3000"))


def _open_webui_bridge_url(host: str, bridge_port: int) -> str:
    docker = os.environ.get("ARKA_OPEN_WEBUI_USE_DOCKER", "").strip().lower() in ("1", "true", "yes", "on")
    if docker and host in ("127.0.0.1", "localhost", "0.0.0.0"):
        return f"http://host.docker.internal:{bridge_port}/v1"
    bind = "127.0.0.1" if host in ("0.0.0.0", "") else host
    return f"http://{bind}:{bridge_port}/v1"


def _open_webui_branding_dir() -> Path:
    override = os.environ.get("ARKA_OPEN_WEBUI_BRANDING_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return open_webui_dir() / "branding"


def _open_webui_name() -> str:
    raw = os.environ.get("ARKA_OPEN_WEBUI_NAME", "").strip() or os.environ.get("WEBUI_NAME", "").strip()
    suffix = " (Open WebUI)"
    keep = os.environ.get("ARKA_OPEN_WEBUI_KEEP_SUFFIX", "").strip().lower() in ("1", "true", "yes", "on")
    if raw.endswith(suffix) and not keep:
        raw = raw[: -len(suffix)].strip()
    if not raw or raw == "Open WebUI":
        return "Arka"
    return raw


def _open_webui_keep_suffix() -> bool:
    return os.environ.get("ARKA_OPEN_WEBUI_KEEP_SUFFIX", "").strip().lower() in ("1", "true", "yes", "on")


def _open_webui_docker_cmd(
    *,
    host: str,
    ui_port: int,
    bridge_port: int,
    token: str,
    container: str,
    volume: str,
    image: str,
    branding: Path | None = None,
) -> list[str]:
    bridge_url = _open_webui_bridge_url(host, bridge_port)
    name = _open_webui_name()
    branding = branding if branding is not None else _open_webui_branding_dir()
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container,
        "-p",
        f"{ui_port}:8080",
        "--add-host=host.docker.internal:host-gateway",
        "-e",
        f"OPENAI_API_BASE_URL={bridge_url}",
        "-e",
        f"OPENAI_API_KEY={token}",
        "-e",
        "ENABLE_OLLAMA_API=false",
        "-e",
        "ENABLE_OPENAI_API=true",
        "-e",
        "DEFAULT_MODELS=arka",
        "-e",
        "ENABLE_FOLLOW_UP_GENERATION=false",
        "-e",
        "ENABLE_SIGNUP=true",
        "-e",
        f"WEBUI_NAME={name}",
        "-e",
        f"ARKA_OPEN_WEBUI_NAME={name}",
    ]
    if _open_webui_keep_suffix():
        cmd.extend(["-e", "ARKA_OPEN_WEBUI_KEEP_SUFFIX=1"])
    if branding.is_dir() and (branding / "docker-entrypoint.sh").is_file():
        cmd.extend(
            [
                "-v",
                f"{branding}:/opt/arka-branding:ro",
                "-e",
                "ARKA_OPEN_WEBUI_BRANDING_DIR=/opt/arka-branding",
                "--entrypoint",
                "bash",
            ]
        )
        cmd.extend(["-v", f"{volume}:/app/backend/data", image, "/opt/arka-branding/docker-entrypoint.sh"])
    else:
        cmd.extend(["-v", f"{volume}:/app/backend/data", image])
    return cmd


def _remote_token() -> str:
    return (
        os.environ.get("ARKA_BACKEND_TOKEN")
        or os.environ.get("ARKA_REMOTE_TOKEN")
        or os.environ.get("REMOTE_TOKEN")
        or ""
    ).strip()


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_running() -> bool:
    if not _docker_available():
        return False
    try:
        subprocess.check_output(["docker", "info"], stderr=subprocess.DEVNULL, timeout=4)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _src_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    src = _src_dir()
    if (src / "arka").is_dir():
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src) if not existing else f"{src}{os.pathsep}{existing}"
    return env


def _check_remote() -> tuple[bool, str]:
    url = f"{_remote_url()}/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw or "{}")
            if data.get("ok"):
                return True, "remote server online"
            return False, data.get("error") or "remote health check failed"
    except urllib.error.URLError as exc:
        return False, f"remote server not reachable at {_remote_url()} ({exc.reason})"
    except TimeoutError:
        return False, f"remote server timed out at {_remote_url()}"


def _start_backend() -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "arka.integrations.remote_server", "serve"],
        env=_python_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_remote(*, timeout: float = 12.0) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout
    last = "remote server not reachable"
    while time.monotonic() < deadline:
        ok, last = _check_remote()
        if ok:
            return True, last
        time.sleep(0.3)
    return False, last


def _ensure_backend(*, timeout: float = 12.0) -> tuple[bool, str, subprocess.Popen[str] | None]:
    """Start `arka serve` when the agent backend is down so UIs never run alone."""
    ok, note = _check_remote()
    if ok:
        return True, note, None
    print(f"Starting agent backend at {_remote_url()} …", flush=True)
    proc = _start_backend()
    time.sleep(0.4)
    if proc.poll() is not None:
        return False, f"agent backend exited immediately (code {proc.returncode})", proc
    ok, note = _wait_remote(timeout=timeout)
    if ok:
        return True, "started agent backend", proc
    return False, note, proc


def _stop_proc(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def _npm_available() -> bool:
    return shutil.which("npm") is not None


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _port_owner_hint(port: int) -> str:
    lsof = shutil.which("lsof")
    if not lsof:
        return ""
    try:
        out = subprocess.check_output(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    lines = out.splitlines()
    if len(lines) < 2:
        return ""
    parts = lines[1].split()
    if len(parts) >= 2:
        return f" ({parts[0]} pid {parts[1]})"
    return ""


def _ensure_ports_free(host: str, *ports: int) -> bool:
    blocked: list[tuple[int, str]] = []
    for port in ports:
        if _port_in_use(host, port):
            blocked.append((port, _port_owner_hint(port)))
    if not blocked:
        return True
    for port, hint in blocked:
        print(f"frontend: port {port} already in use{hint}", file=sys.stderr)
    print(
        "Stop the other process, or pass --bridge-port / --port "
        "(or set ARKA_BRIDGE_PORT / ARKA_FRONTEND_PORT).",
        file=sys.stderr,
    )
    return False


def _wait_bridge_ready(host: str, port: int, *, timeout: float = 8.0) -> bool:
    url = f"http://{host}:{port}/v1/config"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except urllib.error.URLError:
            pass
        time.sleep(0.2)
    return False


def _run_bridge(ui: Path, host: str, port: int, *, env_key: str = "ARKA_BRIDGE_PORT") -> subprocess.Popen[str]:
    bridge = ui / "bridge.py"
    env = os.environ.copy()
    env.setdefault(env_key, str(port))
    if env_key != "ARKA_BRIDGE_PORT":
        env.setdefault("ARKA_BRIDGE_PORT", str(port))
    return subprocess.Popen(
        [sys.executable, str(bridge), "--host", host, "--port", str(port)],
        cwd=str(ui),
        env=env,
    )


def _run_vite(ui: Path, port: int, *, bridge_port: int, bridge_env_key: str = "ARKA_BRIDGE_PORT") -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault(bridge_env_key, str(bridge_port))
    env.setdefault("ARKA_BRIDGE_PORT", str(bridge_port))
    return subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(ui),
        env=env,
    )


def _build_ui(ui: Path | None = None) -> int:
    ui = ui or frontend_dir()
    if not (ui / "package.json").is_file():
        print(f"frontend: missing {ui / 'package.json'}", file=sys.stderr)
        return 1
    if not _npm_available():
        print("frontend: npm is required to build the UI", file=sys.stderr)
        return 1
    if not (ui / "node_modules").is_dir():
        print("Installing npm dependencies…", flush=True)
        code = subprocess.call(["npm", "install"], cwd=str(ui))
        if code != 0:
            return code
    return subprocess.call(["npm", "run", "build"], cwd=str(ui))


def _cmd_start_ui(
    args: argparse.Namespace,
    *,
    ui: Path,
    label: str,
    default_bridge_port: int,
    default_vite_port: int,
    bridge_env_key: str = "ARKA_BRIDGE_PORT",
) -> int:
    bridge = ui / "bridge.py"
    if not bridge.is_file():
        print(f"{label}: bridge not found at {bridge}", file=sys.stderr)
        return 1

    ok, note, _backend = _ensure_backend()
    if not ok:
        print(f"Warning: {note}", file=sys.stderr)
        print("Chat needs the agent backend — it will keep retrying via arka serve.", file=sys.stderr)
    else:
        print(f"Agent backend: {_remote_url()} ({note})", flush=True)

    host = args.host or "127.0.0.1"
    bridge_port = args.bridge_port or default_bridge_port
    vite_port = args.port or default_vite_port

    if args.prod:
        code = _build_ui(ui)
        if code != 0:
            return code
        if not _ensure_ports_free(host, bridge_port):
            return 1
        print(f"{label} production UI: http://{host}:{bridge_port}", flush=True)
        if args.open:
            webbrowser.open(f"http://{host}:{bridge_port}/")
        return _run_bridge(ui, host, bridge_port, env_key=bridge_env_key).wait()

    if not _npm_available():
        print(f"{label}: npm is required for dev mode", file=sys.stderr)
        print("Install Node.js from https://nodejs.org/ (includes npm).", file=sys.stderr)
        return 1
    if not (ui / "package.json").is_file():
        print(f"{label}: missing {ui / 'package.json'}", file=sys.stderr)
        return 1
    if not (ui / "node_modules").is_dir():
        print("Installing npm dependencies…", flush=True)
        code = subprocess.call(["npm", "install"], cwd=str(ui))
        if code != 0:
            print(f"{label}: npm install failed — check network and Node.js version.", file=sys.stderr)
            return code

    if not _ensure_ports_free(host, bridge_port, vite_port):
        return 1

    bridge_proc = _run_bridge(ui, host, bridge_port, env_key=bridge_env_key)
    vite_proc = None
    try:
        bridge_code = bridge_proc.wait(timeout=0.5)
        print(
            f"{label}: bridge exited immediately (code {bridge_code}) — "
            f"check port {bridge_port} and PYTHONPATH.",
            file=sys.stderr,
        )
        return bridge_code or 1
    except subprocess.TimeoutExpired:
        pass

    if not _wait_bridge_ready(host, bridge_port):
        bridge_code = bridge_proc.poll()
        print(
            f"{label}: bridge did not become ready on http://{host}:{bridge_port}",
            file=sys.stderr,
        )
        if bridge_proc.poll() is None:
            bridge_proc.terminate()
            try:
                bridge_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                bridge_proc.kill()
        return bridge_code if bridge_code is not None else 1

    vite_proc = _run_vite(ui, vite_port, bridge_port=bridge_port, bridge_env_key=bridge_env_key)
    url = f"http://{host}:{vite_port}"
    print(f"{label} dev: {url}", flush=True)
    print(f"Bridge API: http://{host}:{bridge_port}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        while True:
            bridge_code = bridge_proc.poll()
            vite_code = vite_proc.poll() if vite_proc else None
            if bridge_code is not None:
                print(f"{label}: bridge stopped (code {bridge_code})", file=sys.stderr)
                return bridge_code
            if vite_code is not None:
                print(f"{label}: Vite stopped (code {vite_code})", file=sys.stderr)
                return vite_code
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    finally:
        for proc in (vite_proc, bridge_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()


def cmd_start(args: argparse.Namespace) -> int:
    return _cmd_start_ui(
        args,
        ui=frontend_dir(),
        label="Arka frontend",
        default_bridge_port=_bridge_port(),
        default_vite_port=_vite_port(),
    )


def cmd_ollama_start(args: argparse.Namespace) -> int:
    return _cmd_start_ui(
        args,
        ui=ollama_ui_dir(),
        label="Arka Ollama UI",
        default_bridge_port=_ollama_bridge_port(),
        default_vite_port=_ollama_vite_port(),
        bridge_env_key="ARKA_OLLAMA_BRIDGE_PORT",
    )


def cmd_bridge(args: argparse.Namespace) -> int:
    ui = frontend_dir()
    bridge = ui / "bridge.py"
    host = args.host or "127.0.0.1"
    port = args.bridge_port or _bridge_port()
    return subprocess.call([sys.executable, str(bridge), "--host", host, "--port", str(port)], cwd=str(ui))


def _run_open_webui_docker(host: str, ui_port: int, bridge_port: int, *, open_browser: bool) -> int:
    if not _docker_available():
        print("open-webui: docker not found — install Docker or use --pip", file=sys.stderr)
        return 1
    token = _remote_token()
    if not token:
        print("open-webui: set REMOTE_TOKEN in ~/.config/arka/.env (from `arka serve`)", file=sys.stderr)
        return 1
    bridge_url = _open_webui_bridge_url(host, bridge_port)
    container = os.environ.get("ARKA_OPEN_WEBUI_CONTAINER", "arka-open-webui")
    volume = os.environ.get("ARKA_OPEN_WEBUI_VOLUME", "open-webui-arka")
    image = os.environ.get("ARKA_OPEN_WEBUI_IMAGE", "ghcr.io/open-webui/open-webui:main")
    branding = _open_webui_branding_dir()
    subprocess.call(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = _open_webui_docker_cmd(
        host=host,
        ui_port=ui_port,
        bridge_port=bridge_port,
        token=token,
        container=container,
        volume=volume,
        image=image,
        branding=branding,
    )
    url = f"http://127.0.0.1:{ui_port}"
    print(f"Open WebUI (Docker): {url}", flush=True)
    print(f"OpenAI bridge: {bridge_url}", flush=True)
    print(f"Branding: {_open_webui_name()}", flush=True)
    if open_browser:
        time.sleep(2)
        webbrowser.open(url)
    return subprocess.call(cmd)


def _run_open_webui_pip(host: str, ui_port: int, bridge_port: int, *, open_browser: bool) -> int:
    token = _remote_token()
    if not token:
        print("open-webui: set REMOTE_TOKEN in ~/.config/arka/.env (from `arka serve`)", file=sys.stderr)
        return 1
    bridge_url = _open_webui_bridge_url(host, bridge_port)
    env = os.environ.copy()
    env["OPENAI_API_BASE_URL"] = bridge_url
    env["OPENAI_API_KEY"] = token
    env.setdefault("ENABLE_OLLAMA_API", "false")
    env.setdefault("ENABLE_OPENAI_API", "true")
    env.setdefault("DEFAULT_MODELS", "arka")
    env.setdefault("ENABLE_SIGNUP", "true")
    env.setdefault("PORT", str(ui_port))
    name = _open_webui_name()
    env["WEBUI_NAME"] = name
    env["ARKA_OPEN_WEBUI_NAME"] = name
    branding = _open_webui_branding_dir()
    apply_py = branding / "apply.py"
    url = f"http://127.0.0.1:{ui_port}"
    print(f"Open WebUI (pip): {url}", flush=True)
    print(f"OpenAI bridge: {bridge_url}", flush=True)
    print(f"Branding: {name}", flush=True)
    if open_browser:
        time.sleep(2)
        webbrowser.open(url)
    if apply_py.is_file():
        return subprocess.call(
            [sys.executable, str(apply_py), "--serve", "--host", "0.0.0.0", "--port", str(ui_port)],
            env=env,
        )
    open_webui_bin = shutil.which("open-webui")
    if not open_webui_bin:
        print("open-webui: install with `pip install open-webui` (Python 3.11+)", file=sys.stderr)
        return 1
    return subprocess.call([open_webui_bin, "serve", "--port", str(ui_port)], env=env)


def cmd_open_webui_start(args: argparse.Namespace) -> int:
    ui = open_webui_dir()
    bridge = ui / "bridge.py"
    if not bridge.is_file():
        print(f"open-webui: bridge not found at {bridge}", file=sys.stderr)
        return 1

    ok, note, _backend = _ensure_backend()
    if not ok:
        print(f"Warning: {note}", file=sys.stderr)
        print("Chat needs the agent backend — it will keep retrying via arka serve.", file=sys.stderr)
    else:
        print(f"Agent backend: {_remote_url()} ({note})", flush=True)

    host = args.host or "127.0.0.1"
    bridge_port = args.bridge_port or _open_webui_bridge_port()
    use_docker = args.docker or (not args.pip and _docker_running())
    ui_port = args.port
    if ui_port is None:
        ui_port = _open_webui_port() if use_docker else int(os.environ.get("ARKA_OPEN_WEBUI_PIP_PORT", "8080"))
    reuse_bridge = _port_in_use(host, bridge_port) and _wait_bridge_ready(host, bridge_port, timeout=1.5)
    if reuse_bridge:
        print(f"Reusing Open WebUI bridge on http://{host}:{bridge_port}/v1", flush=True)
    elif not _ensure_ports_free(host, bridge_port):
        return 1
    ui_already_running = use_docker and _port_in_use(host, ui_port)
    if ui_already_running:
        print(
            f"open-webui: UI already on http://{host}:{ui_port} — starting bridge only",
            flush=True,
        )
    elif args.pip and _port_in_use(host, ui_port):
        print(f"open-webui: port {ui_port} already in use{_port_owner_hint(ui_port)}", file=sys.stderr)
        return 1

    env = _python_env()
    env.setdefault("ARKA_OPEN_WEBUI_BRIDGE_PORT", str(bridge_port))
    bridge_proc: subprocess.Popen[str] | None = None
    if not reuse_bridge:
        bridge_proc = subprocess.Popen(
            [sys.executable, str(bridge), "--host", host, "--port", str(bridge_port)],
            cwd=str(ui),
            env=env,
        )
        try:
            bridge_code = bridge_proc.wait(timeout=0.5)
            print(
                f"open-webui: bridge exited immediately (code {bridge_code}) — check port {bridge_port}.",
                file=sys.stderr,
            )
            return bridge_code or 1
        except subprocess.TimeoutExpired:
            pass

        if not _wait_bridge_ready(host, bridge_port):
            bridge_code = bridge_proc.poll()
            print(f"open-webui: bridge did not become ready on http://{host}:{bridge_port}", file=sys.stderr)
            if bridge_proc.poll() is None:
                bridge_proc.terminate()
            return bridge_code if bridge_code is not None else 1

    try:
        if ui_already_running:
            if bridge_proc is not None:
                print("Bridge running — refresh Open WebUI and select model: arka", flush=True)
                try:
                    bridge_proc.wait()
                except KeyboardInterrupt:
                    pass
            elif reuse_bridge:
                print("Bridge already running — refresh Open WebUI and select model: arka", flush=True)
            code = 0
        elif use_docker:
            os.environ["ARKA_OPEN_WEBUI_USE_DOCKER"] = "1"
            code = _run_open_webui_docker(host, ui_port, bridge_port, open_browser=bool(args.open))
        else:
            code = _run_open_webui_pip(host, ui_port, bridge_port, open_browser=bool(args.open))
    finally:
        if bridge_proc is not None and bridge_proc.poll() is None:
            bridge_proc.terminate()
            try:
                bridge_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                bridge_proc.kill()
    return code


def cmd_open_webui_bridge(args: argparse.Namespace) -> int:
    ui = open_webui_dir()
    bridge = ui / "bridge.py"
    host = args.host or "127.0.0.1"
    port = args.bridge_port or _open_webui_bridge_port()
    env = os.environ.copy()
    env.setdefault("ARKA_OPEN_WEBUI_BRIDGE_PORT", str(port))
    return subprocess.call([sys.executable, str(bridge), "--host", host, "--port", str(port)], cwd=str(ui), env=env)


def cmd_ollama_bridge(args: argparse.Namespace) -> int:
    ui = ollama_ui_dir()
    bridge = ui / "bridge.py"
    host = args.host or "127.0.0.1"
    port = args.bridge_port or _ollama_bridge_port()
    env = os.environ.copy()
    env.setdefault("ARKA_OLLAMA_BRIDGE_PORT", str(port))
    return subprocess.call(
        [sys.executable, str(bridge), "--host", host, "--port", str(port)],
        cwd=str(ui),
        env=env,
    )


def _run_open_webui_bridge_proc(host: str, port: int) -> subprocess.Popen[str]:
    ui = open_webui_dir()
    env = _python_env()
    env.setdefault("ARKA_OPEN_WEBUI_BRIDGE_PORT", str(port))
    return subprocess.Popen(
        [sys.executable, str(ui / "bridge.py"), "--host", host, "--port", str(port)],
        cwd=str(ui),
        env=env,
    )


def _spawn_open_webui_docker(host: str, ui_port: int, bridge_port: int) -> subprocess.Popen[str] | None:
    if not _docker_running():
        return None
    token = _remote_token()
    if not token:
        print("open-webui: set REMOTE_TOKEN in ~/.config/arka/.env to start Docker UI", file=sys.stderr)
        return None
    container = os.environ.get("ARKA_OPEN_WEBUI_CONTAINER", "arka-open-webui")
    volume = os.environ.get("ARKA_OPEN_WEBUI_VOLUME", "open-webui-arka")
    image = os.environ.get("ARKA_OPEN_WEBUI_IMAGE", "ghcr.io/open-webui/open-webui:main")
    subprocess.call(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["ARKA_OPEN_WEBUI_USE_DOCKER"] = "1"
    cmd = _open_webui_docker_cmd(
        host=host,
        ui_port=ui_port,
        bridge_port=bridge_port,
        token=token,
        container=container,
        volume=volume,
        image=image,
        branding=_open_webui_branding_dir(),
    )
    print(f"Open WebUI (Docker): http://127.0.0.1:{ui_port}", flush=True)
    return subprocess.Popen(cmd)


def cmd_all(args: argparse.Namespace) -> int:
    """Start the agent backend and every web UI as one supervised stack."""
    host = args.host or "127.0.0.1"
    ok, note, _backend = _ensure_backend()
    if not ok:
        print(f"frontend all: {note}", file=sys.stderr)
        return 1
    print(f"Agent backend: {_remote_url()} ({note})", flush=True)

    members: list[dict[str, object]] = [
        {
            "name": "agent backend",
            "factory": _start_backend,
            "health": lambda: _check_remote()[0],
            "proc": None,
            "owned": False,
        }
    ]

    ui_specs = (
        (
            "Arka frontend",
            frontend_dir(),
            args.bridge_port or _bridge_port(),
            args.port or _vite_port(),
            "ARKA_BRIDGE_PORT",
        ),
        (
            "Arka Ollama UI",
            ollama_ui_dir(),
            args.ollama_bridge_port or _ollama_bridge_port(),
            args.ollama_port or _ollama_vite_port(),
            "ARKA_OLLAMA_BRIDGE_PORT",
        ),
    )
    for label, ui, bridge_port, vite_port, env_key in ui_specs:
        if not (ui / "bridge.py").is_file():
            print(f"{label}: bridge not found at {ui / 'bridge.py'}", file=sys.stderr)
            continue
        members.append(
            {
                "name": f"{label} bridge",
                "factory": lambda ui=ui, host=host, bridge_port=bridge_port, env_key=env_key: _run_bridge(
                    ui, host, bridge_port, env_key=env_key
                ),
                "health": lambda host=host, bridge_port=bridge_port: _port_in_use(host, bridge_port),
                "proc": None,
                "owned": False,
            }
        )
        can_vite = _npm_available() and (ui / "package.json").is_file()
        if can_vite and not (ui / "node_modules").is_dir():
            print(f"Installing npm dependencies for {label}…", flush=True)
            can_vite = subprocess.call(["npm", "install"], cwd=str(ui)) == 0
        if can_vite:
            members.append(
                {
                    "name": f"{label} Vite",
                    "factory": lambda ui=ui, vite_port=vite_port, bridge_port=bridge_port, env_key=env_key: _run_vite(
                        ui, vite_port, bridge_port=bridge_port, bridge_env_key=env_key
                    ),
                    "health": lambda host=host, vite_port=vite_port: _port_in_use(host, vite_port),
                    "proc": None,
                    "owned": False,
                }
            )
        print(
            f"{label}: http://{host}:{vite_port}  (bridge :{bridge_port})",
            flush=True,
        )

    open_bridge_port = args.open_webui_bridge_port or _open_webui_bridge_port()
    if (open_webui_dir() / "bridge.py").is_file():
        members.append(
            {
                "name": "Open WebUI bridge",
                "factory": lambda: _run_open_webui_bridge_proc(host, open_bridge_port),
                "health": lambda: _port_in_use(host, open_bridge_port),
                "proc": None,
                "owned": False,
            }
        )
        print(f"Open WebUI bridge: http://{host}:{open_bridge_port}/v1", flush=True)
        if not args.no_open_webui and _docker_running():
            ui_port = args.open_webui_port or _open_webui_port()
            members.append(
                {
                    "name": "Open WebUI Docker",
                    "factory": lambda: _spawn_open_webui_docker(host, ui_port, open_bridge_port),
                    "health": lambda: _port_in_use(host, ui_port),
                    "proc": None,
                    "owned": False,
                }
            )
        elif not args.no_open_webui:
            print(
                "Open WebUI app skipped — Docker daemon is not running. Bridge stays up.",
                flush=True,
            )

    def _ensure_member(member: dict[str, object]) -> None:
        health = member["health"]
        proc = member["proc"]
        if callable(health) and health():
            return
        if isinstance(proc, subprocess.Popen) and proc.poll() is None:
            return
        factory = member["factory"]
        if not callable(factory):
            return
        started = factory()
        member["proc"] = started
        member["owned"] = started is not None

    for member in members:
        _ensure_member(member)
        name = str(member["name"])
        if callable(member["health"]) and member["health"]():
            print(f"  {name}: up", flush=True)
        else:
            print(f"  {name}: starting", flush=True)

    print("Combined stack running — Ctrl+C stops UIs started here (backend stays up).", flush=True)
    try:
        while True:
            ok, _note = _check_remote()
            if not ok:
                print("Agent backend dropped — restarting …", flush=True)
            for member in members:
                health = member["health"]
                proc = member["proc"]
                healthy = bool(callable(health) and health())
                alive = isinstance(proc, subprocess.Popen) and proc.poll() is None
                if healthy or alive:
                    continue
                print(f"Restarting {member['name']} …", flush=True)
                _ensure_member(member)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopped combined stack.", flush=True)
        return 0
    finally:
        for member in members:
            if member.get("owned") and str(member.get("name")) != "agent backend":
                proc = member.get("proc")
                if isinstance(proc, subprocess.Popen):
                    _stop_proc(proc)


def route_command(cmd: str) -> str | None:
    import re

    clean = " ".join((cmd or "").split()).strip()
    if not clean:
        return None
    if re.search(
        r"(?i)\b(?:combined|together|all)\b.*\b(?:frontend|dashboard|ui|backends?|stack)\b"
        r"|\b(?:frontend|dashboard|ui|backends?|stack)\b.*\b(?:combined|together|all)\b"
        r"|\b(?:start|run|launch)\s+(?:the\s+)?(?:arka\s+)?(?:backends?|stack)\b"
        r"|\b(?:start|run|launch)\s+all\s+(?:arka\s+)?(?:frontends?|uis?|backends?)\b"
        r"|\b(?:arka\s+)?frontend\s+all\b",
        clean,
    ):
        return "frontend all"
    if re.search(
        r"(?i)\b(?:start|open|launch|run)\b.*\b(?:open[\s-]?webui|openwebui)\b",
        clean,
    ):
        return "frontend open-webui"
    if re.search(r"(?i)^(?:arka\s+)?(?:open[\s-]?webui|frontend\s+open[\s-]?webui)\b", clean):
        return "frontend open-webui"
    if re.search(
        r"(?i)\b(?:start|open|launch|run)\b.*\b(?:ollama(?:-|\s)?ui|ollama\s+frontend|frontend\s+ollama)\b",
        clean,
    ):
        return "frontend ollama"
    if re.search(r"(?i)^(?:arka\s+)?(?:ollama(?:-|\s)?ui|frontend\s+ollama)\b", clean):
        return "frontend ollama"
    if re.search(
        r"(?i)\b(?:start|open|launch|run)\b.*\b(?:arka\s+)?(?:web\s+)?(?:frontend|dashboard|ui)\b",
        clean,
    ):
        return "frontend start"
    if re.search(r"(?i)^(?:arka\s+)?(?:web\s+ui|frontend\s+start|web\s+dashboard)\b", clean):
        return "frontend start"
    return None


def nl_to_argv(text: str) -> list[str]:
    routed = route_command(text)
    if routed:
        return routed.split()[1:]
    return []


def main(argv: list[str] | None = None) -> int:
    _bootstrap_env()
    parser = argparse.ArgumentParser(prog="arka frontend", description="Arka web dashboard")
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="Start bridge + Vite dev server (default)")
    p_start.add_argument("--host", default="127.0.0.1", help="Listen host")
    p_start.add_argument("--port", type=int, default=None, help="Vite dev port (default 5173)")
    p_start.add_argument("--bridge-port", type=int, default=None, help="Bridge port (default 8766)")
    p_start.add_argument("--prod", action="store_true", help="Build UI and serve from bridge only")
    p_start.add_argument("--open", action="store_true", help="Open browser after starting")

    p_bridge = sub.add_parser("bridge", help="Run HTTP bridge only")
    p_bridge.add_argument("--host", default="127.0.0.1")
    p_bridge.add_argument("--bridge-port", type=int, default=None)

    sub.add_parser("build", help="Build production UI bundle")

    p_ollama = sub.add_parser("ollama", help="Start Ollama-style chat UI (bridge + Vite)")
    p_ollama.add_argument("--host", default="127.0.0.1", help="Listen host")
    p_ollama.add_argument("--port", type=int, default=None, help="Vite dev port (default 5174)")
    p_ollama.add_argument("--bridge-port", type=int, default=None, help="Bridge port (default 8767)")
    p_ollama.add_argument("--prod", action="store_true", help="Build UI and serve from bridge only")
    p_ollama.add_argument("--open", action="store_true", help="Open browser after starting")

    p_ollama_bridge = sub.add_parser("ollama-bridge", help="Run Ollama UI bridge only")
    p_ollama_bridge.add_argument("--host", default="127.0.0.1")
    p_ollama_bridge.add_argument("--bridge-port", type=int, default=None)

    p_open = sub.add_parser("open-webui", help="Start Open WebUI + Arka OpenAI bridge")
    p_open.add_argument("--host", default="127.0.0.1", help="Bridge listen host")
    p_open.add_argument("--port", type=int, default=None, help="Open WebUI port (default 3000 Docker, 8080 pip)")
    p_open.add_argument("--bridge-port", type=int, default=None, help="OpenAI bridge port (default 8769)")
    p_open.add_argument("--docker", action="store_true", help="Run Open WebUI via Docker (default when available)")
    p_open.add_argument("--pip", action="store_true", help="Run Open WebUI via pip install")
    p_open.add_argument("--open", action="store_true", help="Open browser after starting")

    p_open_bridge = sub.add_parser("open-webui-bridge", help="Run Open WebUI OpenAI bridge only")
    p_open_bridge.add_argument("--host", default="127.0.0.1")
    p_open_bridge.add_argument("--bridge-port", type=int, default=None)

    p_all = sub.add_parser("all", help="Start agent backend + every web UI together and keep them up")
    p_all.add_argument("--host", default="127.0.0.1", help="Listen host")
    p_all.add_argument("--port", type=int, default=None, help="Arka UI Vite port (default 5173)")
    p_all.add_argument("--bridge-port", type=int, default=None, help="Arka UI bridge port (default 8766)")
    p_all.add_argument("--ollama-port", type=int, default=None, help="Ollama UI Vite port (default 5174)")
    p_all.add_argument("--ollama-bridge-port", type=int, default=None, help="Ollama UI bridge port (default 8767)")
    p_all.add_argument("--open-webui-port", type=int, default=None, help="Open WebUI Docker port (default 3000)")
    p_all.add_argument("--open-webui-bridge-port", type=int, default=None, help="Open WebUI bridge port (default 8769)")
    p_all.add_argument("--no-open-webui", action="store_true", help="Skip the Open WebUI Docker/pip app")
    p_all.add_argument("--open", action="store_true", help="Open the Arka UI in a browser")

    args = parser.parse_args(argv)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "bridge":
        return cmd_bridge(args)
    if args.command == "build":
        return _build_ui()
    if args.command == "ollama":
        return cmd_ollama_start(args)
    if args.command == "ollama-bridge":
        return cmd_ollama_bridge(args)
    if args.command == "open-webui":
        return cmd_open_webui_start(args)
    if args.command == "open-webui-bridge":
        return cmd_open_webui_bridge(args)
    if args.command == "all":
        if getattr(args, "open", False):
            webbrowser.open(f"http://{args.host or '127.0.0.1'}:{args.port or _vite_port()}")
        return cmd_all(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
