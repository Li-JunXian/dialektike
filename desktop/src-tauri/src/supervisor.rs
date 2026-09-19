use std::{
    ffi::OsString,
    io::{self, BufRead, BufReader, Read, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex, MutexGuard,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
#[cfg(not(debug_assertions))]
use tauri::Manager;
use tauri::{AppHandle, Emitter};

use crate::protocol::{
    CommandEnvelope, EventEnvelope, MAX_JSONL_CHUNKS, MAX_REASSEMBLED_JSON_BYTES,
    ORDINARY_EVENT_CHANNEL, PERMISSION_EVENT_CHANNEL, TRANSPORT_CHUNK_EVENT,
};

// A clean shutdown may need to cancel provider work, finish a topic snapshot,
// flush the final protocol event, and only then exit. 750 ms was short enough
// to kill the sidecar while those owner-only records were still being saved.
// Keep the close operation bounded, but give the child a realistic window to
// prove that it exited before force is used as the last resort.
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(15);
const PROCESS_POLL_INTERVAL: Duration = Duration::from_millis(50);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ShutdownDisposition {
    Exited,
    Forced,
}

#[derive(Debug, Clone, Serialize)]
pub struct SupervisorStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub generation: Option<u64>,
}

#[derive(Clone)]
pub struct Supervisor {
    inner: Arc<Mutex<SupervisorInner>>,
    next_generation: Arc<AtomicU64>,
    next_request: Arc<AtomicU64>,
}

struct SupervisorInner {
    child: Option<ChildHandle>,
    initialized: bool,
}

#[derive(Clone)]
struct ChildHandle {
    generation: u64,
    pid: u32,
    child: Arc<Mutex<Child>>,
    stdin: Arc<Mutex<ChildStdin>>,
}

struct LaunchSpec {
    program: PathBuf,
    args: Vec<OsString>,
    working_directory: PathBuf,
}

struct ChunkTransfer {
    transfer_id: String,
    total: usize,
    encoded_length: usize,
    next_index: usize,
    data: String,
}

#[derive(Default)]
struct ChunkAssembler {
    active: Option<ChunkTransfer>,
}

impl ChunkAssembler {
    fn accept(&mut self, envelope: EventEnvelope) -> Result<Option<EventEnvelope>, String> {
        if envelope.event != TRANSPORT_CHUNK_EVENT {
            if self.active.is_some() {
                return Err("sidecar transport chunk sequence was interrupted".to_owned());
            }
            return Ok(Some(envelope));
        }

        let payload = envelope
            .payload
            .as_object()
            .ok_or_else(|| "transport chunk payload must be an object".to_owned())?;
        let transfer_id = payload
            .get("transfer_id")
            .and_then(Value::as_str)
            .filter(|value| {
                value.len() == 64
                    && value
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            .ok_or_else(|| "transport chunk has an invalid transfer id".to_owned())?;
        let index = payload
            .get("index")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| "transport chunk has an invalid index".to_owned())?;
        let total = payload
            .get("total")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .filter(|value| *value > 0 && *value <= MAX_JSONL_CHUNKS)
            .ok_or_else(|| "transport chunk has an invalid total".to_owned())?;
        let encoded_length = payload
            .get("encoded_length")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .filter(|value| *value > 0 && *value <= MAX_REASSEMBLED_JSON_BYTES)
            .ok_or_else(|| "transport chunk has an invalid encoded length".to_owned())?;
        let data = payload
            .get("data")
            .and_then(Value::as_str)
            .ok_or_else(|| "transport chunk data must be text".to_owned())?;
        if index >= total {
            return Err("transport chunk index exceeds its total".to_owned());
        }

        if index == 0 {
            if self.active.is_some() {
                return Err("sidecar started an overlapping chunk transfer".to_owned());
            }
            self.active = Some(ChunkTransfer {
                transfer_id: transfer_id.to_owned(),
                total,
                encoded_length,
                next_index: 0,
                data: String::with_capacity(encoded_length),
            });
        }
        let transfer = self
            .active
            .as_mut()
            .ok_or_else(|| "transport chunk arrived without a start".to_owned())?;
        if transfer.transfer_id != transfer_id
            || transfer.total != total
            || transfer.encoded_length != encoded_length
            || transfer.next_index != index
        {
            return Err("transport chunk metadata or ordering changed".to_owned());
        }
        if transfer.data.len().saturating_add(data.len()) > encoded_length {
            return Err("transport chunks exceed their declared length".to_owned());
        }
        transfer.data.push_str(data);
        transfer.next_index += 1;
        if transfer.next_index < transfer.total {
            return Ok(None);
        }

        let completed = self.active.take().expect("active transfer checked above");
        if completed.data.len() != completed.encoded_length {
            return Err("transport chunks do not match their declared length".to_owned());
        }
        let actual_transfer_id = format!("{:x}", Sha256::digest(completed.data.as_bytes()));
        if actual_transfer_id != completed.transfer_id {
            return Err("transport chunks failed their SHA-256 integrity check".to_owned());
        }
        let record = completed.data.trim_end_matches(['\r', '\n']);
        let reconstructed = EventEnvelope::parse_reassembled(record)?;
        if reconstructed.event == TRANSPORT_CHUNK_EVENT {
            return Err("nested transport chunk envelope is forbidden".to_owned());
        }
        Ok(Some(reconstructed))
    }
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(SupervisorInner {
                child: None,
                initialized: false,
            })),
            next_generation: Arc::new(AtomicU64::new(1)),
            next_request: Arc::new(AtomicU64::new(1)),
        }
    }

    pub fn start(&self, app: &AppHandle) -> Result<SupervisorStatus, String> {
        let mut inner = self.lock_inner()?;
        if let Some(handle) = &inner.child {
            return Ok(status_for(handle));
        }

        let spec = resolve_launch_spec(app)?;
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(&spec.working_directory)
            .env("PYTHONUNBUFFERED", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command.spawn().map_err(|error| {
            format!(
                "failed to start the fixed Dialektikḗ sidecar at {}: {error}",
                spec.program.display()
            )
        })?;
        let pid = child.id();
        let Some(stdin) = child.stdin.take() else {
            let _ = child.kill();
            return Err("sidecar stdin was not piped".to_owned());
        };
        let Some(stdout) = child.stdout.take() else {
            let _ = child.kill();
            return Err("sidecar stdout was not piped".to_owned());
        };
        let Some(stderr) = child.stderr.take() else {
            let _ = child.kill();
            return Err("sidecar stderr was not piped".to_owned());
        };
        let generation = self.next_generation.fetch_add(1, Ordering::Relaxed);
        let handle = ChildHandle {
            generation,
            pid,
            child: Arc::new(Mutex::new(child)),
            stdin: Arc::new(Mutex::new(stdin)),
        };
        inner.child = Some(handle.clone());
        inner.initialized = false;
        drop(inner);

        if let Err(error) = emit_ordinary(
            app,
            "supervisor.status",
            json!({"state": "running", "pid": pid, "generation": generation}),
        ) {
            let _ = self.kill_generation(generation);
            self.clear_generation(generation);
            return Err(error);
        }

        let stdout_supervisor = self.clone();
        let stdout_app = app.clone();
        if let Err(error) = thread::Builder::new()
            .name("dialektike-sidecar-stdout".to_owned())
            .spawn(move || {
                read_stdout(
                    stdout_app,
                    stdout_supervisor,
                    generation,
                    BufReader::new(stdout),
                );
            })
        {
            let _ = self.kill_generation(generation);
            self.clear_generation(generation);
            return Err(format!("failed to create sidecar stdout reader: {error}"));
        }

        let stderr_app = app.clone();
        if let Err(error) = thread::Builder::new()
            .name("dialektike-sidecar-stderr".to_owned())
            .spawn(move || read_stderr(stderr_app, BufReader::new(stderr)))
        {
            let _ = self.kill_generation(generation);
            self.clear_generation(generation);
            return Err(format!("failed to create sidecar stderr reader: {error}"));
        }

        let monitor_supervisor = self.clone();
        let monitor_app = app.clone();
        let monitored_child = handle.child.clone();
        if let Err(error) = thread::Builder::new()
            .name("dialektike-sidecar-monitor".to_owned())
            .spawn(move || {
                monitor_process(
                    monitor_app,
                    monitor_supervisor,
                    generation,
                    pid,
                    monitored_child,
                );
            })
        {
            let _ = self.kill_generation(generation);
            self.clear_generation(generation);
            return Err(format!("failed to create sidecar monitor: {error}"));
        }

        Ok(status_for(&handle))
    }

    pub fn status(&self) -> Result<SupervisorStatus, String> {
        let inner = self.lock_inner()?;
        Ok(inner
            .child
            .as_ref()
            .map(status_for)
            .unwrap_or(SupervisorStatus {
                running: false,
                pid: None,
                generation: None,
            }))
    }

    pub fn ensure_initialized(&self, app: &AppHandle) -> Result<SupervisorStatus, String> {
        let status = self.start(app)?;
        let claimed = {
            let mut inner = self.lock_inner()?;
            if inner.initialized {
                false
            } else {
                inner.initialized = true;
                true
            }
        };
        if claimed {
            let command = CommandEnvelope::new(
                self.next_request_id(),
                "initialize",
                json!({
                    "client": "desktop",
                    "client_version": env!("CARGO_PKG_VERSION")
                }),
            );
            if let Err(error) = self.send(&command) {
                if let Ok(mut inner) = self.inner.lock() {
                    inner.initialized = false;
                }
                return Err(error);
            }
        }
        Ok(status)
    }

    pub fn send_command(&self, command: &'static str, payload: Value) -> Result<String, String> {
        let id = self.next_request_id();
        self.send(&CommandEnvelope::new(id.clone(), command, payload))?;
        Ok(id)
    }

    pub fn shutdown(&self) -> Result<(), String> {
        let handle = {
            let inner = self.lock_inner()?;
            inner.child.clone()
        };
        let Some(handle) = handle else {
            return Ok(());
        };
        let envelope = CommandEnvelope::new(self.next_request_id(), "shutdown", json!({}));
        let _ = self.send(&envelope);

        wait_for_exit_or_kill(&handle.child, SHUTDOWN_TIMEOUT, PROCESS_POLL_INTERVAL)?;
        self.clear_generation(handle.generation);
        Ok(())
    }

    fn send(&self, envelope: &CommandEnvelope) -> Result<(), String> {
        let line = serde_json::to_string(envelope)
            .map_err(|error| format!("failed to encode sidecar command: {error}"))?;
        let stdin = {
            let inner = self.lock_inner()?;
            inner
                .child
                .as_ref()
                .map(|handle| handle.stdin.clone())
                .ok_or_else(|| "the Dialektikḗ sidecar is not running".to_owned())?
        };
        let mut writer = lock(&stdin, "sidecar stdin")?;
        writer
            .write_all(line.as_bytes())
            .and_then(|_| writer.write_all(b"\n"))
            .and_then(|_| writer.flush())
            .map_err(|error| format!("failed to send a sidecar command: {error}"))
    }

    fn kill_generation(&self, generation: u64) -> Result<(), String> {
        let child = {
            let inner = self.lock_inner()?;
            inner
                .child
                .as_ref()
                .filter(|handle| handle.generation == generation)
                .map(|handle| handle.child.clone())
        };
        if let Some(child) = child {
            lock(&child, "sidecar process")?
                .kill()
                .map_err(|error| format!("failed to stop the sidecar: {error}"))?;
        }
        Ok(())
    }

    fn clear_generation(&self, generation: u64) {
        if let Ok(mut inner) = self.inner.lock() {
            if inner
                .child
                .as_ref()
                .is_some_and(|handle| handle.generation == generation)
            {
                inner.child = None;
                inner.initialized = false;
            }
        }
    }

    fn next_request_id(&self) -> String {
        let sequence = self.next_request.fetch_add(1, Ordering::Relaxed);
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        format!("desktop-{millis}-{sequence}")
    }

    fn lock_inner(&self) -> Result<MutexGuard<'_, SupervisorInner>, String> {
        self.inner
            .lock()
            .map_err(|_| "sidecar supervisor state was poisoned".to_owned())
    }
}

