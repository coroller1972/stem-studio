use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::Stdio;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};
use tokio::process::Command;
use tokio::sync::{watch, Mutex};
use uuid::Uuid;

const SESSION_SCHEMA_VERSION: u32 = 2;
const SESSION_MANIFEST_NAME: &str = "session.json";
const MAX_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAX_TRANSCRIPTION_JSON_BYTES: u64 = 16 * 1024 * 1024;
const MAX_CACHED_PROJECTS: usize = 5;
const MAX_PROJECT_AGE_SECONDS: u64 = 7 * 24 * 60 * 60;

#[derive(Default)]
struct RunnerState {
    cancel_sender: Mutex<Option<watch::Sender<bool>>>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct StemPaths {
    vocals: String,
    drums: String,
    bass: String,
    other: String,
}

#[derive(Debug, Deserialize)]
struct CompletedEvent {
    #[serde(rename = "type")]
    event_type: String,
    stems: StemPaths,
}

#[derive(Debug, Deserialize)]
struct ErrorEvent {
    message: String,
}

#[derive(Default)]
struct EngineOutput {
    completed: Option<StemPaths>,
    error_message: Option<String>,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum TranscriptionTrack {
    Bass,
    Drums,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum BassTuning {
    Eadg,
    Beadg,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
enum BassTranscriptionEngine {
    BasicPitch,
    Torchcrepe,
}

impl BassTranscriptionEngine {
    fn as_str(self) -> &'static str {
        match self {
            Self::BasicPitch => "basic-pitch",
            Self::Torchcrepe => "torchcrepe",
        }
    }
}

impl BassTuning {
    fn as_str(self) -> &'static str {
        match self {
            Self::Eadg => "eadg",
            Self::Beadg => "beadg",
        }
    }
}

impl TranscriptionTrack {
    fn as_str(self) -> &'static str {
        match self {
            Self::Bass => "bass",
            Self::Drums => "drums",
        }
    }

    fn command(self) -> &'static str {
        match self {
            Self::Bass => "transcribe-bass",
            Self::Drums => "transcribe-drums",
        }
    }

