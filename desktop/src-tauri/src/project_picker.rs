use std::path::{Path, PathBuf};

pub(crate) fn canonical_existing_directory(path: &Path) -> Result<String, String> {
    if !path.is_absolute() {
        return Err("selected project directory was not absolute".to_owned());
    }
    let canonical = path
        .canonicalize()
        .map_err(|_| "selected project directory is unavailable".to_owned())?;
    let metadata = canonical
        .metadata()
        .map_err(|_| "selected project directory is unavailable".to_owned())?;
    if !metadata.is_dir() {
        return Err("selected project path is not a directory".to_owned());
    }
    canonical
        .to_str()
        .map(str::to_owned)
        .ok_or_else(|| "selected project directory is not valid UTF-8".to_owned())
}

#[cfg(target_os = "macos")]
pub fn pick_project_directory() -> Result<Option<String>, String> {
    use objc2::MainThreadMarker;
    use objc2_app_kit::{NSModalResponseCancel, NSModalResponseOK, NSOpenPanel};

    let mtm = MainThreadMarker::new()
        .ok_or_else(|| "project directory picker must run on the main thread".to_owned())?;
    let panel = NSOpenPanel::openPanel(mtm);
    panel.setCanChooseDirectories(true);
    panel.setCanChooseFiles(false);
    panel.setAllowsMultipleSelection(false);
    panel.setResolvesAliases(true);
    let response = panel.runModal();
    if response == NSModalResponseCancel {
        return Ok(None);
    }
    if response != NSModalResponseOK {
        return Err("project directory picker did not complete".to_owned());
    }
    let urls = panel.URLs();
    let url = urls
        .firstObject()
        .ok_or_else(|| "project directory picker returned no directory".to_owned())?;
    let path = url
        .path()
        .ok_or_else(|| "project directory picker returned no filesystem path".to_owned())?;
    canonical_existing_directory(&PathBuf::from(path.to_string())).map(Some)
}

#[cfg(not(target_os = "macos"))]
pub fn pick_project_directory() -> Result<Option<String>, String> {
    Err("project directory selection is available only on macOS".to_owned())
}

#[cfg(test)]
mod tests {
    use super::canonical_existing_directory;
    use std::fs;

    #[test]
    fn canonical_directory_validation_rejects_relative_and_files() {
        assert!(canonical_existing_directory(std::path::Path::new("relative")).is_err());
        let root =
            std::env::temp_dir().join(format!("dialektike-project-picker-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let file = root.join("not-a-directory");
        fs::write(&file, b"fixture").unwrap();
        assert!(canonical_existing_directory(&file).is_err());
        assert_eq!(
            canonical_existing_directory(&root).unwrap(),
            root.canonicalize().unwrap().to_str().unwrap()
        );
        fs::remove_file(file).unwrap();
        fs::remove_dir(root).unwrap();
    }
}