fn wait_for_exit_or_kill(
    child: &Arc<Mutex<Child>>,
    timeout: Duration,
    poll_interval: Duration,
) -> Result<ShutdownDisposition, String> {
    let started = Instant::now();
    loop {
        let exited = lock(child, "sidecar process")?
            .try_wait()
            .map_err(|error| format!("failed to monitor sidecar shutdown: {error}"))?
            .is_some();
        if exited {
            return Ok(ShutdownDisposition::Exited);
        }

        let elapsed = started.elapsed();
        if elapsed >= timeout {
            break;
        }
        thread::sleep(poll_interval.min(timeout.saturating_sub(elapsed)));
    }

    // Close the race between the final poll and kill. If the child completed
    // cleanly in that gap, preserve that result instead of reporting force.
    let mut process = lock(child, "sidecar process")?;
    if process
        .try_wait()
        .map_err(|error| format!("failed to monitor sidecar shutdown: {error}"))?
        .is_some()
    {
        return Ok(ShutdownDisposition::Exited);
    }
    if let Err(error) = process.kill() {
        if process
            .try_wait()
            .map_err(|wait_error| format!("failed to monitor sidecar shutdown: {wait_error}"))?
            .is_some()
        {
            return Ok(ShutdownDisposition::Exited);
        }
        return Err(format!("failed to stop the sidecar: {error}"));
    }
    process
        .wait()
        .map_err(|error| format!("failed to reap the stopped sidecar: {error}"))?;
    Ok(ShutdownDisposition::Forced)
}

