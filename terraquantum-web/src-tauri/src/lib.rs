// TerraQuantum — orquestador de escritorio local-first (Tauri v2).
//
// Lanza DOS sidecars empaquetados en la app y NUNCA deja nada en la nube:
//   1. Backend Python (PyInstaller): FastAPI/uvicorn en 127.0.0.1:8010, con los
//      datos del usuario en %APPDATA%\TerraQuantum\data (fuera de la instalación).
//   2. Frontend Next.js (Node standalone): servidor en 127.0.0.1:3000 con los 40
//      proxies intactos → cero duplicación de lógica, cero cambios de código.
// La ventana muestra un splash y, cuando el frontend responde, navega al server
// local. Al cerrar la app se terminan ambos árboles de procesos.

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::path::BaseDirectory;
use tauri::{Manager, RunEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const BACKEND_PORT: u16 = 8010;
const FRONTEND_PORT: u16 = 3000;

/// PIDs de los sidecars, para terminarlos al salir.
struct Sidecars(Mutex<Vec<u32>>);

fn data_dir() -> PathBuf {
    // %APPDATA%\TerraQuantum\data en Windows; ~/.local/share/... en otros.
    let base = std::env::var("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            dirs_home().join(if cfg!(target_os = "macos") {
                "Library/Application Support"
            } else {
                ".local/share"
            })
        });
    base.join("TerraQuantum").join("data")
}

fn dirs_home() -> PathBuf {
    std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
}

fn resource(app: &tauri::App, rel: &str) -> Result<PathBuf, String> {
    app.path()
        .resolve(rel, BaseDirectory::Resource)
        .map(strip_verbatim)
        .map_err(|e| format!("no se pudo resolver el recurso {rel}: {e}"))
}

/// Quita el prefijo verbatim de Windows (\\?\) — Node mutila esas rutas al
/// resolver módulos (lstat 'C:' → EISDIR).
fn strip_verbatim(p: PathBuf) -> PathBuf {
    let s = p.to_string_lossy();
    match s.strip_prefix(r"\\?\") {
        Some(rest) => PathBuf::from(rest),
        None => p,
    }
}

fn logs_dir() -> PathBuf {
    let d = data_dir();
    let logs = d.parent().map(|p| p.join("logs")).unwrap_or_else(|| d.join("logs"));
    std::fs::create_dir_all(&logs).ok();
    logs
}

fn spawn_hidden(mut cmd: Command, log_name: &str) -> std::io::Result<u32> {
    // Redirigir a archivos de log (útil para el canal de diagnóstico y para
    // depurar el arranque de los sidecars sin ventana de consola).
    let log_path = logs_dir().join(log_name);
    let out = std::fs::File::create(&log_path)?;
    let err = out.try_clone()?;
    cmd.stdout(Stdio::from(out)).stderr(Stdio::from(err)).stdin(Stdio::null());
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let child = cmd.spawn()?;
    Ok(child.id())
}

fn wait_for_port(port: u16, timeout_secs: u64) -> bool {
    let addr: std::net::SocketAddr = format!("127.0.0.1:{port}").parse().unwrap();
    for _ in 0..(timeout_secs * 2) {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn start_sidecars(app: &tauri::App) -> Result<Vec<u32>, String> {
    let mut pids = Vec::new();

    let data = data_dir();
    std::fs::create_dir_all(&data).ok();

    // ── Backend Python (sidecar 1) ────────────────────────────────────────────
    let backend_exe = resource(app, "resources/backend/terraquantum-backend.exe")?;
    let mut backend = Command::new(&backend_exe);
    backend
        .env("TERRAQUANTUM_DATA_DIR", &data)
        .env("TERRAQUANTUM_HOST", "127.0.0.1")
        .env("TERRAQUANTUM_PORT", BACKEND_PORT.to_string());
    if let Some(dir) = backend_exe.parent() {
        backend.current_dir(dir);
    }
    match spawn_hidden(backend, "backend.log") {
        Ok(pid) => {
            pids.push(pid);
            log::info!("backend sidecar iniciado (pid {pid})");
        }
        Err(e) => return Err(format!("no se pudo iniciar el backend: {e}")),
    }

    // ── Frontend Next.js sobre Node (sidecar 2) ───────────────────────────────
    // Se pasa "server.js" RELATIVO (cwd = dir del frontend): la ruta ABSOLUTA que
    // devuelve el resolvedor de recursos puede venir con prefijo verbatim
    // (\\?\C:\...) y la resolución de módulo de Node la mutila a 'C:' (EISDIR).
    let node_exe = resource(app, "resources/node/node.exe")?;
    let frontend_dir = resource(app, "resources/frontend")?;
    let mut frontend = Command::new(&node_exe);
    frontend
        .arg("server.js")
        .current_dir(&frontend_dir)
        .env("PORT", FRONTEND_PORT.to_string())
        .env("HOSTNAME", "127.0.0.1")
        .env("NODE_ENV", "production")
        .env(
            "TERRAQUANTUM_BACKEND_URL",
            format!("http://127.0.0.1:{BACKEND_PORT}"),
        );
    match spawn_hidden(frontend, "frontend.log") {
        Ok(pid) => {
            pids.push(pid);
            log::info!("frontend sidecar iniciado (pid {pid})");
        }
        Err(e) => return Err(format!("no se pudo iniciar el frontend: {e}")),
    }

    Ok(pids)
}

fn kill_pid_tree(pid: u32) {
    #[cfg(windows)]
    {
        let mut cmd = Command::new("taskkill");
        cmd.args(["/F", "/T", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        cmd.creation_flags(CREATE_NO_WINDOW);
        let _ = cmd.status();
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill").args(["-9", &pid.to_string()]).status();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let pids = start_sidecars(app).unwrap_or_else(|e| {
                log::error!("fallo al iniciar sidecars: {e}");
                Vec::new()
            });
            app.manage(Sidecars(Mutex::new(pids)));

            // Cuando el frontend responde, navegar la ventana del splash al server.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if wait_for_port(FRONTEND_PORT, 90) {
                    if let Some(win) = handle.get_webview_window("main") {
                        let url = format!("http://localhost:{FRONTEND_PORT}");
                        if let Ok(u) = tauri::Url::parse(&url) {
                            let _ = win.navigate(u);
                        }
                    }
                } else {
                    log::error!("el frontend no respondió en 90s");
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la app Tauri")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<Sidecars>() {
                    if let Ok(pids) = state.0.lock() {
                        for pid in pids.iter() {
                            kill_pid_tree(*pid);
                        }
                    }
                }
            }
        });
}
