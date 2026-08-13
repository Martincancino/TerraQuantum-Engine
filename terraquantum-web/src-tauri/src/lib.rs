// TerraQuantum — orquestador de escritorio local-first (Tauri v2).
//
// Lanza DOS sidecars empaquetados en la app y NUNCA deja nada en la nube:
//   1. Backend Python (PyInstaller): FastAPI/uvicorn en 127.0.0.1:8010, con los
//      datos del usuario en %APPDATA%\TerraQuantum\data (fuera de la instalación).
//   2. Frontend Next.js (Node standalone): servidor en 127.0.0.1:3000 con los 40
//      proxies intactos → cero duplicación de lógica, cero cambios de código.
//
// ── Fase 2 — "que el instalador falle en voz alta" ────────────────────────────
// El principio del producto ("ningún input produce basura silenciosa; siempre un
// error en español que dice qué hacer") se aplicaba al pipeline de datos y NO al
// arranque, que es justo donde no hay un desarrollador presente. Esta versión lo
// corrige con cinco mecanismos:
//
//   H-17  El splash deja de ser una animación infinita: recibe eventos de estado
//         y, si algo falla, muestra causa en español + [Reintentar] + [Ver
//         registros]. Todo lo que se muestra se escribe además a `boot.jsonl`,
//         que es lo que audita el gate de arranque adverso.
//   H-18  Job Object de Windows con KILL_ON_JOB_CLOSE: si matan la app desde el
//         Administrador de Tareas, el SO mata a los sidecars. Deja de depender de
//         que se dispare `RunEvent::Exit`.
//   H-19  El chequeo de salud pregunta por `/health` y compara un TOKEN DE
//         INSTANCIA generado en este arranque. Un `TcpStream::connect` sólo
//         prueba que alguien escucha; esto prueba QUIÉN escucha. El frontend se
//         valida por `/api/backend-health`, que además demuestra que el sidecar
//         Node está emparejado con NUESTRO backend.
//   H-20  El updater tiene por fin camino de consumo: "Buscar actualizaciones…"
//         en el menú. Es MANUAL a propósito — un producto local-first no debe
//         hacer llamadas de red silenciosas al arrancar.
//   H-21  Puertos: se eligen ANTES de spawnear. Si el preferido está ocupado se
//         usa el siguiente libre y se dice por qué; el backend elegido viaja al
//         sidecar Node por entorno, así que los proxies siguen apuntando bien.
//
// La ventana muestra el splash y sólo navega al servidor local cuando la
// identidad de AMBOS sidecars está verificada.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::menu::{MenuBuilder, MenuItemBuilder, SubmenuBuilder};
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Emitter, Listener, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Puertos preferidos. Si están ocupados se usa el siguiente libre del tramo.
const BACKEND_PORT: u16 = 8010;
const FRONTEND_PORT: u16 = 3000;
const PORT_SPAN: u16 = 12;

/// El backend es un onefile de ~200 MB: la primera ejecución se descomprime y
/// puede además ser escaneada por el antivirus. 180 s es holgado a propósito;
/// lo que no es aceptable es esperar para siempre (H-17).
const BACKEND_READY_TIMEOUT: Duration = Duration::from_secs(180);
const FRONTEND_READY_TIMEOUT: Duration = Duration::from_secs(120);
const PROBE_TIMEOUT: Duration = Duration::from_millis(1500);
const POLL_INTERVAL: Duration = Duration::from_millis(400);

// ─────────────────────────────────────────────────────────────────────────────
// Estado compartido
// ─────────────────────────────────────────────────────────────────────────────

struct Sidecar {
    /// Nombre técnico, para logs y para el gate.
    key: &'static str,
    /// Nombre en español, para el usuario.
    label: &'static str,
    child: Child,
}

#[derive(Default)]
struct Shell {
    sidecars: Vec<Sidecar>,
    booting: bool,
    ready_url: Option<String>,
}

struct ShellState(Mutex<Shell>);