fn read_stdout(app: AppHandle, supervisor: Supervisor, generation: u64, mut reader: impl BufRead) {
    let mut chunks = ChunkAssembler::default();
    loop {
        let line = match read_bounded_line(&mut reader, crate::protocol::MAX_JSONL_BYTES) {
            Ok(Some(line)) => line,
            Ok(None) => return,
            Err(_) => {
                fail_protocol(
                    &app,
                    &supervisor,
                    generation,
                    "failed to read sidecar stdout",
                );
                return;
            }
        };
        let record = line.trim_end_matches(['\r', '\n']);
        match EventEnvelope::parse(record).and_then(|envelope| chunks.accept(envelope)) {
            Ok(Some(envelope)) => {
                let channel = if envelope.event == "permission.request" {
                    PERMISSION_EVENT_CHANNEL
                } else {
                    ORDINARY_EVENT_CHANNEL
                };
                if app.emit(channel, envelope).is_err() {
                    let _ = supervisor.kill_generation(generation);
                    return;
                }
            }
            Ok(None) => {}
            Err(message) => {
                fail_protocol(&app, &supervisor, generation, &message);
                return;
            }
        }
    }
}

fn read_stderr(_app: AppHandle, reader: impl Read) {
    // Stderr is not a trusted desktop protocol and may contain provider or
    // dependency diagnostics. Drain it so the child cannot block, but never
    // forward its raw content into the WebView. Actionable sidecar failures
    // use the bounded, versioned JSONL stdout protocol instead.
    let _ = drain_stderr(reader);
}

