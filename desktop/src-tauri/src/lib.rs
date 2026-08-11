use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

pub struct ArkaBackend {
    remote: Option<Child>,
    bridge: Option<Child>,
}

impl ArkaBackend {
    pub fn start() -> Result<Self, String> {
        let python = resolve_python();
        let repo = resolve_repo_root();
        let desktop = desktop_dir();
        let mut env = std::env::vars().collect::<std::collections::HashMap<_, _>>();
        let src = repo.join("src");
        if src.is_dir() {
            let existing = env.get("PYTHONPATH").cloned().unwrap_or_default();
            let merged = if existing.is_empty() {
                src.display().to_string()
            } else {
                format!("{}:{}", src.display(), existing)
            };
            env.insert("PYTHONPATH".into(), merged);
        }

        let remote = spawn_process(
            &python,
            &["-m", "arka.integrations.remote_server", "serve"],
            &repo,
            &env,
        )
        .map_err(|e| format!("failed to start arka serve: {e}"))?;

        wait_for_port(8765, 45)?;

        let bridge_script = desktop.join("bridge.py");
        let bridge = spawn_process(&python, &[bridge_script.to_string_lossy().as_ref()], &desktop, &env)
            .map_err(|e| format!("failed to start bridge: {e}"))?;

        wait_for_port(8766, 30)?;

        eprintln!("Arka backend ready (remote :8765, bridge :8766)");
        Ok(Self {
            remote: Some(remote),
            bridge: Some(bridge),
        })
    }
}

impl Drop for ArkaBackend {
    fn drop(&mut self) {
        stop_child(&mut self.bridge);
        stop_child(&mut self.remote);
    }
}

fn stop_child(child: &mut Option<Child>) {
    if let Some(mut proc) = child.take() {
        let _ = proc.kill();
        let _ = proc.wait();
    }
}

fn spawn_process(
    program: &str,
    args: &[&str],
    cwd: &Path,
    env: &std::collections::HashMap<String, String>,
) -> std::io::Result<Child> {
    let mut cmd = Command::new(program);
    cmd.args(args).current_dir(cwd).envs(env).stdout(Stdio::null()).stderr(Stdio::null());
    cmd.spawn()
}

fn wait_for_port(port: u16, seconds: u64) -> Result<(), String> {
    let deadline = Duration::from_secs(seconds);
    let start = std::time::Instant::now();
    while start.elapsed() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err(format!("timed out waiting for 127.0.0.1:{port}"))
}

fn resolve_python() -> String {
    if let Ok(v) = std::env::var("ARKA_PYTHON") {
        if !v.trim().is_empty() {
            return v;
        }
    }
    for candidate in ["python3", "python"] {
        if Command::new(candidate)
            .arg("-c")
            .arg("import arka")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
        {
            return candidate.into();
        }
    }
    "python3".into()
}

fn resolve_repo_root() -> PathBuf {
    if let Ok(v) = std::env::var("ARKA_REPO") {
        let p = PathBuf::from(v);
        if p.is_dir() {
            return p;
        }
    }
    desktop_dir().parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."))
}

fn desktop_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| {
            let mut dir = exe.parent()?.to_path_buf();
            for _ in 0..6 {
                if dir.join("bridge.py").is_file() {
                    return Some(dir);
                }
                dir = dir.parent()?.to_path_buf();
            }
            None
        })
        .unwrap_or_else(|| resolve_repo_root().join("desktop"))
}

pub type BackendState = Mutex<Option<ArkaBackend>>;

#[tauri::command]
fn backend_status(state: tauri::State<'_, BackendState>) -> serde_json::Value {
    let running = state.lock().map(|g| g.is_some()).unwrap_or(false);
    serde_json::json!({
        "ok": running,
        "remote": "http://127.0.0.1:8765",
        "bridge": "http://127.0.0.1:8766"
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_state: BackendState = Mutex::new(None);

    tauri::Builder::default()
        .manage(backend_state)
        .setup(|app| {
            match ArkaBackend::start() {
                Ok(backend) => {
                    if let Ok(mut guard) = app.state::<BackendState>().lock() {
                        *guard = Some(backend);
                    }
                }
                Err(err) => {
                    eprintln!("Arka backend startup warning: {err}");
                    eprintln!("Install Arka (pipx install arka-agent) and set REMOTE_TOKEN in ~/.config/arka/.env");
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