    fn requantize_command(self) -> &'static str {
        match self {
            Self::Bass => "requantize-bass",
            Self::Drums => "requantize-drums",
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct ManualTiming {
    bpm: f64,
    first_measure_seconds: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TranscriptionResult {
    events_file: String,
    midi_file: String,
    music_xml_file: String,
    transcription: TranscriptionPayload,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "track", rename_all = "lowercase")]
enum TranscriptionPayload {
    Bass(BassTranscriptionPayload),
    Drums(DrumTranscriptionPayload),
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct BassTranscriptionPayload {
    schema_version: u32,
    events: Vec<NoteEventPayload>,
    tab: Vec<TabNotePayload>,
    tempo_map: TempoMapPayload,
    tuning: Vec<u8>,
    #[serde(default)]
    warnings: Vec<String>,
    #[serde(default)]
    model_id: Option<String>,
    #[serde(default)]
    source_events: Vec<NoteEventPayload>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DrumTranscriptionPayload {
    schema_version: u32,
    events: Vec<DrumEventPayload>,
    tempo_map: TempoMapPayload,
    #[serde(default)]
    warnings: Vec<String>,
    #[serde(default)]
    source_events: Vec<DrumEventPayload>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TempoMapPayload {
    bpm: f64,
    beats: Vec<TempoBeatPayload>,
    time_signature: TimeSignaturePayload,
    #[serde(default)]
    tempo_candidates: Vec<f64>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TempoBeatPayload {
    beat_index: i64,
    time_seconds: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct TimeSignaturePayload {
    numerator: u8,
    denominator: u8,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct NoteEventPayload {
    id: String,
    detected_start_seconds: f64,
    detected_end_seconds: f64,
    quantized_start_beat: Option<f64>,
    quantized_duration_beats: Option<f64>,
    midi_pitch: u8,
    velocity: u8,
    confidence: Option<f64>,
    #[serde(default)]
    pitch_bends: Vec<PitchBendPayload>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct PitchBendPayload {
    time_offset_seconds: f64,
    semitones: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DrumEventPayload {
    id: String,
    detected_time_seconds: f64,
    quantized_beat: Option<f64>,
    instrument: DrumInstrumentPayload,
    velocity: u8,
    confidence: Option<f64>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum DrumInstrumentPayload {
    Kick,
    Snare,
    ClosedHihat,
    OpenHihat,
    Ride,
    Crash,
    HighTom,
    MidTom,
    LowTom,
    Other,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TabNotePayload {
    note_event_id: String,
    string_index: usize,
    fret: u8,
    start_beat: f64,
    duration_beats: f64,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
struct SessionTranscriptions {
    #[serde(skip_serializing_if = "Option::is_none")]
    bass: Option<TranscriptionArtifactPaths>,
    #[serde(skip_serializing_if = "Option::is_none")]
    drums: Option<TranscriptionArtifactPaths>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TranscriptionArtifactPaths {
    events_file: String,
    midi_file: String,
    music_xml_file: String,
}

#[derive(Debug, Clone, Default, Serialize)]
struct RestoredTranscriptions {
    bass: Option<TranscriptionResult>,
    drums: Option<TranscriptionResult>,
}

#[derive(Debug, Deserialize)]
struct TranscriptionCompletedEvent {
    #[serde(rename = "type")]
    event_type: String,
    track: TranscriptionTrack,
    result: TranscriptionResult,
}

#[derive(Default)]
struct TranscriptionEngineOutput {
    completed: Option<TranscriptionResult>,
    error_message: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SeparationResult {
    project_id: String,
    project_path: String,
    stems: StemPaths,
    quality_profile: SeparationQuality,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TrackMixState {
    volume: f64,
    muted: bool,
    solo: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct StemTrackStates {
    vocals: TrackMixState,
    drums: TrackMixState,
    bass: TrackMixState,
    other: TrackMixState,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct SessionState {
    current_time_seconds: f64,
    start_marker_seconds: f64,
    master_volume: f64,
    tracks: StemTrackStates,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct SessionManifest {
    schema_version: u32,
    saved_at_unix_seconds: u64,
    source_name: String,
    quality_profile: SeparationQuality,
    stems: StemPaths,
    state: SessionState,
    #[serde(skip_serializing_if = "Option::is_none")]
    engine_metadata: Option<Value>,
    #[serde(default)]
    transcriptions: SessionTranscriptions,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SavedSession {
    session_path: String,
    manifest_path: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RestoredSession {
    session_path: String,
    manifest_path: String,
    source_name: String,
    quality_profile: SeparationQuality,
    stems: StemPaths,
    state: SessionState,
    transcriptions: RestoredTranscriptions,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum SeparationQuality {
    Standard,
    High,
}

#[tauri::command]
async fn save_session(
    project_path: String,
    session_path: String,
    source_name: String,
    quality_profile: SeparationQuality,
    state: SessionState,
) -> Result<SavedSession, String> {
    tauri::async_runtime::spawn_blocking(move || {
        save_session_files(
            Path::new(&project_path),
            Path::new(&session_path),
            &source_name,
            quality_profile,
            state,
        )
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn load_session(app: AppHandle, manifest_path: String) -> Result<RestoredSession, String> {
    let restored =
        tauri::async_runtime::spawn_blocking(move || load_session_files(Path::new(&manifest_path)))
            .await
            .map_err(|error| error.to_string())??;

    app.asset_protocol_scope()
        .allow_directory(&restored.session_path, false)
        .map_err(|error| format!("Unable to authorize the session audio files: {error}"))?;
    Ok(restored)
}

impl SeparationQuality {
    fn as_str(self) -> &'static str {
        match self {
            Self::Standard => "standard",
            Self::High => "high",
        }
    }
}

#[tauri::command]
async fn separate_audio(
    app: AppHandle,
    state: State<'_, RunnerState>,
    input_path: String,
    quality: Option<SeparationQuality>,
) -> Result<SeparationResult, String> {
    validate_input(&input_path)?;

    let mut active = state.cancel_sender.lock().await;
    if active.is_some() {
        return Err("A separation is already running.".into());
    }
    let (cancel_sender, mut cancel_receiver) = watch::channel(false);
    *active = Some(cancel_sender);
    drop(active);

    let project_id = Uuid::new_v4().to_string();
    let projects_path = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("projects");
    cleanup_project_cache(&projects_path);
    let project_path = projects_path.join(&project_id);
    std::fs::create_dir_all(&project_path).map_err(|error| error.to_string())?;

    let quality = quality.unwrap_or(SeparationQuality::Standard);
    let result = run_engine(
        &app,
        &input_path,
        &project_path,
        quality,
        &mut cancel_receiver,
    )
    .await;
    *state.cancel_sender.lock().await = None;

    let stems = match result {
        Ok(stems) => stems,
        Err(error) => {
            let _ = fs::remove_dir_all(&project_path);
            return Err(error);
        }
    };
    Ok(SeparationResult {
        project_id,
        project_path: project_path.to_string_lossy().into_owned(),
        stems,
        quality_profile: quality,
    })
}

#[tauri::command]
async fn cancel_separation(state: State<'_, RunnerState>) -> Result<(), String> {
    let active = state.cancel_sender.lock().await;
    match active.as_ref() {
        Some(sender) => sender
            .send(true)
            .map_err(|_| "The separation process already stopped.".to_string()),
        None => Ok(()),
    }
}

#[tauri::command]
async fn transcribe_track(
    app: AppHandle,
    state: State<'_, RunnerState>,
    project_path: String,
    track: TranscriptionTrack,
    bass_tuning: Option<BassTuning>,
    bass_engine: Option<BassTranscriptionEngine>,
) -> Result<TranscriptionResult, String> {
    let project = PathBuf::from(project_path);
    if !project.is_dir() {
        return Err("The current stem project could not be found.".into());
    }
    let input = project.join(format!("{}.wav", track.as_str()));
    if !input.is_file() {
        return Err(format!("The {} stem could not be found.", track.as_str()));
    }
    let output = project.join("transcription");
    fs::create_dir_all(&output)
        .map_err(|error| format!("Unable to create the transcription folder: {error}"))?;

    let mut active = state.cancel_sender.lock().await;
    if active.is_some() {
        return Err("An audio operation is already running.".into());
    }
    let (cancel_sender, mut cancel_receiver) = watch::channel(false);
    *active = Some(cancel_sender);
    drop(active);

    let result = run_transcription_engine(
        &app,
        &input,
        &output,
        project
            .join("drums.wav")
            .is_file()
            .then(|| project.join("drums.wav")),
        track,
        bass_tuning.unwrap_or(BassTuning::Eadg),
        bass_engine.unwrap_or(BassTranscriptionEngine::BasicPitch),
        None,
        &mut cancel_receiver,
    )
    .await;
    *state.cancel_sender.lock().await = None;
    result
}

#[tauri::command]
async fn requantize_transcription(
    app: AppHandle,
    state: State<'_, RunnerState>,
    project_path: String,
    track: TranscriptionTrack,
    bpm: f64,
    first_measure_seconds: f64,
) -> Result<TranscriptionResult, String> {
    if !bpm.is_finite() || !(20.0..=400.0).contains(&bpm) {
        return Err("Tempo must be between 20 and 400 BPM.".into());
    }
    if !first_measure_seconds.is_finite() || first_measure_seconds < 0.0 {
        return Err("The first measure timestamp must be a positive number.".into());
    }
    let project = PathBuf::from(project_path);
    if !project.is_dir() {
        return Err("The current stem project could not be found.".into());
    }
    let output = project.join("transcription");
    let events_file = output.join(format!("{}.json", track.as_str()));
    if !events_file.is_file() {
        return Err(format!(
            "The saved {} transcription could not be found.",
            track.as_str()
        ));
    }

    let mut active = state.cancel_sender.lock().await;
    if active.is_some() {
        return Err("An audio operation is already running.".into());
    }
    let (cancel_sender, mut cancel_receiver) = watch::channel(false);
    *active = Some(cancel_sender);
    drop(active);

    let result = run_transcription_engine(
        &app,
        &events_file,
        &output,
        None,
        track,
        BassTuning::Eadg,
        BassTranscriptionEngine::BasicPitch,
        Some(ManualTiming {
            bpm,
            first_measure_seconds,
        }),
        &mut cancel_receiver,
    )
    .await;
    *state.cancel_sender.lock().await = None;
    result
}

#[tauri::command]
async fn export_transcription_file(
    source_path: String,
    destination_path: String,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        let source = fs::canonicalize(&source_path)
            .map_err(|error| format!("Unable to find the transcription export: {error}"))?;
        let source_extension = source
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            .ok_or("The transcription export has no extension.")?;
        if !matches!(source_extension.as_str(), "mid" | "musicxml") || !source.is_file() {
            return Err("Only generated MIDI and MusicXML files can be exported.".into());
        }
        let destination = PathBuf::from(destination_path);
        let destination_extension = destination
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            .ok_or("The export destination has no extension.")?;
        if destination_extension != source_extension {
            return Err("The export destination must keep the generated file extension.".into());
        }
        fs::copy(source, destination)
            .map_err(|error| format!("Unable to export the transcription file: {error}"))?;
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())?
}

async fn run_transcription_engine(
    app: &AppHandle,
    input: &Path,
    output: &Path,
    beat_source: Option<PathBuf>,
    track: TranscriptionTrack,
    bass_tuning: BassTuning,
    bass_engine: BassTranscriptionEngine,
    manual_timing: Option<ManualTiming>,
    cancel: &mut watch::Receiver<bool>,
) -> Result<TranscriptionResult, String> {
    let (program, prefix_args) = resolve_engine_command(app)?;
    let mut command = Command::new(program);
    command.args(prefix_args);
    if let Some(timing) = manual_timing {
        command
            .arg(track.requantize_command())
            .arg(input)
            .arg("--output")
            .arg(output)
            .arg("--bpm")
            .arg(timing.bpm.to_string())
            .arg("--first-measure-seconds")
            .arg(timing.first_measure_seconds.to_string());
    } else {
        command
            .arg(track.command())
            .arg(input)
            .arg("--output")
            .arg(output);
        if let Some(beat_source) = beat_source {
            command.arg("--beat-source").arg(beat_source);
        }
        if matches!(track, TranscriptionTrack::Bass) {
            command
                .arg("--bass-tuning")
                .arg(bass_tuning.as_str())
                .arg("--bass-engine")
                .arg(bass_engine.as_str());
        }
    }
    command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let models_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("models");
    fs::create_dir_all(&models_dir).map_err(|error| error.to_string())?;
    command.env("STEM_STUDIO_MODELS_DIR", &models_dir);
    if let Some(ffmpeg_path) = resolve_ffmpeg_path(app) {
        command.env("STEM_STUDIO_FFMPEG", ffmpeg_path);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start the transcription engine: {error}"))?;
    let stdout = child.stdout.take().ok_or("Unable to read engine output.")?;
    let mut stderr = child.stderr.take().ok_or("Unable to read engine logs.")?;
    let event_app = app.clone();
    let stdout_task = tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        let mut output = TranscriptionEngineOutput::default();
        while let Some(line) = lines.next_line().await.map_err(|error| error.to_string())? {
            let Ok(value) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            event_app
                .emit("transcription-event", &value)
                .map_err(|error| error.to_string())?;
            if value.get("type").and_then(Value::as_str) == Some("transcription_completed") {
                if let Ok(event) =
                    serde_json::from_value::<TranscriptionCompletedEvent>(value.clone())
                {
                    if event.event_type == "transcription_completed"
                        && event.track.as_str() == track.as_str()
                    {
                        output.completed = Some(event.result);
                    }
                }
            } else if value.get("type").and_then(Value::as_str) == Some("transcription_error") {
                if let Ok(event) = serde_json::from_value::<ErrorEvent>(value) {
                    output.error_message = Some(event.message);
                }
            }
        }
        Ok::<TranscriptionEngineOutput, String>(output)
    });
    let stderr_task = tauri::async_runtime::spawn(async move {
        let mut logs = String::new();
        stderr
            .read_to_string(&mut logs)
            .await
            .map_err(|error| error.to_string())?;
        Ok::<String, String>(logs)
    });
    let status = tokio::select! {
        status = child.wait() => status.map_err(|error| error.to_string())?,
        changed = cancel.changed() => {
            if changed.is_ok() && *cancel.borrow() {
                let _ = child.start_kill();
                let _ = child.wait().await;
                return Err("Transcription was cancelled.".into());
            }
            child.wait().await.map_err(|error| error.to_string())?
        }
    };
    let engine_output = stdout_task.await.map_err(|error| error.to_string())??;
    let logs = stderr_task.await.map_err(|error| error.to_string())??;
    if !logs.is_empty() {
        eprintln!("stem-engine transcription: {logs}");
    }
    if !status.success() {
        return Err(engine_output
            .error_message
            .unwrap_or_else(|| "Transcription process terminated unexpectedly.".into()));
    }
    engine_output
        .completed
        .ok_or_else(|| "The engine did not return a transcription.".into())
}

async fn run_engine(
    app: &AppHandle,
    input: &str,
    output: &Path,
    quality: SeparationQuality,
    cancel: &mut watch::Receiver<bool>,
) -> Result<StemPaths, String> {
    let (program, prefix_args) = resolve_engine_command(app)?;
    let mut command = Command::new(program);
    command
        .args(prefix_args)
        .arg("separate")
        .arg(input)
        .arg("--output")
        .arg(output)
        .arg("--quality")
        .arg(quality.as_str())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let models_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("models");
    let torch_models_dir = models_dir.join("torch");
    let bs_roformer_models_dir = models_dir.join("bs-roformer");
    std::fs::create_dir_all(&torch_models_dir).map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&bs_roformer_models_dir).map_err(|error| error.to_string())?;
    command
        .env("TORCH_HOME", torch_models_dir)
        .env("BS_ROFORMER_MODELS_PATH", bs_roformer_models_dir);
    if let Some(ffmpeg_path) = resolve_ffmpeg_path(app) {
        command.env("STEM_STUDIO_FFMPEG", ffmpeg_path);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start the separation engine: {error}"))?;
    let stdout = child.stdout.take().ok_or("Unable to read engine output.")?;
    let mut stderr = child.stderr.take().ok_or("Unable to read engine logs.")?;
    let event_app = app.clone();

    let stdout_task = tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        let mut output = EngineOutput::default();
        while let Some(line) = lines.next_line().await.map_err(|error| error.to_string())? {
            let Ok(value) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            event_app
                .emit("separation-event", &value)
                .map_err(|error| error.to_string())?;
            if value.get("type").and_then(Value::as_str) == Some("completed") {
                if let Ok(event) = serde_json::from_value::<CompletedEvent>(value.clone()) {
                    if event.event_type == "completed" {
                        output.completed = Some(event.stems);
                    }
                }
            }
            if value.get("type").and_then(Value::as_str) == Some("error") {
                if let Ok(event) = serde_json::from_value::<ErrorEvent>(value) {
                    output.error_message = Some(event.message);
                }
            }
        }
        Ok::<EngineOutput, String>(output)
    });

    let stderr_task = tauri::async_runtime::spawn(async move {
        let mut logs = String::new();
        stderr
            .read_to_string(&mut logs)
            .await
            .map_err(|error| error.to_string())?;
        Ok::<String, String>(logs)
    });

    let status = tokio::select! {
        status = child.wait() => status.map_err(|error| error.to_string())?,
        changed = cancel.changed() => {
            if changed.is_ok() && *cancel.borrow() {
                let _ = child.start_kill();
                let _ = child.wait().await;
                return Err("Stem separation was cancelled.".into());
            }
            child.wait().await.map_err(|error| error.to_string())?
        }
    };

    let engine_output = stdout_task.await.map_err(|error| error.to_string())??;
    let logs = stderr_task.await.map_err(|error| error.to_string())??;
    if !logs.is_empty() {
        eprintln!("stem-engine: {logs}");
    }
    if !status.success() {
        return Err(engine_output
            .error_message
            .unwrap_or_else(|| "Separation process terminated unexpectedly.".into()));
    }
    engine_output
        .completed
        .ok_or_else(|| "The engine did not return the separated stems.".into())
}

fn resolve_engine_command(app: &AppHandle) -> Result<(PathBuf, Vec<String>), String> {
    if cfg!(debug_assertions) {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let engine_dir = manifest.join("../../engine");
        let python311 = engine_dir.join(".venv311/bin/python");
        let default_virtualenv = engine_dir.join(".venv/bin/python");
        let python = std::env::var_os("STEM_STUDIO_PYTHON")
            .map(PathBuf::from)
            .or_else(|| python311.is_file().then_some(python311))
            .or_else(|| default_virtualenv.is_file().then_some(default_virtualenv))
            .unwrap_or_else(|| PathBuf::from("python3"));
        return Ok((
            python,
            vec![engine_dir.join("main.py").to_string_lossy().into_owned()],
        ));
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let candidates = [
        resource_dir.join("binaries/stem-engine/stem-engine"),
        resource_dir.join("stem-engine/stem-engine"),
        resource_dir.join("stem-engine"),
        resource_dir.join("stem-engine-aarch64-apple-darwin"),
        resource_dir.join("binaries/stem-engine-aarch64-apple-darwin"),
        executable_dir
            .as_ref()
            .map(|path| path.join("stem-engine"))
            .unwrap_or_default(),
        executable_dir
            .as_ref()
            .map(|path| path.join("stem-engine-aarch64-apple-darwin"))
            .unwrap_or_default(),
    ];
    let executable = candidates
        .into_iter()
        .find(|path| path.is_file())
        .ok_or("Packaged stem-engine sidecar was not found.")?;
    Ok((executable, Vec::new()))
}

fn resolve_ffmpeg_path(app: &AppHandle) -> Option<PathBuf> {
    let configured = std::env::var_os("STEM_STUDIO_FFMPEG").map(PathBuf::from);
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let resource_dir = app.path().resource_dir().ok();
    let candidates = [
        configured.unwrap_or_default(),
        executable_dir
            .as_ref()
            .map(|path| path.join("ffmpeg"))
            .unwrap_or_default(),
        resource_dir
            .as_ref()
            .map(|path| path.join("ffmpeg"))
            .unwrap_or_default(),
        PathBuf::from("/opt/ffmpeg/ffmpeg"),
        PathBuf::from("/opt/homebrew/bin/ffmpeg"),
        PathBuf::from("/usr/local/bin/ffmpeg"),
    ];
    candidates.into_iter().find(|path| path.is_file())
}

fn save_session_files(
    project_path: &Path,
    requested_session_path: &Path,
    source_name: &str,
    quality_profile: SeparationQuality,
    state: SessionState,
) -> Result<SavedSession, String> {
    validate_session_state(&state)?;
    if !project_path.is_dir() {
        return Err("The current stem project could not be found.".into());
    }
    let session_path = normalized_session_path(requested_session_path)?;
    let destination_dir = session_path
        .parent()
        .ok_or("The selected session destination has no parent folder.")?;
    if !destination_dir.is_dir() {
        return Err("The selected session destination could not be found.".into());
    }
    if session_path.exists() {
        if !session_path.is_dir() {
            return Err("The selected session destination is not a folder.".into());
        }
        load_session_files(&session_path.join(SESSION_MANIFEST_NAME)).map_err(|error| {
            format!("The selected folder is not a valid Stem Studio session: {error}")
        })?;
    }

    let session_name = sanitize_session_name(source_name);
    let temporary_path =
        destination_dir.join(format!(".{session_name}.stemstudio-{}.tmp", Uuid::new_v4()));
    fs::create_dir(&temporary_path)
        .map_err(|error| format!("Unable to create the session folder: {error}"))?;

    let result = (|| {
        for stem_name in ["vocals", "drums", "bass", "other"] {
            let file_name = format!("{stem_name}.wav");
            let source = project_path.join(&file_name);
            if !source.is_file() {
                return Err(format!("The {stem_name} stem could not be found."));
            }
            fs::copy(source, temporary_path.join(&file_name))
                .map_err(|error| format!("Unable to copy {file_name}: {error}"))?;
        }

        let engine_metadata = read_optional_metadata(&project_path.join("source.json"));
        let transcriptions = copy_session_transcriptions(project_path, &temporary_path)?;
        let manifest = SessionManifest {
            schema_version: SESSION_SCHEMA_VERSION,
            saved_at_unix_seconds: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| error.to_string())?
                .as_secs(),
            source_name: normalized_source_name(source_name),
            quality_profile,
            stems: StemPaths {
                vocals: "vocals.wav".into(),
                drums: "drums.wav".into(),
                bass: "bass.wav".into(),
                other: "other.wav".into(),
            },
            state,
            engine_metadata,
            transcriptions,
        };
        let manifest_json = serde_json::to_string_pretty(&manifest)
            .map_err(|error| format!("Unable to serialize the session manifest: {error}"))?;
        fs::write(temporary_path.join(SESSION_MANIFEST_NAME), manifest_json)
            .map_err(|error| format!("Unable to write the session manifest: {error}"))?;
        replace_session_directory(&temporary_path, &session_path)?;
        Ok(())
    })();

    if let Err(error) = result {
        let _ = fs::remove_dir_all(&temporary_path);
        return Err(error);
    }

    Ok(SavedSession {
        session_path: session_path.to_string_lossy().into_owned(),
        manifest_path: session_path
            .join(SESSION_MANIFEST_NAME)
            .to_string_lossy()
            .into_owned(),
    })
}

fn load_session_files(manifest_path: &Path) -> Result<RestoredSession, String> {
    if !manifest_path.is_file() {
        return Err("The selected session manifest could not be found.".into());
    }
    let metadata = fs::metadata(manifest_path)
        .map_err(|error| format!("Unable to inspect the session manifest: {error}"))?;
    if metadata.len() > MAX_MANIFEST_BYTES {
        return Err("The session manifest is unexpectedly large.".into());
    }

    let manifest_json = fs::read_to_string(manifest_path)
        .map_err(|error| format!("Unable to read the session manifest: {error}"))?;
    let manifest: SessionManifest = serde_json::from_str(&manifest_json)
        .map_err(|error| format!("The session manifest is invalid: {error}"))?;
    if !(1..=SESSION_SCHEMA_VERSION).contains(&manifest.schema_version) {
        return Err(format!(
            "Session format version {} is not supported.",
            manifest.schema_version
        ));
    }
    if manifest.source_name.trim().is_empty() {
        return Err("The session manifest has no source name.".into());
    }
    validate_session_state(&manifest.state)?;

    let session_path = manifest_path
        .parent()
        .ok_or("The session manifest has no parent folder.")?;
    let canonical_session = fs::canonicalize(session_path)
        .map_err(|error| format!("Unable to resolve the session folder: {error}"))?;
    let stems = StemPaths {
        vocals: resolve_session_stem(&canonical_session, &manifest.stems.vocals, "vocals")?,
        drums: resolve_session_stem(&canonical_session, &manifest.stems.drums, "drums")?,
        bass: resolve_session_stem(&canonical_session, &manifest.stems.bass, "bass")?,
        other: resolve_session_stem(&canonical_session, &manifest.stems.other, "other")?,
    };
    let canonical_manifest = fs::canonicalize(manifest_path)
        .map_err(|error| format!("Unable to resolve the session manifest: {error}"))?;
    let transcriptions = RestoredTranscriptions {
        bass: restore_transcription(
            &canonical_session,
            manifest.transcriptions.bass.as_ref(),
            "bass",
        )?,
        drums: restore_transcription(
            &canonical_session,
            manifest.transcriptions.drums.as_ref(),
            "drums",
        )?,
    };

    Ok(RestoredSession {
        session_path: canonical_session.to_string_lossy().into_owned(),
        manifest_path: canonical_manifest.to_string_lossy().into_owned(),
        source_name: manifest.source_name,
        quality_profile: manifest.quality_profile,
        stems,
        state: manifest.state,
        transcriptions,
    })
}

fn copy_session_transcriptions(
    project_path: &Path,
    destination: &Path,
) -> Result<SessionTranscriptions, String> {
    let source_dir = project_path.join("transcription");
    if !source_dir.is_dir() {
        return Ok(SessionTranscriptions::default());
    }
    let destination_dir = destination.join("transcription");
    let mut result = SessionTranscriptions::default();
    for track in ["bass", "drums"] {
        let events_name = format!("{track}.json");
        let midi_name = format!("{track}.mid");
        let xml_name = format!("{track}.musicxml");
        let files = [
            source_dir.join(&events_name),
            source_dir.join(&midi_name),
            source_dir.join(&xml_name),
        ];
        if files.iter().all(|path| path.is_file()) {
            fs::create_dir_all(&destination_dir).map_err(|error| {
                format!("Unable to create the saved transcription folder: {error}")
            })?;
            for path in &files {
                let name = path
                    .file_name()
                    .ok_or("A transcription file has no name.")?;
                fs::copy(path, destination_dir.join(name))
                    .map_err(|error| format!("Unable to copy a transcription file: {error}"))?;
            }
            let paths = TranscriptionArtifactPaths {
                events_file: format!("transcription/{events_name}"),
                midi_file: format!("transcription/{midi_name}"),
                music_xml_file: format!("transcription/{xml_name}"),
            };
            if track == "bass" {
                result.bass = Some(paths);
            } else {
                result.drums = Some(paths);
            }
        }
    }
    Ok(result)
}

fn restore_transcription(
    session_path: &Path,
    paths: Option<&TranscriptionArtifactPaths>,
    track: &str,
) -> Result<Option<TranscriptionResult>, String> {
    let Some(paths) = paths else {
        return Ok(None);
    };
    let events_file = resolve_session_artifact(session_path, &paths.events_file, "json", track)?;
    let midi_file = resolve_session_artifact(session_path, &paths.midi_file, "mid", track)?;
    let music_xml_file =
        resolve_session_artifact(session_path, &paths.music_xml_file, "musicxml", track)?;
    let metadata = fs::metadata(&events_file)
        .map_err(|error| format!("Unable to inspect the {track} transcription: {error}"))?;
    if metadata.len() > MAX_TRANSCRIPTION_JSON_BYTES {
        return Err(format!(
            "The {track} transcription JSON is unexpectedly large."
        ));
    }
    let transcription = serde_json::from_str::<TranscriptionPayload>(
        &fs::read_to_string(&events_file)
            .map_err(|error| format!("Unable to read the {track} transcription: {error}"))?,
    )
    .map_err(|error| format!("The {track} transcription JSON is invalid: {error}"))?;
    validate_transcription(&transcription, track)?;
    Ok(Some(TranscriptionResult {
        events_file: events_file.to_string_lossy().into_owned(),
        midi_file: midi_file.to_string_lossy().into_owned(),
        music_xml_file: music_xml_file.to_string_lossy().into_owned(),
        transcription,
    }))
}

fn resolve_session_artifact(
    session_path: &Path,
    relative_path: &str,
    expected_extension: &str,
    track: &str,
) -> Result<PathBuf, String> {
    let path = Path::new(relative_path);
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(format!(
            "The {track} transcription path is not a safe relative path."
        ));
    }
    if !path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case(expected_extension))
    {
        return Err(format!(
            "The {track} transcription has an invalid file extension."
        ));
    }
    let canonical = fs::canonicalize(session_path.join(path))
        .map_err(|error| format!("Unable to resolve the {track} transcription: {error}"))?;
    if !canonical.starts_with(session_path) || !canonical.is_file() {
        return Err(format!(
            "The {track} transcription is outside the session folder or missing."
        ));
    }
    Ok(canonical)
}

fn resolve_session_stem(
    session_path: &Path,
    relative_path: &str,
    name: &str,
) -> Result<String, String> {
    let path = Path::new(relative_path);
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(format!("The {name} stem path is not a safe relative path."));
    }
    if !path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("wav"))
    {
        return Err(format!("The {name} stem is not a WAV file."));
    }

    let canonical = fs::canonicalize(session_path.join(path))
        .map_err(|error| format!("Unable to resolve the {name} stem: {error}"))?;
    if !canonical.starts_with(session_path) || !canonical.is_file() {
        return Err(format!(
            "The {name} stem is outside the session folder or missing."
        ));
    }
    Ok(canonical.to_string_lossy().into_owned())
}

fn validate_session_state(state: &SessionState) -> Result<(), String> {
    if !state.current_time_seconds.is_finite() || state.current_time_seconds < 0.0 {
        return Err("The session playback position is invalid.".into());
    }
    if !state.start_marker_seconds.is_finite() || state.start_marker_seconds < 0.0 {
        return Err("The session start marker is invalid.".into());
    }
    validate_unit_value(state.master_volume, "master volume")?;
    for (name, track) in [
        ("vocals", &state.tracks.vocals),
        ("drums", &state.tracks.drums),
        ("bass", &state.tracks.bass),
        ("other", &state.tracks.other),
    ] {
        validate_unit_value(track.volume, &format!("{name} volume"))?;
    }
    Ok(())
}

fn cleanup_project_cache(projects_path: &Path) {
    let Ok(entries) = fs::read_dir(projects_path) else {
        return;
    };
    let now = SystemTime::now();
    let mut projects = entries
        .filter_map(Result::ok)
        .filter(|entry| entry.path().is_dir())
        .filter_map(|entry| {
            let modified = entry.metadata().ok()?.modified().ok()?;
            Some((entry.path(), modified))
        })
        .collect::<Vec<_>>();
    projects.sort_by_key(|(_, modified)| std::cmp::Reverse(*modified));
    for (index, (path, modified)) in projects.into_iter().enumerate() {
        let expired = now
            .duration_since(modified)
            .is_ok_and(|age| age.as_secs() > MAX_PROJECT_AGE_SECONDS);
        if index >= MAX_CACHED_PROJECTS || expired {
            let _ = fs::remove_dir_all(path);
        }
    }
}

fn validate_transcription(
    transcription: &TranscriptionPayload,
    expected_track: &str,
) -> Result<(), String> {
    match transcription {
        TranscriptionPayload::Bass(payload) => {
            if expected_track != "bass" || !(1..=3).contains(&payload.schema_version) {
                return Err("The bass transcription schema or track is not supported.".into());
            }
            validate_tempo_map(&payload.tempo_map)?;
            if !matches!(payload.tuning.len(), 4 | 5)
                || payload.tuning.windows(2).any(|notes| notes[1] <= notes[0])
            {
                return Err("The bass transcription tuning is invalid.".into());
            }
            let mut ids = std::collections::HashSet::new();
            for event in &payload.events {
                validate_note_event(event)?;
                if !ids.insert(event.id.as_str()) {
                    return Err("The bass transcription contains duplicate event IDs.".into());
                }
            }
            for event in &payload.source_events {
                validate_note_event(event)?;
            }
            for note in &payload.tab {
                if !ids.contains(note.note_event_id.as_str())
                    || note.string_index >= payload.tuning.len()
                    || note.fret > 36
                    || !note.start_beat.is_finite()
                    || !note.duration_beats.is_finite()
                    || note.duration_beats <= 0.0
                {
                    return Err("The bass tablature contains an invalid note.".into());
                }
            }
        }
        TranscriptionPayload::Drums(payload) => {
            if expected_track != "drums" || !(1..=2).contains(&payload.schema_version) {
                return Err("The drum transcription schema or track is not supported.".into());
            }
            validate_tempo_map(&payload.tempo_map)?;
            let mut ids = std::collections::HashSet::new();
            for event in &payload.events {
                validate_drum_event(event)?;
                if !ids.insert(event.id.as_str()) {
                    return Err("The drum transcription contains duplicate event IDs.".into());
                }
            }
            for event in &payload.source_events {
                validate_drum_event(event)?;
            }
        }
    }
    Ok(())
}

fn validate_note_event(event: &NoteEventPayload) -> Result<(), String> {
    if event.id.trim().is_empty()
        || !event.detected_start_seconds.is_finite()
        || !event.detected_end_seconds.is_finite()
        || event.detected_start_seconds < 0.0
        || event.detected_end_seconds <= event.detected_start_seconds
        || event
            .quantized_start_beat
            .is_some_and(|value| !value.is_finite())
        || event
            .quantized_duration_beats
            .is_some_and(|value| !value.is_finite() || value <= 0.0)
        || event.midi_pitch > 127
        || !(1..=127).contains(&event.velocity)
        || event
            .confidence
            .is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
    {
        return Err("The bass transcription contains an invalid event.".into());
    }
    let duration = event.detected_end_seconds - event.detected_start_seconds;
    if event.pitch_bends.iter().any(|bend| {
        !bend.time_offset_seconds.is_finite()
            || bend.time_offset_seconds < 0.0
            || bend.time_offset_seconds > duration
            || !bend.semitones.is_finite()
            || !(-12.0..=12.0).contains(&bend.semitones)
    }) {
        return Err("The bass transcription contains an invalid pitch bend.".into());
    }
    Ok(())
}

fn validate_drum_event(event: &DrumEventPayload) -> Result<(), String> {
    if event.id.trim().is_empty()
        || !event.detected_time_seconds.is_finite()
        || event.detected_time_seconds < 0.0
        || event.quantized_beat.is_some_and(|value| !value.is_finite())
        || !(1..=127).contains(&event.velocity)
        || event
            .confidence
            .is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
    {
        Err("The drum transcription contains an invalid event.".into())
    } else {
        Ok(())
    }
}

fn validate_tempo_map(tempo: &TempoMapPayload) -> Result<(), String> {
    if !tempo.bpm.is_finite()
        || !(20.0..=400.0).contains(&tempo.bpm)
        || tempo.time_signature.numerator == 0
        || tempo.time_signature.denominator == 0
        || tempo
            .beats
            .iter()
            .any(|beat| !beat.time_seconds.is_finite() || beat.time_seconds < 0.0)
        || tempo.beats.windows(2).any(|beats| {
            beats[1].time_seconds <= beats[0].time_seconds
                || beats[1].beat_index <= beats[0].beat_index
        })
        || tempo
            .tempo_candidates
            .iter()
            .any(|candidate| !candidate.is_finite() || !(20.0..=400.0).contains(candidate))
    {
        Err("The transcription tempo map is invalid.".into())
    } else {
        Ok(())
    }
}

fn validate_unit_value(value: f64, label: &str) -> Result<(), String> {
    if value.is_finite() && (0.0..=1.0).contains(&value) {
        Ok(())
    } else {
        Err(format!("The session {label} is invalid."))
    }
}

fn normalized_source_name(source_name: &str) -> String {
    Path::new(source_name)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("Untitled audio")
        .to_string()
}

fn sanitize_session_name(source_name: &str) -> String {
    let normalized = normalized_source_name(source_name);
    let stem = Path::new(&normalized)
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("session");
    let sanitized = stem
        .chars()
        .map(|character| {
            if character.is_alphanumeric() || matches!(character, ' ' | '-' | '_') {
                character
            } else {
                '-'
            }
        })
        .collect::<String>();
    let trimmed = sanitized.trim_matches([' ', '-', '_']);
    if trimmed.is_empty() {
        "session".into()
    } else {
        trimmed.chars().take(80).collect()
    }
}

fn normalized_session_path(requested_path: &Path) -> Result<PathBuf, String> {
    let file_name = requested_path
        .file_name()
        .ok_or("The selected session destination has no folder name.")?;
    if requested_path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("stemstudio"))
    {
        return Ok(requested_path.to_path_buf());
    }
    let mut session_name = file_name.to_os_string();
    session_name.push(".stemstudio");
    Ok(requested_path.with_file_name(session_name))
}

fn replace_session_directory(temporary_path: &Path, session_path: &Path) -> Result<(), String> {
    if !session_path.exists() {
        return fs::rename(temporary_path, session_path)
            .map_err(|error| format!("Unable to finalize the session folder: {error}"));
    }

    let parent = session_path
        .parent()
        .ok_or("The selected session destination has no parent folder.")?;
    let backup_name = format!(
        ".{}.{}.backup",
        session_path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("session.stemstudio"),
        Uuid::new_v4()
    );
    let backup_path = parent.join(backup_name);
    fs::rename(session_path, &backup_path)
        .map_err(|error| format!("Unable to prepare the existing session for update: {error}"))?;
    if let Err(error) = fs::rename(temporary_path, session_path) {
        let restoration = fs::rename(&backup_path, session_path);
        return Err(match restoration {
            Ok(()) => format!("Unable to update the session folder: {error}"),
            Err(restoration_error) => format!(
                "Unable to update the session folder ({error}) or restore its backup at {} ({restoration_error}).",
                backup_path.display()
            ),
        });
    }
    if let Err(error) = fs::remove_dir_all(&backup_path) {
        eprintln!(
            "Unable to remove the previous session backup at {}: {error}",
            backup_path.display()
        );
    }
    Ok(())
}

fn read_optional_metadata(path: &Path) -> Option<Value> {
    let metadata = fs::metadata(path).ok()?;
    if metadata.len() > MAX_MANIFEST_BYTES {
        return None;
    }
    let mut value = serde_json::from_str::<Value>(&fs::read_to_string(path).ok()?).ok()?;
    if let Some(object) = value.as_object_mut() {
        object.remove("sourcePath");
    }
    Some(value)
}

fn validate_input(input: &str) -> Result<(), String> {
    let path = Path::new(input);
    if !path.is_file() {
        return Err("Audio file could not be found.".into());
    }
    match path.extension().and_then(|value| value.to_str()) {
        Some(extension)
            if extension.eq_ignore_ascii_case("mp3") || extension.eq_ignore_ascii_case("wav") =>
        {
            Ok(())
        }
        _ => Err("Only MP3 and WAV files are supported.".into()),
    }
}

#[cfg(test)]
mod session_tests {
    use super::*;

    fn test_state() -> SessionState {
        let track = TrackMixState {
            volume: 0.75,
            muted: false,
            solo: false,
        };
        SessionState {
            current_time_seconds: 42.5,
            start_marker_seconds: 18.0,
            master_volume: 0.6,
            tracks: StemTrackStates {
                vocals: track.clone(),
                drums: track.clone(),
                bass: track.clone(),
                other: track,
            },
        }
    }

    #[test]
    fn bass_tuning_serializes_to_engine_cli_values() {
        assert_eq!(BassTuning::Eadg.as_str(), "eadg");
        assert_eq!(BassTuning::Beadg.as_str(), "beadg");
    }

    #[test]
    fn bass_engine_serializes_to_engine_cli_values() {
        assert_eq!(BassTranscriptionEngine::BasicPitch.as_str(), "basic-pitch");
        assert_eq!(BassTranscriptionEngine::Torchcrepe.as_str(), "torchcrepe");
    }

    #[test]
    fn session_round_trip_copies_stems_and_restores_relative_paths() {
        let root = std::env::temp_dir().join(format!("stem-studio-test-{}", Uuid::new_v4()));
        let project = root.join("project");
        let destination = root.join("saved");
        fs::create_dir_all(&project).unwrap();
        fs::create_dir_all(&destination).unwrap();
        for name in ["vocals", "drums", "bass", "other"] {
            fs::write(project.join(format!("{name}.wav")), [1_u8, 2, 3]).unwrap();
        }
        let transcription = project.join("transcription");
        fs::create_dir(&transcription).unwrap();
        fs::write(
            transcription.join("bass.json"),
            r#"{"schemaVersion":1,"track":"bass","events":[],"tab":[],"tempoMap":{"bpm":120,"beats":[],"timeSignature":{"numerator":4,"denominator":4}},"tuning":[28,33,38,43],"warnings":[]}"#,
        )
        .unwrap();
        fs::write(transcription.join("bass.mid"), [1_u8, 2, 3]).unwrap();
        fs::write(transcription.join("bass.musicxml"), b"<score-partwise/>").unwrap();
        fs::write(
            project.join("source.json"),
            r#"{"sourcePath":"/private/song.mp3","model":"test-model"}"#,
        )
        .unwrap();

        let session_path = destination.join("My Song.stemstudio");
        let saved = save_session_files(
            &project,
            &session_path,
            "/music/My Song.mp3",
            SeparationQuality::High,
            test_state(),
        )
        .unwrap();
        let restored = load_session_files(Path::new(&saved.manifest_path)).unwrap();

        assert!(Path::new(&saved.session_path).is_dir());
        assert_eq!(restored.source_name, "My Song.mp3");
        assert_eq!(restored.quality_profile.as_str(), "high");
        assert_eq!(restored.state.current_time_seconds, 42.5);
        assert!(Path::new(&restored.stems.vocals).starts_with(&restored.session_path));
        let restored_bass = restored.transcriptions.bass.as_ref().unwrap();
        assert!(Path::new(&restored_bass.events_file).is_file());
        assert!(matches!(
            restored_bass.transcription,
            TranscriptionPayload::Bass(_)
        ));
        let manifest: Value =
            serde_json::from_str(&fs::read_to_string(Path::new(&saved.manifest_path)).unwrap())
                .unwrap();
        assert_eq!(manifest["stems"]["vocals"], "vocals.wav");
        assert_eq!(
            manifest["transcriptions"]["bass"]["eventsFile"],
            "transcription/bass.json"
        );
        assert!(manifest["engineMetadata"].get("sourcePath").is_none());

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn saving_an_existing_session_updates_the_same_folder() {
        let root = std::env::temp_dir().join(format!("stem-studio-test-{}", Uuid::new_v4()));
        let project = root.join("project");
        let destination = root.join("saved");
        let session_path = destination.join("My Song.stemstudio");
        fs::create_dir_all(&project).unwrap();
        fs::create_dir_all(&destination).unwrap();
        for name in ["vocals", "drums", "bass", "other"] {
            fs::write(project.join(format!("{name}.wav")), [1_u8, 2, 3]).unwrap();
        }

        let first = save_session_files(
            &project,
            &session_path,
            "/music/My Song.mp3",
            SeparationQuality::Standard,
            test_state(),
        )
        .unwrap();
        let transcription = session_path.join("transcription");
        fs::create_dir(&transcription).unwrap();
        fs::write(
            transcription.join("drums.json"),
            r#"{"schemaVersion":1,"track":"drums","events":[],"tempoMap":{"bpm":120,"beats":[],"timeSignature":{"numerator":4,"denominator":4}},"warnings":[]}"#,
        )
        .unwrap();
        fs::write(transcription.join("drums.mid"), [4_u8, 5, 6]).unwrap();
        fs::write(transcription.join("drums.musicxml"), b"<score-partwise/>").unwrap();
        let mut updated_state = test_state();
        updated_state.current_time_seconds = 99.0;

        let updated = save_session_files(
            &session_path,
            &session_path,
            "/music/My Song.mp3",
            SeparationQuality::Standard,
            updated_state,
        )
        .unwrap();
        let restored = load_session_files(Path::new(&updated.manifest_path)).unwrap();
        let session_folders = fs::read_dir(&destination)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .path()
                    .extension()
                    .is_some_and(|value| value == "stemstudio")
            })
            .count();

        assert_eq!(first.session_path, updated.session_path);
        assert_eq!(session_folders, 1);
        assert_eq!(restored.state.current_time_seconds, 99.0);
        assert!(restored.transcriptions.drums.is_some());

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejects_invalid_mix_values_and_parent_directory_paths() {
        let mut state = test_state();
        state.master_volume = 1.2;
        assert!(validate_session_state(&state).is_err());

        let root = std::env::temp_dir().join(format!("stem-studio-test-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        assert!(resolve_session_stem(&root, "../vocals.wav", "vocals").is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejects_invalid_typed_transcription_payloads() {
        let invalid = serde_json::from_str::<TranscriptionPayload>(
            r#"{"track":"bass","schemaVersion":3,"events":[{"id":"n1","detectedStartSeconds":1,"detectedEndSeconds":0.5,"quantizedStartBeat":0,"quantizedDurationBeats":1,"midiPitch":40,"velocity":100,"confidence":0.8}],"tab":[],"tempoMap":{"bpm":120,"beats":[],"timeSignature":{"numerator":4,"denominator":4}},"tuning":[28,33,38,43],"warnings":[]}"#,
        )
        .unwrap();
        assert!(validate_transcription(&invalid, "bass").is_err());
        assert!(validate_transcription(&invalid, "drums").is_err());
    }

    #[test]
    fn project_cache_is_bounded() {
        let root = std::env::temp_dir().join(format!("stem-studio-cache-test-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        for index in 0..7 {
            fs::create_dir(root.join(format!("project-{index}"))).unwrap();
        }
        cleanup_project_cache(&root);
        assert_eq!(fs::read_dir(&root).unwrap().count(), MAX_CACHED_PROJECTS);
        fs::remove_dir_all(root).unwrap();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(RunnerState::default())
        .invoke_handler(tauri::generate_handler![
            separate_audio,
            cancel_separation,
            transcribe_track,
            requantize_transcription,
            export_transcription_file,
            save_session,
            load_session
        ])
        .run(tauri::generate_context!())
        .expect("error while running Stem Studio");
}