fn drain_stderr(mut reader: impl Read) -> io::Result<u64> {
    // stderr is an opaque byte stream, not a line protocol. In particular, a
    // dependency may emit one diagnostic line larger than the stdout record
    // bound; stopping the drain there could deadlock the child on a full pipe.
    io::copy(&mut reader, &mut io::sink())
}

fn read_bounded_line(reader: &mut impl BufRead, limit: usize) -> io::Result<Option<String>> {
    let mut bytes = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            if bytes.is_empty() {
                return Ok(None);
            }
            break;
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let consumed = newline.map_or(available.len(), |index| index + 1);
        if bytes.len().saturating_add(consumed) > limit {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "sidecar output line exceeds its limit",
            ));
        }
        bytes.extend_from_slice(&available[..consumed]);
        reader.consume(consumed);
        if newline.is_some() {
            break;
        }
    }
    String::from_utf8(bytes)
        .map(Some)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "sidecar output is not UTF-8"))
}

fn monitor_process(
    app: AppHandle,
    supervisor: Supervisor,
    generation: u64,
    pid: u32,
    child: Arc<Mutex<Child>>,
) {
    loop {
        let result = match lock(&child, "sidecar process") {
            Ok(mut process) => process.try_wait(),
            Err(_) => {
                supervisor.clear_generation(generation);
                let _ = emit_ordinary(
                    &app,
                    "supervisor.error",
                    json!({"message": "sidecar process state was poisoned"}),
                );
                return;
            }
        };
        match result {
            Ok(Some(status)) => {
                supervisor.clear_generation(generation);
                let _ = emit_ordinary(
                    &app,
                    "supervisor.status",
                    json!({
                        "state": "exited",
                        "pid": pid,
                        "generation": generation,
                        "success": status.success(),
                        "code": status.code()
                    }),
                );
                return;
            }
            Ok(None) => thread::sleep(PROCESS_POLL_INTERVAL),
            Err(error) => {
                supervisor.clear_generation(generation);
                let _ = emit_ordinary(
                    &app,
                    "supervisor.error",
                    json!({"message": format!("failed to monitor the sidecar: {error}")}),
                );
                return;
            }
        }
    }
}