/// Identidad de ESTE arranque. Se genera una vez y se compara contra lo que
/// publica `/health`: es lo que distingue "mi sidecar" de "un zombi que ocupa el
/// puerto" (H-19).
fn instance_token() -> &'static str {
    static TOKEN: OnceLock<String> = OnceLock::new();
    TOKEN.get_or_init(|| {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        format!("tq-{:x}-{:x}", std::process::id(), nanos)
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// Rutas
// ─────────────────────────────────────────────────────────────────────────────

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

fn resource(app: &AppHandle, rel: &str) -> Result<PathBuf, String> {
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

// ─────────────────────────────────────────────────────────────────────────────
// Diario de arranque: lo que ve el usuario y lo que audita el gate
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone, Serialize)]
struct BootEvent {
    /// "backend" | "frontend" | "ready" | "error"
    stage: &'static str,
    /// "start" | "waiting" | "ok" | "warn" | "error"
    state: &'static str,
    /// Mensaje en español para el usuario. Nunca vacío.
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail: Option<String>,
    /// Código estable (para soporte y para el gate). Sólo en errores y avisos.
    #[serde(skip_serializing_if = "Option::is_none")]
    code: Option<&'static str>,
    /// Qué puede hacer el usuario. Obligatorio cuando hay error.
    #[serde(skip_serializing_if = "Option::is_none")]
    hint: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    url: Option<String>,
    logs_dir: String,
    elapsed_ms: u128,
}

fn boot_started() -> Instant {
    static T0: OnceLock<Instant> = OnceLock::new();
    *T0.get_or_init(Instant::now)
}

fn event(stage: &'static str, state: &'static str, message: impl Into<String>) -> BootEvent {
    BootEvent {
        stage,
        state,
        message: message.into(),
        detail: None,
        code: None,
        hint: None,
        url: None,
        logs_dir: logs_dir().to_string_lossy().to_string(),
        elapsed_ms: boot_started().elapsed().as_millis(),
    }
}

/// Publica un estado de arranque: a la interfaz (splash), al log de Tauri y al
/// diario `boot.jsonl`. El diario es lo que hace AUDITABLE la matriz de arranque
/// adverso sin necesitar un piloto de interfaz gráfica.
fn publish(app: &AppHandle, ev: BootEvent) {
    match ev.state {
        "error" => log::error!("[boot:{}] {} — {:?}", ev.stage, ev.message, ev.detail),
        "warn" => log::warn!("[boot:{}] {}", ev.stage, ev.message),
        _ => log::info!("[boot:{}] {}", ev.stage, ev.message),
    }
    journal(&ev);
    let _ = app.emit("tq://boot", ev);
}

fn journal(ev: &BootEvent) {
    let dir = logs_dir();
    if let Ok(line) = serde_json::to_string(ev) {
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(dir.join("boot.jsonl"))
        {
            let _ = writeln!(f, "{line}");
        }
        let _ = std::fs::write(dir.join("boot_state.json"), line);
    }
}

/// Arranca un diario limpio por lanzamiento y conserva el anterior: el caso más
/// útil para soporte es "arrancó mal, lo maté, volví a abrir".
fn rotate_journal() {
    let dir = logs_dir();
    let current = dir.join("boot.jsonl");
    if current.exists() {
        let _ = std::fs::rename(&current, dir.join("boot.prev.jsonl"));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Job Object de Windows (H-18): el ciclo de vida de los hijos lo garantiza el SO
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(windows)]
mod win_job {
    //! FFI mínima a kernel32 — a propósito sin dependencias nuevas.
    //!
    //! `taskkill` en `RunEvent::Exit` sólo cubre el cierre ORDENADO. Un Job
    //! Object con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` ata la vida de los
    //! sidecars a la del shell: si matan el shell desde el Administrador de
    //! Tareas, Windows cierra el handle del job y termina a los hijos. Es la
    //! diferencia entre una convención y un invariante.
    use std::ffi::c_void;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use std::sync::OnceLock;

    type Handle = *mut c_void;

    #[repr(C)]
    #[derive(Clone, Copy, Default)]
    struct IoCounters {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    #[derive(Clone, Copy, Default)]
    struct BasicLimitInformation {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    #[derive(Clone, Copy, Default)]
    struct ExtendedLimitInformation {
        basic_limit_information: BasicLimitInformation,
        io_info: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;
    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: i32 = 9;

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(
            job: Handle,
            class: i32,
            info: *const c_void,
            len: u32,
        ) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
    }

    static JOB: OnceLock<usize> = OnceLock::new();

    /// Crea (una vez) el job con "matar a los hijos al cerrar el job".
    /// Devuelve `None` si el SO no lo permite: en ese caso seguimos con
    /// `taskkill`, que cubre el cierre ordenado.
    fn job_handle() -> Option<usize> {
        let raw = *JOB.get_or_init(|| unsafe {
            let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            if job.is_null() {
                return 0;
            }
            let mut info = ExtendedLimitInformation::default();
            info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                &info as *const _ as *const c_void,
                std::mem::size_of::<ExtendedLimitInformation>() as u32,
            );
            if ok == 0 {
                CloseHandle(job);
                return 0;
            }
            job as usize
        });
        if raw == 0 {
            None
        } else {
            Some(raw)
        }
    }

    /// Mete al hijo recién creado en el job. `false` = no se pudo (Windows 7 sin
    /// jobs anidados, o política corporativa): el llamador lo registra.
    pub fn adopt(child: &Child) -> bool {
        let Some(job) = job_handle() else { return false };
        unsafe { AssignProcessToJobObject(job as Handle, child.as_raw_handle() as Handle) != 0 }
    }

    /// Cierra el job → Windows termina a todos los sidecars. Se llama en el
    /// cierre ordenado; en el desordenado lo hace el SO por nosotros.
    pub fn close() {
        if let Some(job) = JOB.get() {
            if *job != 0 {
                unsafe { CloseHandle(*job as Handle) };
            }
        }
    }

    pub fn available() -> bool {
        job_handle().is_some()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Sondas HTTP mínimas (sin dependencias nuevas: es loopback y JSON pequeño)
// ─────────────────────────────────────────────────────────────────────────────

/// Respuesta cruda de una sonda: código y cuerpo en texto.
struct Probe {
    status: u16,
    body: String,
}

/// Separa la respuesta HTTP en (código, cuerpo). Se pide con HTTP/1.0 para que
/// ni uvicorn ni Node usen `Transfer-Encoding: chunked`, y así el cuerpo llega
/// tal cual hasta el cierre de la conexión.
fn parse_http(raw: &[u8]) -> Option<Probe> {
    let split = raw.windows(4).position(|w| w == b"\r\n\r\n")?;
    let head = String::from_utf8_lossy(&raw[..split]);
    let mut first = head.lines().next()?.split_whitespace();
    let _version = first.next()?;
    let status: u16 = first.next()?.parse().ok()?;
    let body = String::from_utf8_lossy(&raw[split + 4..]).to_string();
    Some(Probe { status, body })
}

fn http_get(port: u16, path: &str) -> Result<Probe, String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream =
        TcpStream::connect_timeout(&addr, PROBE_TIMEOUT).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(PROBE_TIMEOUT)).ok();
    stream.set_write_timeout(Some(PROBE_TIMEOUT)).ok();
    let request = format!(
        "GET {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\n\
         User-Agent: TerraQuantum-Shell\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|e| e.to_string())?;
    let mut raw = Vec::new();
    // Con HTTP/1.0 el servidor cierra al terminar → read_to_end termina solo.
    stream.read_to_end(&mut raw).map_err(|e| e.to_string())?;
    parse_http(&raw).ok_or_else(|| "respuesta HTTP ilegible".to_string())
}

/// Veredicto de identidad de un puerto (H-19).
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum Identity {
    /// Responde y lleva NUESTRO token: es nuestro sidecar.
    Ours,
    /// Responde, pero es otro TerraQuantum (instancia previa / zombi).
    OtherTerraQuantum,
    /// Responde, pero no es TerraQuantum.
    Foreign,
    /// No responde todavía.
    Silent,
}

/// Clasifica una respuesta. Función pura: es la que se testea.
fn classify(probe: Option<&Probe>, token: &str) -> Identity {
    let Some(probe) = probe else { return Identity::Silent };
    if probe.status != 200 {
        return Identity::Foreign;
    }
    if probe.body.contains(token) {
        Identity::Ours
    } else if probe.body.contains("terraquantum-backend") {
        Identity::OtherTerraQuantum
    } else {
        Identity::Foreign
    }
}

fn identity_of(port: u16, path: &str, token: &str) -> Identity {
    match http_get(port, path) {
        Ok(probe) => classify(Some(&probe), token),
        Err(_) => Identity::Silent,
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Puertos: se decide ANTES de spawnear
// ─────────────────────────────────────────────────────────────────────────────

fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// Primer puerto libre a partir del preferido. `None` = tramo agotado.
///
/// La decisión se separa del sistema operativo a propósito: así se puede probar
/// sin depender de qué puertos estén libres en la máquina donde corren los
/// tests. Un test que sólo pasa "casi siempre" es peor que no tenerlo, porque
/// enseña a ignorar la suite.
fn choose_port_where<F: Fn(u16) -> bool>(preferred: u16, span: u16, is_free: F) -> Option<u16> {
    (0..span).find_map(|offset| {
        let candidate = preferred.checked_add(offset)?;
        is_free(candidate).then_some(candidate)
    })
}

fn choose_port(preferred: u16, span: u16) -> Option<u16> {
    choose_port_where(preferred, span, port_is_free)
}

/// Quién ocupa el puerto, en español, para que el aviso sea accionable.
fn describe_occupant(port: u16, path: &str, token: &str) -> String {
    match identity_of(port, path, token) {
        Identity::Ours | Identity::OtherTerraQuantum => {
            "lo ocupa otra instancia de TerraQuantum que sigue viva".to_string()
        }
        Identity::Foreign => "lo ocupa otra aplicación".to_string(),
        Identity::Silent => "está tomado por un proceso que no responde".to_string(),
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Arranque de sidecars
// ─────────────────────────────────────────────────────────────────────────────

struct BootError {
    code: &'static str,
    message: String,
    detail: Option<String>,
    hint: String,
}

impl BootError {
    fn new(code: &'static str, message: impl Into<String>, hint: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            detail: None,
            hint: hint.into(),
        }
    }
    fn with_detail(mut self, detail: impl Into<String>) -> Self {
        self.detail = Some(detail.into());
        self
    }
}

fn spawn_hidden(mut cmd: Command, log_name: &str) -> std::io::Result<Child> {
    // Redirigir a archivos de log (útil para el canal de diagnóstico y para
    // depurar el arranque de los sidecars sin ventana de consola).
    let log_path = logs_dir().join(log_name);
    let out = std::fs::File::create(&log_path)?;
    let err = out.try_clone()?;
    cmd.stdout(Stdio::from(out))
        .stderr(Stdio::from(err))
        .stdin(Stdio::null());
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd.spawn()
}

/// Mete el hijo en el Job Object y lo guarda en el estado.
fn register(app: &AppHandle, key: &'static str, label: &'static str, child: Child) {
    #[cfg(windows)]
    {
        if !win_job::adopt(&child) {
            log::warn!("no se pudo asignar {key} al Job Object; queda el cierre por taskkill");
        }
    }
    if let Some(state) = app.try_state::<ShellState>() {
        if let Ok(mut shell) = state.0.lock() {
            shell.sidecars.push(Sidecar { key, label, child });
        }
    }
}

/// ¿Murió el sidecar mientras esperábamos? Devuelve el código de salida.
fn exited_with(app: &AppHandle, key: &str) -> Option<Option<i32>> {
    let state = app.try_state::<ShellState>()?;
    let mut shell = state.0.lock().ok()?;
    let sidecar = shell.sidecars.iter_mut().find(|s| s.key == key)?;
    match sidecar.child.try_wait() {
        Ok(Some(status)) => Some(status.code()),
        _ => None,
    }
}

/// Espera a que el sidecar sea NUESTRO en ese puerto, vigilando además que no se
/// haya muerto por el camino. Es la diferencia entre "esperar para siempre" y
/// "decir qué pasó" (H-17 + H-19).
#[allow(clippy::too_many_arguments)]
fn wait_until_ours(
    app: &AppHandle,
    stage: &'static str,
    key: &'static str,
    label: &'static str,
    port: u16,
    path: &str,
    timeout: Duration,
    dead_code: &'static str,
    timeout_code: &'static str,
) -> Result<(), BootError> {
    let token = instance_token();
    let deadline = Instant::now() + timeout;
    let mut announced = false;
    // Si alguien AJENO contesta en nuestro puerto, no se aborta al primer
    // intento: durante el arranque la respuesta puede ser transitoria (el proxy
    // del frontend contesta antes de tener enlazado el backend). Se anota y se
    // usa para dar el diagnóstico correcto cuando el intento termine — que será
    // enseguida, porque un puerto realmente robado hace morir al sidecar.
    let mut saw_stranger = false;

    let hijacked = |port: u16, label: &str| {
        BootError::new(
            "PORT_HIJACKED",
            format!("El puerto {port} responde, pero no es el proceso que TerraQuantum lanzó."),
            format!(
                "Cierra otras instancias de TerraQuantum (o la aplicación que use ese puerto) \
                 y pulsa Reintentar. {label} no pudo tomar el puerto."
            ),
        )
    };

    loop {
        match identity_of(port, path, token) {
            Identity::Ours => return Ok(()),
            Identity::OtherTerraQuantum | Identity::Foreign => saw_stranger = true,
            Identity::Silent => {}
        }

        if let Some(code) = exited_with(app, key) {
            if saw_stranger {
                return Err(hijacked(port, label));
            }
            let detail = match code {
                Some(c) => format!("código de salida {c}"),
                None => "terminado por el sistema".to_string(),
            };
            return Err(BootError::new(
                dead_code,
                format!("{label} se cerró solo durante el arranque."),
                "Abre los registros: la última línea de su log dice por qué. \
                 La causa más común es un antivirus que puso el ejecutable en cuarentena.",
            )
            .with_detail(detail));
        }

        if Instant::now() >= deadline {
            if saw_stranger {
                return Err(hijacked(port, label));
            }
            return Err(BootError::new(
                timeout_code,
                format!(
                    "{label} no respondió en {} segundos.",
                    timeout.as_secs()
                ),
                "Pulsa Reintentar. Si vuelve a fallar, abre los registros y \
                 comprueba que el antivirus no esté bloqueando la aplicación.",
            ));
        }

        if !announced {
            announced = true;
            publish(
                app,
                event(
                    stage,
                    "waiting",
                    // La etiqueta ya viene con mayúscula porque encabeza los
                    // mensajes de error; aquí se usa como sujeto, no tras
                    // preposición ("Esperando a El motor…" sonaría a máquina).
                    format!("{label}: esperando respuesta en el puerto {port}…"),
                ),
            );
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

fn start_backend(app: &AppHandle) -> Result<u16, BootError> {
    let token = instance_token();
    let exe = resource(app, "resources/backend/terraquantum-backend.exe").map_err(|e| {
        BootError::new(
            "BACKEND_MISSING",
            "No se encontró el motor de cálculo dentro de la instalación.",
            "Reinstala TerraQuantum. Si tienes antivirus corporativo, revisa la \
             cuarentena: suele confiscar ejecutables grandes sin firma.",
        )
        .with_detail(e)
    })?;
    if !exe.exists() {
        return Err(BootError::new(
            "BACKEND_MISSING",
            "No se encontró el motor de cálculo dentro de la instalación.",
            "Reinstala TerraQuantum y revisa la cuarentena del antivirus.",
        )
        .with_detail(format!("ruta esperada: {}", exe.display())));
    }

    let port = choose_port(BACKEND_PORT, PORT_SPAN).ok_or_else(|| {
        BootError::new(
            "PORTS_EXHAUSTED",
            format!(
                "No hay ningún puerto libre entre {BACKEND_PORT} y {}.",
                BACKEND_PORT + PORT_SPAN - 1
            ),
            "Cierra otras aplicaciones que usen esos puertos (u otra copia de \
             TerraQuantum) y pulsa Reintentar.",
        )
    })?;
    if port != BACKEND_PORT {
        let mut ev = event(
            "backend",
            "warn",
            format!(
                "El puerto {BACKEND_PORT} no estaba libre ({}); el motor usará el {port}.",
                describe_occupant(BACKEND_PORT, "/health", token)
            ),
        );
        ev.code = Some("BACKEND_PORT_FALLBACK");
        publish(app, ev);
    }

    let mut cmd = Command::new(&exe);
    cmd.env("TERRAQUANTUM_DATA_DIR", data_dir())
        .env("TERRAQUANTUM_HOST", "127.0.0.1")
        .env("TERRAQUANTUM_PORT", port.to_string())
        .env("TERRAQUANTUM_INSTANCE_TOKEN", token);
    if let Some(dir) = exe.parent() {
        cmd.current_dir(dir);
    }

    let child = spawn_hidden(cmd, "backend.log").map_err(|e| {
        BootError::new(
            "BACKEND_SPAWN_FAILED",
            "Windows no dejó iniciar el motor de cálculo.",
            "Suele ser el antivirus o una carpeta de instalación sin permisos. \
             Reinstala o añade una excepción para TerraQuantum.",
        )
        .with_detail(e.to_string())
    })?;
    register(app, "backend", "El motor de cálculo", child);

    wait_until_ours(
        app,
        "backend",
        "backend",
        "El motor de cálculo",
        port,
        "/health",
        BACKEND_READY_TIMEOUT,
        "BACKEND_DEAD",
        "BACKEND_TIMEOUT",
    )?;

    Ok(port)
}

fn start_frontend(app: &AppHandle, backend_port: u16) -> Result<u16, BootError> {
    let node = resource(app, "resources/node/node.exe").map_err(|e| {
        BootError::new(
            "NODE_MISSING",
            "No se encontró el motor de la interfaz dentro de la instalación.",
            "Reinstala TerraQuantum y revisa la cuarentena del antivirus.",
        )
        .with_detail(e)
    })?;
    let dir = resource(app, "resources/frontend").map_err(|e| {
        BootError::new(
            "FRONTEND_MISSING",
            "Faltan los archivos de la interfaz dentro de la instalación.",
            "Reinstala TerraQuantum.",
        )
        .with_detail(e)
    })?;
    if !node.exists() || !dir.join("server.js").exists() {
        return Err(BootError::new(
            "FRONTEND_MISSING",
            "Faltan los archivos de la interfaz dentro de la instalación.",
            "Reinstala TerraQuantum y revisa la cuarentena del antivirus.",
        )
        .with_detail(format!("ruta esperada: {}", dir.join("server.js").display())));
    }

    let token = instance_token();
    let port = choose_port(FRONTEND_PORT, PORT_SPAN).ok_or_else(|| {
        BootError::new(
            "PORTS_EXHAUSTED",
            format!(
                "No hay ningún puerto libre entre {FRONTEND_PORT} y {}.",
                FRONTEND_PORT + PORT_SPAN - 1
            ),
            "Cierra otras aplicaciones que usen esos puertos y pulsa Reintentar.",
        )
    })?;
    if port != FRONTEND_PORT {
        let mut ev = event(
            "frontend",
            "warn",
            format!(
                "El puerto {FRONTEND_PORT} no estaba libre ({}); la interfaz usará el {port}.",
                describe_occupant(FRONTEND_PORT, "/api/backend-health", token)
            ),
        );
        ev.code = Some("FRONTEND_PORT_FALLBACK");
        publish(app, ev);
    }

    // Se pasa "server.js" RELATIVO (cwd = dir del frontend): la ruta ABSOLUTA que
    // devuelve el resolvedor de recursos puede venir con prefijo verbatim
    // (\\?\C:\...) y la resolución de módulo de Node la mutila a 'C:' (EISDIR).
    let mut cmd = Command::new(&node);
    cmd.arg("server.js")
        .current_dir(&dir)
        .env("PORT", port.to_string())
        .env("HOSTNAME", "127.0.0.1")
        .env("NODE_ENV", "production")
        .env(
            "TERRAQUANTUM_BACKEND_URL",
            format!("http://127.0.0.1:{backend_port}"),
        );

    let child = spawn_hidden(cmd, "frontend.log").map_err(|e| {
        BootError::new(
            "FRONTEND_SPAWN_FAILED",
            "Windows no dejó iniciar la interfaz.",
            "Suele ser el antivirus. Añade una excepción para TerraQuantum y reintenta.",
        )
        .with_detail(e.to_string())
    })?;
    register(app, "frontend", "La interfaz", child);

    // La sonda va al PROXY del frontend, no a su portada: comprobar que responde
    // HTML sólo diría que hay un servidor web; esto demuestra que es NUESTRO
    // servidor Y que está emparejado con NUESTRO backend (H-19).
    wait_until_ours(
        app,
        "frontend",
        "frontend",
        "La interfaz",
        port,
        "/api/backend-health",
        FRONTEND_READY_TIMEOUT,
        "FRONTEND_DEAD",
        "FRONTEND_TIMEOUT",
    )?;

    Ok(port)
}

fn stop_sidecars(app: &AppHandle) {
    if let Some(state) = app.try_state::<ShellState>() {
        if let Ok(mut shell) = state.0.lock() {
            for sidecar in shell.sidecars.iter_mut() {
                let pid = sidecar.child.id();
                log::info!("deteniendo {} ({}, pid {pid})", sidecar.label, sidecar.key);
                kill_pid_tree(pid);
                let _ = sidecar.child.kill();
                let _ = sidecar.child.wait();
            }
            shell.sidecars.clear();
            shell.ready_url = None;
        }
    }
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

fn is_booting(app: &AppHandle) -> bool {
    app.try_state::<ShellState>()
        .and_then(|state| state.0.lock().ok().map(|shell| shell.booting))
        .unwrap_or(false)
}

/// Secuencia completa. Se ejecuta en un hilo propio para no bloquear la interfaz.
fn boot(app: AppHandle) {
    {
        // Un solo arranque a la vez: el botón Reintentar no debe poder duplicar
        // sidecares.
        let Some(state) = app.try_state::<ShellState>() else { return };
        let Ok(mut shell) = state.0.lock() else { return };
        if shell.booting {
            return;
        }
        shell.booting = true;
    }

    publish(
        &app,
        event("backend", "start", "Iniciando el motor de cálculo…"),
    );

    let result = start_backend(&app).and_then(|backend_port| {
        publish(
            &app,
            event("frontend", "start", "Iniciando la interfaz…"),
        );
        start_frontend(&app, backend_port)
    });

    match result {
        Ok(frontend_port) => {
            let url = format!("http://localhost:{frontend_port}");
            let mut ev = event("ready", "ok", "Listo. Abriendo TerraQuantum…");
            ev.url = Some(url.clone());
            publish(&app, ev);

            if let Some(state) = app.try_state::<ShellState>() {
                if let Ok(mut shell) = state.0.lock() {
                    shell.ready_url = Some(url.clone());
                    shell.booting = false;
                }
            }
            if let Some(win) = app.get_webview_window("main") {
                if let Ok(parsed) = tauri::Url::parse(&url) {
                    let _ = win.navigate(parsed);
                }
            }
        }
        Err(err) => {
            // Un arranque a medias deja procesos que ocuparían el puerto en el
            // siguiente intento: se limpian ANTES de ofrecer Reintentar.
            stop_sidecars(&app);
            let mut ev = event("error", "error", err.message);
            ev.code = Some(err.code);
            ev.detail = err.detail;
            ev.hint = Some(err.hint);
            publish(&app, ev);
            if let Some(state) = app.try_state::<ShellState>() {
                if let Ok(mut shell) = state.0.lock() {
                    shell.booting = false;
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Acciones de la interfaz de arranque y del menú
// ─────────────────────────────────────────────────────────────────────────────

/// Abre una carpeta en el explorador del sistema.
/// OJO: el explorador NO se mete en el Job Object — si no, cerrar TerraQuantum
/// cerraría también la ventana de carpetas del usuario.
fn open_folder(dir: PathBuf) {
    std::fs::create_dir_all(&dir).ok();
    #[cfg(windows)]
    let program = "explorer";
    #[cfg(target_os = "macos")]
    let program = "open";
    #[cfg(all(unix, not(target_os = "macos")))]
    let program = "xdg-open";
    let _ = Command::new(program).arg(dir.as_os_str()).spawn();
}

fn open_logs() {
    open_folder(logs_dir());
}

/// Ventana pequeña reutilizable para estados que ocurren DESPUÉS del arranque
/// (hoy: el resultado de buscar actualizaciones).
fn status_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    if let Some(win) = app.get_webview_window("estado") {
        let _ = win.set_focus();
        return Some(win);
    }
    WebviewWindowBuilder::new(app, "estado", WebviewUrl::App("index.html".into()))
        .title("TerraQuantum — Estado")
        .inner_size(560.0, 380.0)
        .resizable(true)
        .center()
        .build()
        .ok()
}

#[derive(Clone, Serialize)]
struct UpdateEvent {
    state: &'static str,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail: Option<String>,
}

/// H-20 — el updater deja de ser un mecanismo de papel: hay un camino de
/// consumo. Es MANUAL a propósito; un producto que promete que los datos no
/// salen de la máquina no debe llamar a internet sin que se lo pidan.
fn check_updates(app: &AppHandle) {
    let handle = app.clone();
    let _ = status_window(app);

    tauri::async_runtime::spawn(async move {
        use tauri_plugin_updater::UpdaterExt;
        // La ventana acaba de crearse: si se emite antes de que su script
        // registre el oyente, el aviso se pierde y el usuario ve una ventana en
        // blanco. Medio segundo es suficiente y no compite con la red.
        std::thread::sleep(Duration::from_millis(500));
        let _ = handle.emit(
            "tq://update",
            UpdateEvent {
                state: "checking",
                message: "Consultando si hay una versión nueva…".to_string(),
                detail: Some(
                    "Es la única función de esta ventana que usa internet. \
                     Tus datos no viajan."
                        .to_string(),
                ),
            },
        );
        let payload = match handle.updater() {
            Ok(updater) => match updater.check().await {
                Ok(Some(update)) => UpdateEvent {
                    state: "available",
                    message: format!("Hay una versión nueva: {}.", update.version),
                    detail: Some(format!(
                        "Tienes la {}. Descárgala desde la página de versiones \
                         e instálala; tus datos en %APPDATA%\\TerraQuantum se conservan.",
                        update.current_version
                    )),
                },
                Ok(None) => UpdateEvent {
                    state: "current",
                    message: "Ya tienes la última versión.".to_string(),
                    detail: None,
                },
                Err(e) => UpdateEvent {
                    state: "error",
                    message: "No se pudo comprobar si hay actualizaciones.".to_string(),
                    detail: Some(format!(
                        "{e}. Si no tienes internet es lo esperable: TerraQuantum \
                         funciona igual sin conexión."
                    )),
                },
            },
            Err(e) => UpdateEvent {
                state: "error",
                message: "El comprobador de actualizaciones no está disponible.".to_string(),
                detail: Some(e.to_string()),
            },
        };
        let _ = handle.emit("tq://update", payload);
    });
}

fn build_menu(app: &AppHandle) -> tauri::Result<()> {
    let logs = MenuItemBuilder::with_id("tq_logs", "Ver registros de arranque").build(app)?;
    let updates = MenuItemBuilder::with_id("tq_updates", "Buscar actualizaciones…").build(app)?;
    let data = MenuItemBuilder::with_id("tq_data", "Abrir carpeta de datos").build(app)?;
    let help = SubmenuBuilder::new(app, "Ayuda")
        .items(&[&logs, &data, &updates])
        .build()?;
    let menu = MenuBuilder::new(app).items(&[&help]).build()?;
    app.set_menu(menu)?;
    Ok(())
}

// ─────────────────────────────────────────────────────────────────────────────
// Punto de entrada
// ─────────────────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(ShellState(Mutex::new(Shell::default())))
        .setup(|app| {
            boot_started();
            rotate_journal();
            #[cfg(windows)]
            if !win_job::available() {
                log::warn!(
                    "sin Job Object: el cierre forzado dependerá de taskkill (H-18 degradado)"
                );
            }

            let handle = app.handle().clone();
            if let Err(e) = build_menu(&handle) {
                log::warn!("no se pudo construir el menú: {e}");
            }

            // Acciones del splash: [Reintentar] [Ver registros] [Cerrar].
            let actions = handle.clone();
            handle.listen("tq://action", move |ev| {
                let action = serde_json::from_str::<serde_json::Value>(ev.payload())
                    .ok()
                    .and_then(|v| v.get("action").and_then(|a| a.as_str().map(String::from)))
                    .unwrap_or_default();
                match action.as_str() {
                    "retry" => {
                        // Se comprueba ANTES de matar nada: si hubiera un arranque
                        // en curso, limpiar los sidecars lo mataría y el usuario
                        // vería un error en vez del reintento que pidió.
                        if is_booting(&actions) {
                            log::info!("reintento ignorado: ya hay un arranque en curso");
                        } else {
                            let app = actions.clone();
                            std::thread::spawn(move || {
                                stop_sidecars(&app);
                                boot(app);
                            });
                        }
                    }
                    "logs" => open_logs(),
                    "updates" => check_updates(&actions),
                    "quit" => actions.exit(0),
                    other => log::warn!("acción desconocida del splash: {other}"),
                }
            });

            let menu_handle = handle.clone();
            handle.on_menu_event(move |_app, event| match event.id().as_ref() {
                "tq_logs" => open_logs(),
                "tq_updates" => check_updates(&menu_handle),
                "tq_data" => open_folder(data_dir()),
                _ => {}
            });

            let booter = handle.clone();
            std::thread::spawn(move || boot(booter));

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la app Tauri")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                stop_sidecars(app_handle);
                #[cfg(windows)]
                win_job::close();
            }
        });
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests de las piezas que deciden (el resto lo cubre la matriz de arranque
// adverso, `scripts/f2_gate_boot_matrix.ps1`).
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn probe(status: u16, body: &str) -> Probe {
        Probe {
            status,
            body: body.to_string(),
        }
    }

    #[test]
    fn parse_http_extracts_status_and_body() {
        let raw = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\"}";
        let parsed = parse_http(raw).expect("debe parsear");
        assert_eq!(parsed.status, 200);
        assert_eq!(parsed.body, "{\"status\":\"ok\"}");
    }

    #[test]
    fn parse_http_rejects_garbage() {
        assert!(parse_http(b"no soy http").is_none());
    }

    #[test]
    fn identity_requires_our_token_not_just_an_answer() {
        // El corazón de H-19: responder NO es ser el nuestro.
        let token = "tq-abc-123";
        assert_eq!(classify(None, token), Identity::Silent);
        assert_eq!(
            classify(Some(&probe(200, r#"{"service":"terraquantum-backend"}"#)), token),
            Identity::OtherTerraQuantum,
            "un zombi de TerraQuantum responde igual de bien: sin token no vale"
        );
        assert_eq!(
            classify(Some(&probe(200, "<html>otra app</html>")), token),
            Identity::Foreign
        );
        assert_eq!(
            classify(
                Some(&probe(
                    200,
                    r#"{"service":"terraquantum-backend","instance_token":"tq-abc-123"}"#
                )),
                token
            ),
            Identity::Ours
        );
    }

    #[test]
    fn identity_rejects_non_200_even_with_token() {
        let token = "tq-abc-123";
        assert_eq!(
            classify(Some(&probe(500, "tq-abc-123")), token),
            Identity::Foreign
        );
    }

    #[test]
    fn frontend_proxy_answer_proves_the_pairing() {
        // /api/backend-health envuelve la respuesta del backend: si el token
        // aparece ahí, el sidecar Node está hablando con NUESTRO backend.
        let token = "tq-9f-1";
        let body = r#"{"online":true,"data":{"service":"terraquantum-backend","instance_token":"tq-9f-1"}}"#;
        assert_eq!(classify(Some(&probe(200, body)), token), Identity::Ours);

        let paired_to_someone_else =
            r#"{"online":true,"data":{"service":"terraquantum-backend","instance_token":"tq-otro"}}"#;
        assert_eq!(
            classify(Some(&probe(200, paired_to_someone_else)), token),
            Identity::OtherTerraQuantum
        );
    }

    #[test]
    fn choose_port_prefers_the_first_free_one() {
        // Lógica pura: no depende de qué puertos tenga libres esta máquina.
        assert_eq!(choose_port_where(8010, 5, |_| true), Some(8010));
        assert_eq!(choose_port_where(8010, 5, |p| p >= 8012), Some(8012));
        assert_eq!(choose_port_where(8010, 5, |_| false), None, "tramo agotado");
        assert_eq!(
            choose_port_where(8010, 3, |p| p >= 8013),
            None,
            "no puede salirse del tramo declarado"
        );
    }

    #[test]
    fn choose_port_never_returns_a_socket_that_is_taken() {
        // Con un socket REAL ocupado: puede no haber alternativa en el tramo
        // (la máquina decide), pero lo que nunca puede pasar es que devuelva el
        // puerto ocupado.
        let busy = TcpListener::bind(("127.0.0.1", 0)).expect("bind");
        let port = busy.local_addr().unwrap().port();
        assert_ne!(choose_port(port, 6), Some(port));
    }

    #[test]
    fn every_boot_error_speaks_spanish_and_says_what_to_do() {
        // H-17: un error sin salida es tan inútil como un splash infinito.
        let errors = [
            BootError::new("BACKEND_MISSING", "No se encontró el motor.", "Reinstala."),
            BootError::new("BACKEND_DEAD", "El motor se cerró solo.", "Abre los registros."),
        ];
        for err in errors {
            assert!(!err.message.trim().is_empty());
            assert!(!err.hint.trim().is_empty(), "{} sin acción", err.code);
            assert!(err.message.ends_with('.'), "{} sin puntuación", err.code);
        }
    }

    #[test]
    fn boot_event_serialises_what_the_gate_reads() {
        let mut ev = event("error", "error", "El motor de cálculo se cerró solo.");
        ev.code = Some("BACKEND_DEAD");
        ev.hint = Some("Abre los registros.".into());
        let json = serde_json::to_string(&ev).expect("serializa");
        assert!(json.contains("\"stage\":\"error\""));
        assert!(json.contains("\"code\":\"BACKEND_DEAD\""));
        assert!(json.contains("\"logs_dir\""));
    }
}
