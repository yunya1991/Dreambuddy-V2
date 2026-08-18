use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Serialize)]
struct CmdResult {
    ok: bool,
    code: i32,
    stdout: String,
    stderr: String,
}

fn _uid() -> Result<String, String> {
    let out = Command::new("id")
        .arg("-u")
        .output()
        .map_err(|e| format!("id_failed:{e}"))?;
    let code = out.status.code().unwrap_or(-1);
    if !out.status.success() {
        return Err(format!(
            "id_failed:code={code} stderr={}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn _home_dir() -> Result<PathBuf, String> {
    let v = std::env::var("HOME").map_err(|_| "missing_home".to_string())?;
    Ok(PathBuf::from(v))
}

fn _canonicalize_dir(p: &str) -> Result<PathBuf, String> {
    let pb = PathBuf::from(p);
    let c = pb
        .canonicalize()
        .map_err(|e| format!("project_dir_not_found:{e}"))?;
    if !c.is_dir() {
        return Err("project_dir_not_a_directory".to_string());
    }
    Ok(c)
}

fn _is_allowed_label(label: &str) -> bool {
    let s = label.trim();
    if s.is_empty() {
        return false;
    }
    let ok_prefix = s.starts_with("com.ft.ml_trade_service.")
        || s.starts_with("com.ft.dashboard.")
        || s == "com.ft.explore.ml_trade_service"
        || s.starts_with("com.ft.explore.dashboard.");
    if !ok_prefix {
        return false;
    }
    s.chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_')
}

#[tauri::command]
fn guess_project_dir() -> Option<String> {
    let mut cur = std::env::current_dir().ok()?;
    for _ in 0..8 {
        let cand = cur.join("ml_trade_service.py");
        if cand.exists() {
            return Some(cur.to_string_lossy().to_string());
        }
        let parent = cur.parent()?.to_path_buf();
        cur = parent;
    }
    None
}

#[tauri::command]
fn run_launchd_script(project_dir: String, script_rel: String, args: Vec<String>) -> Result<CmdResult, String> {
    let project = _canonicalize_dir(&project_dir)?;
    let rel = script_rel.trim().replace('\\', "/");
    let allowed = matches!(
        rel.as_str(),
        "ops/launchd/install_8092.sh"
            | "ops/launchd/uninstall_8092.sh"
            | "ops/launchd/install_dashboard.sh"
            | "ops/launchd/uninstall_dashboard.sh"
    );
    if !allowed {
        return Err("script_not_allowed".to_string());
    }

    let script_path = project.join(rel);
    let script_path = script_path
        .canonicalize()
        .map_err(|e| format!("script_not_found:{e}"))?;
    if !script_path.starts_with(&project) {
        return Err("script_path_escape".to_string());
    }

    let out = Command::new("bash")
        .arg(&script_path)
        .args(args)
        .current_dir(&project)
        .output()
        .map_err(|e| format!("script_exec_failed:{e}"))?;

    Ok(CmdResult {
        ok: out.status.success(),
        code: out.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&out.stdout).to_string(),
        stderr: String::from_utf8_lossy(&out.stderr).to_string(),
    })
}

#[tauri::command]
fn launchctl_print(label: String) -> Result<CmdResult, String> {
    if !_is_allowed_label(&label) {
        return Err("label_not_allowed".to_string());
    }
    let uid = _uid()?;
    let target = format!("gui/{uid}/{}", label.trim());
    let out = Command::new("launchctl")
        .arg("print")
        .arg(&target)
        .output()
        .map_err(|e| format!("launchctl_failed:{e}"))?;
    Ok(CmdResult {
        ok: out.status.success(),
        code: out.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&out.stdout).to_string(),
        stderr: String::from_utf8_lossy(&out.stderr).to_string(),
    })
}

#[tauri::command]
fn launchctl_kickstart(label: String) -> Result<CmdResult, String> {
    if !_is_allowed_label(&label) {
        return Err("label_not_allowed".to_string());
    }
    let uid = _uid()?;
    let target = format!("gui/{uid}/{}", label.trim());
    let out = Command::new("launchctl")
        .arg("kickstart")
        .arg("-k")
        .arg(&target)
        .output()
        .map_err(|e| format!("launchctl_failed:{e}"))?;
    Ok(CmdResult {
        ok: out.status.success(),
        code: out.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&out.stdout).to_string(),
        stderr: String::from_utf8_lossy(&out.stderr).to_string(),
    })
}

#[tauri::command]
fn launchctl_bootout_by_label(label: String) -> Result<CmdResult, String> {
    if !_is_allowed_label(&label) {
        return Err("label_not_allowed".to_string());
    }
    let uid = _uid()?;
    let home = _home_dir()?;
    let plist = home
        .join("Library")
        .join("LaunchAgents")
        .join(format!("{}.plist", label.trim()));
    let out = Command::new("launchctl")
        .arg("bootout")
        .arg(format!("gui/{uid}"))
        .arg(plist.to_string_lossy().to_string())
        .output()
        .map_err(|e| format!("launchctl_failed:{e}"))?;
    Ok(CmdResult {
        ok: out.status.success(),
        code: out.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&out.stdout).to_string(),
        stderr: String::from_utf8_lossy(&out.stderr).to_string(),
    })
}

fn _tail_text(content: &str, max_lines: usize) -> String {
    if max_lines == 0 {
        return String::new();
    }
    let mut lines: Vec<&str> = content.lines().collect();
    if lines.len() > max_lines {
        lines.drain(0..(lines.len() - max_lines));
    }
    lines.join("\n")
}

#[tauri::command]
fn read_text_tail(path: String, max_lines: u32, max_bytes: u32) -> Result<String, String> {
    let p = PathBuf::from(path);
    let meta = std::fs::metadata(&p).map_err(|_| "file_not_found".to_string())?;
    if !meta.is_file() {
        return Err("not_a_file".to_string());
    }
    let max_b = (max_bytes as usize).clamp(1, 2_000_000);
    let bytes = std::fs::read(&p).map_err(|_| "file_read_failed".to_string())?;
    let slice = if bytes.len() > max_b {
        &bytes[(bytes.len() - max_b)..]
    } else {
        &bytes[..]
    };
    let text = String::from_utf8_lossy(slice).to_string();
    Ok(_tail_text(&text, (max_lines as usize).clamp(1, 2000)))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    use tauri::{
        menu::{MenuBuilder, MenuItem},
        tray::TrayIconBuilder,
        WebviewUrl,
        WebviewWindowBuilder,
        Manager,
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            guess_project_dir,
            run_launchd_script,
            launchctl_print,
            launchctl_kickstart,
            launchctl_bootout_by_label,
            read_text_tail
        ])
        .setup(|app| {
            let _ = WebviewWindowBuilder::new(
                app,
                "agent",
                WebviewUrl::App("index.html".into()),
            )
            .title("交易 Ai Agent 控制台")
            .build();

            let open = MenuItem::with_id(app, "open", "打开控制台", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = MenuBuilder::new(app).items(&[&open, &quit]).build()?;

            let _tray = TrayIconBuilder::with_id("tray")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => {
                        if let Some(w) = app.get_webview_window("agent") {
                            let _ = w.show().ok();
                            let _ = w.set_focus().ok();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