fn fail_protocol(app: &AppHandle, supervisor: &Supervisor, generation: u64, message: &str) {
    let _ = emit_ordinary(app, "protocol.error", json!({"message": message}));
    let _ = supervisor.kill_generation(generation);
}

fn emit_ordinary(app: &AppHandle, event: &str, payload: Value) -> Result<(), String> {
    app.emit(
        ORDINARY_EVENT_CHANNEL,
        EventEnvelope::desktop(event, payload),
    )
    .map_err(|error| format!("failed to emit a desktop event: {error}"))
}

fn status_for(handle: &ChildHandle) -> SupervisorStatus {
    SupervisorStatus {
        running: true,
        pid: Some(handle.pid),
        generation: Some(handle.generation),
    }
}

fn lock<'a, T>(mutex: &'a Mutex<T>, label: &str) -> Result<MutexGuard<'a, T>, String> {
    mutex
        .lock()
        .map_err(|_| format!("{label} lock was poisoned"))
}

#[cfg(debug_assertions)]
fn resolve_launch_spec(_app: &AppHandle) -> Result<LaunchSpec, String> {
    let repository = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .map_err(|error| format!("could not resolve the repository root: {error}"))?;
    let python = repository.join("venv/bin/python");
    if !python.is_file() {
        return Err(format!(
            "the fixed development interpreter does not exist at {}",
            python.display()
        ));
    }
    Ok(LaunchSpec {
        program: python,
        args: vec![OsString::from("-m"), OsString::from("dialektike.sidecar")],
        working_directory: repository,
    })
}

#[cfg(not(debug_assertions))]
fn resolve_launch_spec(app: &AppHandle) -> Result<LaunchSpec, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("could not resolve the application resources: {error}"))?;
    let sidecar = resource_dir.join("sidecar/dialektike-sidecar");
    if !sidecar.is_file() {
        return Err(format!(
            "the packaged Dialektikḗ sidecar does not exist at {}",
            sidecar.display()
        ));
    }
    Ok(LaunchSpec {
        program: sidecar,
        args: Vec::new(),
        working_directory: resource_dir,
    })
}

#[cfg(test)]
mod tests {
    use std::{
        io::{BufReader, Cursor},
        process::{Command, Stdio},
        sync::{Arc, Mutex},
        time::{Duration, Instant},
    };

    use serde_json::json;
    use sha2::{Digest, Sha256};

    use crate::protocol::{EventEnvelope, MAX_JSONL_BYTES, TRANSPORT_CHUNK_EVENT};

