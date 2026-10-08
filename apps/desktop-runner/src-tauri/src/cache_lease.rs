//! Cache deletion and native execution share the same OS lock as runner-core.
use std::fs::{self, File, OpenOptions};
use std::path::Path;

pub(crate) struct ReadLease {
    _file: File,
}
impl Drop for ReadLease {
    fn drop(&mut self) {
        let _ = self._file.unlock();
    }
}
impl ReadLease {
    pub(crate) fn for_managed_model(path: &Path) -> Result<Option<Self>, String> {
        let target = fs::canonicalize(path).map_err(|_| "Could not resolve selected model path")?;
        let parent = target
            .parent()
            .ok_or("Model path has no parent directory")?;
        if fs::symlink_metadata(parent.join(".infergrade-cache-control")).is_ok() {
            Self::acquire(parent).map(Some)
        } else {
            Ok(None)
        }
    }

    pub(crate) fn acquire(root: &Path) -> Result<Self, String> {
        if fs::symlink_metadata(root)
            .map(|m| m.file_type().is_symlink())
            .unwrap_or(false)
        {
            return Err("Cache control refuses a linked cache directory.".into());
        }
        let directory = root.join(".infergrade-cache-control");
        if fs::symlink_metadata(&directory)
            .map(|m| m.file_type().is_symlink())
            .unwrap_or(false)
        {
            return Err("Cache control refuses linked metadata.".into());
        }
        fs::create_dir_all(&directory).map_err(|_| "Could not prepare cache control.")?;
        let path = directory.join("cache-lease.lock");
        if fs::symlink_metadata(&path)
            .map(|m| !m.is_file() || m.file_type().is_symlink())
            .unwrap_or(false)
        {
            return Err("Invalid cache lock.".into());
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
        }
        let file = options
            .open(path)
            .map_err(|_| "Could not open cache lease.")?;
        if !file
            .metadata()
            .map_err(|_| "Could not inspect cache lease.")?
            .is_file()
        {
            return Err("Invalid cache lock.".into());
        }
        file.try_lock_shared()
            .map_err(|_| "Cache cleanup is active. Try again after it finishes.")?;
        Ok(Self { _file: file })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_readers_block_exclusive_cleanup_until_every_reader_drops() {
        let root = std::env::temp_dir().join(format!(
            "infergrade-cache-lease-test-{}",
            std::process::id()
        ));
        let first = ReadLease::acquire(&root).expect("first reader");
        let second = ReadLease::acquire(&root).expect("second reader");
        let exclusive = OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join(".infergrade-cache-control/cache-lease.lock"))
            .expect("cleanup handle");
        assert!(exclusive.try_lock().is_err());
        drop(first);
        assert!(exclusive.try_lock().is_err());
        drop(second);
        exclusive.try_lock().expect("cleanup after readers exit");
        assert!(ReadLease::acquire(&root).is_err());
        // Parallel process tests may fork with this descriptor briefly inherited.
        // Match production Python cleanup: unlock explicitly before closing.
        exclusive.unlock().expect("release cleanup lock");
        drop(exclusive);
        ReadLease::acquire(&root).expect("reader after cleanup");
        let _ = fs::remove_dir_all(root);
    }
    #[test]
    fn native_reader_and_python_cleanup_use_the_same_os_lock() {
        let root = std::env::temp_dir().join(format!(
            "infergrade-cache-python-interop-{}",
            std::process::id()
        ));
        let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../python/runner-core/src");
        let probe = "import sys;from infergrade.cache_control import process_lock\ntry:\n with process_lock(sys.argv[1], shared=False, blocking=False): pass\nexcept RuntimeError:\n sys.exit(23)";
        let check = || {
            std::process::Command::new(if cfg!(windows) { "python" } else { "python3" })
                .env("PYTHONPATH", &source)
                .args(["-B", "-c", probe])
                .arg(&root)
                .output()
                .expect("Python lock probe")
                .status
                .code()
        };
        let reader = ReadLease::acquire(&root).expect("native reader");
        assert_eq!(check(), Some(23), "Python must refuse native-held cache");
        drop(reader);
        assert_eq!(
            check(),
            Some(0),
            "Python may clean after native reader exits"
        );
        let _ = fs::remove_dir_all(root);
    }
    #[test]
    fn selected_custom_managed_model_keeps_its_parent_cache_leased() {
        let root = std::env::temp_dir().join(format!(
            "infergrade-custom-model-lease-{}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        let model = root.join("owned.gguf");
        fs::write(&model, b"test model").unwrap();
        let setup = ReadLease::acquire(&root).unwrap();
        drop(setup);
        let selected = ReadLease::for_managed_model(&model)
            .unwrap()
            .expect("managed model lease");
        let cleanup = OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join(".infergrade-cache-control/cache-lease.lock"))
            .unwrap();
        assert!(cleanup.try_lock().is_err());
        drop(selected);
        cleanup.try_lock().unwrap();
        cleanup.unlock().unwrap();
        drop(cleanup);
        let _ = fs::remove_dir_all(root);
    }
}