    use super::{
        drain_stderr, read_bounded_line, wait_for_exit_or_kill, ChunkAssembler, ShutdownDisposition,
    };

    #[test]
    fn bounded_reader_never_accumulates_an_oversized_record() {
        let mut valid = BufReader::new(Cursor::new(b"{\"event\":\"ready\"}\nnext\n"));
        assert_eq!(
            read_bounded_line(&mut valid, 64).unwrap().as_deref(),
            Some("{\"event\":\"ready\"}\n")
        );
        assert_eq!(
            read_bounded_line(&mut valid, 64).unwrap().as_deref(),
            Some("next\n")
        );

        let mut oversized = BufReader::new(Cursor::new(vec![b'x'; 65]));
        assert!(read_bounded_line(&mut oversized, 64).is_err());
    }

    #[test]
    fn stderr_drainer_consumes_an_opaque_oversized_stream() {
        let bytes = vec![b'x'; 1024 * 1024 + 17];
        assert_eq!(drain_stderr(Cursor::new(bytes)).unwrap(), 1024 * 1024 + 17);
    }

    #[test]
    fn oversized_verbatim_permission_is_reassembled_before_validation() {
        let native = "x".repeat(600 * 1024);
        let original = EventEnvelope::desktop(
            "permission.request",
            json!({
                "permission_id": "permission-large",
                "runtime_id": "claude-code",
                "title": "Write a large file",
                "card": native,
                "native_payload": {"content": native},
                "annotations": {}
            }),
        );
        let line = serde_json::to_string(&original).unwrap() + "\n";
        assert!(line.len() > MAX_JSONL_BYTES);
        let transfer_id = format!("{:x}", Sha256::digest(line.as_bytes()));
        let pieces = line.as_bytes().chunks(128 * 1024).collect::<Vec<_>>();
        let mut assembler = ChunkAssembler::default();
        let mut completed = None;
        for (index, piece) in pieces.iter().enumerate() {
            let chunk = EventEnvelope::desktop(
                TRANSPORT_CHUNK_EVENT,
                json!({
                    "transfer_id": transfer_id,
                    "index": index,
                    "total": pieces.len(),
                    "encoded_length": line.len(),
                    "data": std::str::from_utf8(piece).unwrap()
                }),
            );
            let encoded_chunk = serde_json::to_string(&chunk).unwrap();
            assert!(encoded_chunk.len() <= MAX_JSONL_BYTES);
            completed = assembler
                .accept(EventEnvelope::parse(&encoded_chunk).unwrap())
                .unwrap()
                .or(completed);
        }
        let completed = completed.expect("final chunk must reconstruct one event");
        assert_eq!(completed.event, "permission.request");
        assert_eq!(
            completed.payload["native_payload"]["content"]
                .as_str()
                .unwrap()
                .len(),
            600 * 1024
        );
    }

    #[test]
    fn graceful_shutdown_waits_beyond_the_old_750ms_cutoff() {
        let child = Command::new("sleep")
            .arg("1")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("sleep must be available for the process-lifecycle test");
        let child = Arc::new(Mutex::new(child));
        let started = Instant::now();

        assert_eq!(
            wait_for_exit_or_kill(&child, Duration::from_secs(3), Duration::from_millis(20))
                .unwrap(),
            ShutdownDisposition::Exited
        );
        assert!(started.elapsed() >= Duration::from_millis(750));
        assert!(child.lock().unwrap().try_wait().unwrap().is_some());
    }

    #[test]
    fn hung_shutdown_is_force_stopped_at_the_bounded_fallback() {
        let child = Command::new("sleep")
            .arg("30")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("sleep must be available for the process-lifecycle test");
        let child = Arc::new(Mutex::new(child));
        let started = Instant::now();

        assert_eq!(
            wait_for_exit_or_kill(
                &child,
                Duration::from_millis(120),
                Duration::from_millis(10),
            )
            .unwrap(),
            ShutdownDisposition::Forced
        );
        assert!(started.elapsed() >= Duration::from_millis(120));
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(child.lock().unwrap().try_wait().unwrap().is_some());
    }
}
