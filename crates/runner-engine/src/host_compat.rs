//! Host facts that decide which managed llama.cpp build can run on this machine.
//!
//! Linux builds differ in the C library (glibc) and C++ runtime (libstdc++)
//! they were linked against, and GPU builds need host drivers. These checks run
//! before anything is downloaded, so an incompatible build is never offered.

use serde_json::Value;
use std::path::Path;
use std::process::Command;

/// What the host provides. `None` means "unknown": recommendation does not
/// reject on unknown facts, but installation still checks what it can.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HostFacts {
    /// glibc version, e.g. "2.35".
    pub glibc: Option<String>,
    /// Highest `GLIBCXX_3.4.N` minor provided by the system libstdc++.
    pub glibcxx_minor: Option<u32>,
    /// Whether the Vulkan loader (`libvulkan.so.1`) is installed.
    pub vulkan_loader: Option<bool>,
}

pub fn detect_host_facts() -> HostFacts {
    if !cfg!(target_os = "linux") {
        return HostFacts::default();
    }
    HostFacts {
        glibc: linux_glibc_version(),
        glibcxx_minor: linux_glibcxx_minor(),
        vulkan_loader: Some(linux_vulkan_loader_present()),
    }
}

pub fn linux_glibc_version() -> Option<String> {
    let output = Command::new("getconf")
        .arg("GNU_LIBC_VERSION")
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8_lossy(&output.stdout)
        .split_whitespace()
        .last()
        .map(str::to_string)
}

fn ldconfig_paths(library: &str) -> Vec<String> {
    let arch_tag = if cfg!(target_arch = "aarch64") {
        "AArch64"
    } else {
        "x86-64"
    };
    for program in ["ldconfig", "/sbin/ldconfig", "/usr/sbin/ldconfig"] {
        if let Ok(output) = Command::new(program).arg("-p").output() {
            if output.status.success() {
                return parse_ldconfig_paths(
                    &String::from_utf8_lossy(&output.stdout),
                    library,
                    arch_tag,
                );
            }
        }
    }
    Vec::new()
}

/// Parse `ldconfig -p` lines such as
/// `libstdc++.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libstdc++.so.6`.
pub fn parse_ldconfig_paths(listing: &str, library: &str, arch_tag: &str) -> Vec<String> {
    listing
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            let (left, path) = line.split_once("=>")?;
            let name = left.split_whitespace().next()?;
            (name == library && left.contains(arch_tag)).then(|| path.trim().to_string())
        })
        .collect()
}

const LIBRARY_DIRS: [&str; 6] = [
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib/aarch64-linux-gnu",
    "/usr/lib64",
    "/lib64",
    "/usr/lib",
    "/lib",
];

pub fn linux_glibcxx_minor() -> Option<u32> {
    let mut candidates = ldconfig_paths("libstdc++.so.6");
    candidates.extend(
        LIBRARY_DIRS
            .iter()
            .map(|dir| format!("{dir}/libstdc++.so.6")),
    );
    candidates.iter().find_map(|path| {
        std::fs::read(path)
            .ok()
            .and_then(|bytes| max_glibcxx_minor(&bytes))
    })
}

/// Highest `GLIBCXX_3.4.N` version string embedded in a libstdc++ image.
pub fn max_glibcxx_minor(bytes: &[u8]) -> Option<u32> {
    const NEEDLE: &[u8] = b"GLIBCXX_3.4.";
    let mut best = None;
    let mut index = 0;
    while index + NEEDLE.len() <= bytes.len() {
        let Some(offset) = bytes[index..]
            .windows(NEEDLE.len())
            .position(|window| window == NEEDLE)
        else {
            break;
        };
        let start = index + offset + NEEDLE.len();
        let end = bytes[start..]
            .iter()
            .position(|byte| !byte.is_ascii_digit())
            .map_or(bytes.len(), |length| start + length);
        if end > start {
            if let Ok(minor) = std::str::from_utf8(&bytes[start..end])
                .unwrap_or("")
                .parse::<u32>()
            {
                best = Some(best.map_or(minor, |current: u32| current.max(minor)));
            }
        }
        index = start;
    }
    best
}

pub fn linux_vulkan_loader_present() -> bool {
    !ldconfig_paths("libvulkan.so.1").is_empty()
        || LIBRARY_DIRS
            .iter()
            .any(|dir| Path::new(&format!("{dir}/libvulkan.so.1")).exists())
}

fn version_parts(value: &str) -> Option<Vec<u32>> {
    value
        .split('.')
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .ok()
}

/// `3.4.30` -> 30. Only the libstdc++ 3.4.x series is versioned this way.
pub fn glibcxx_requirement_minor(requirement: &str) -> Option<u32> {
    match version_parts(requirement)?.as_slice() {
        [3, 4, minor] => Some(*minor),
        _ => None,
    }
}

/// Why `entry` cannot run on a host with `facts`, or `None` when nothing known
/// rules it out.
pub fn entry_host_incompatibility(entry: &Value, facts: &HostFacts) -> Option<String> {
    if entry.pointer("/platform/system").and_then(Value::as_str) != Some("linux") {
        return None;
    }
    if let (Some(required), Some(observed)) = (
        entry
            .pointer("/platform/minimum_glibc")
            .and_then(Value::as_str),
        facts.glibc.as_deref(),
    ) {
        if let (Some(required_parts), Some(observed_parts)) =
            (version_parts(required), version_parts(observed))
        {
            if observed_parts < required_parts {
                return Some(format!(
                    "needs glibc {required}, but this machine has glibc {observed}"
                ));
            }
        }
    }
    if let (Some(required), Some(observed)) = (
        entry
            .pointer("/platform/minimum_glibcxx")
            .and_then(Value::as_str)
            .and_then(glibcxx_requirement_minor),
        facts.glibcxx_minor,
    ) {
        if observed < required {
            return Some(format!(
                "needs libstdc++ GLIBCXX_3.4.{required}, but this machine's libstdc++ stops at GLIBCXX_3.4.{observed}"
            ));
        }
    }
    if entry
        .pointer("/platform/requires_vulkan_loader")
        .and_then(Value::as_bool)
        == Some(true)
        && facts.vulkan_loader == Some(false)
    {
        return Some(
            "needs the Vulkan loader (libvulkan.so.1), which is not installed. Install your GPU's Vulkan driver, e.g. `sudo apt install mesa-vulkan-drivers libvulkan1` (Debian/Ubuntu) or `sudo dnf install mesa-vulkan-drivers vulkan-loader` (Fedora)"
                .to_string(),
        );
    }
    None
}

/// Display-class PCI device that llama.cpp's Vulkan build should drive.
/// AMD GPUs (integrated or discrete) qualify; Intel qualifies only for
/// discrete Arc parts, because integrated Intel graphics are usually slower
/// than the CPU for this workload.
pub fn classify_pci_gpu(vendor: u32, device: u32, class: u32) -> Option<&'static str> {
    if class >> 16 != 0x03 {
        return None;
    }
    match vendor {
        0x1002 => Some("amd"),
        0x8086 if is_intel_discrete_gpu(device) => Some("intel"),
        _ => None,
    }
}

/// Intel Arc Alchemist (0x56xx) and Battlemage (0xe20x) discrete device IDs.
pub fn is_intel_discrete_gpu(device: u32) -> bool {
    (0x5690..=0x56ff).contains(&device) || (0xe200..=0xe2ff).contains(&device)
}

/// Classify Windows display adapter names (one per line).
pub fn classify_windows_adapters(names: &str) -> Option<&'static str> {
    let mut found_intel = false;
    for name in names.lines().map(str::trim).filter(|name| !name.is_empty()) {
        let lowered = name.to_ascii_lowercase();
        if lowered.contains("radeon") || lowered.starts_with("amd ") {
            return Some("amd");
        }
        if lowered.contains("intel") && lowered.contains("arc") {
            found_intel = true;
        }
    }
    found_intel.then_some("intel")
}

fn read_hex(path: &Path) -> Option<u32> {
    let text = std::fs::read_to_string(path).ok()?;
    u32::from_str_radix(text.trim().trim_start_matches("0x"), 16).ok()
}

/// Detect an AMD or Intel Arc GPU that the Vulkan build can use.
pub fn detect_vulkan_gpu_vendor() -> Option<&'static str> {
    if cfg!(target_os = "linux") {
        let entries = std::fs::read_dir("/sys/class/drm").ok()?;
        let mut found = None;
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if !name.starts_with("card") || name.contains('-') {
                continue;
            }
            let device_dir = entry.path().join("device");
            if let (Some(vendor), Some(device), Some(class)) = (
                read_hex(&device_dir.join("vendor")),
                read_hex(&device_dir.join("device")),
                read_hex(&device_dir.join("class")),
            ) {
                match classify_pci_gpu(vendor, device, class) {
                    Some("amd") => return Some("amd"),
                    Some(other) => found = Some(other),
                    None => {}
                }
            }
        }
        return found;
    }
    if cfg!(target_os = "windows") {
        let output = Command::new("powershell")
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance Win32_VideoController).Name",
            ])
            .output()
            .ok()?;
        if !output.status.success() {
            return None;
        }
        return classify_windows_adapters(&String::from_utf8_lossy(&output.stdout));
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn linux_entry(platform: Value) -> Value {
        let mut platform = platform;
        platform["system"] = json!("linux");
        json!({"platform": platform})
    }

    fn ubuntu22() -> HostFacts {
        HostFacts {
            glibc: Some("2.35".into()),
            glibcxx_minor: Some(30),
            vulkan_loader: Some(true),
        }
    }

    #[test]
    fn glibcxx_scan_finds_the_highest_minor() {
        let image =
            b"\0GLIBCXX_3.4\0GLIBCXX_3.4.9\0GLIBCXX_3.4.30\0GLIBCXX_3.4.29\0CXXABI_1.3.13\0";
        assert_eq!(max_glibcxx_minor(image), Some(30));
        assert_eq!(max_glibcxx_minor(b"GLIBCXX_3.4"), None);
        assert_eq!(max_glibcxx_minor(b"tail GLIBCXX_3.4.32"), Some(32));
        assert_eq!(glibcxx_requirement_minor("3.4.30"), Some(30));
        assert_eq!(glibcxx_requirement_minor("3.5.1"), None);
    }

    #[test]
    fn ldconfig_listing_is_filtered_by_name_and_architecture() {
        let listing = "1234 libs found in cache `/etc/ld.so.cache'\n\
            \tlibvulkan.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libvulkan.so.1\n\
            \tlibvulkan.so.1 (libc6) => /lib/i386-linux-gnu/libvulkan.so.1\n\
            \tlibvulkan.so (libc6,x86-64) => /lib/x86_64-linux-gnu/libvulkan.so\n";
        assert_eq!(
            parse_ldconfig_paths(listing, "libvulkan.so.1", "x86-64"),
            vec!["/lib/x86_64-linux-gnu/libvulkan.so.1"]
        );
    }

    #[test]
    fn upstream_cuda_is_rejected_on_ubuntu22_with_the_reason() {
        let entry = linux_entry(json!({"minimum_glibc": "2.38", "minimum_glibcxx": "3.4.32"}));
        let reason = entry_host_incompatibility(&entry, &ubuntu22()).unwrap();
        assert!(
            reason.contains("glibc 2.38") && reason.contains("2.35"),
            "{reason}"
        );
        let newer = HostFacts {
            glibc: Some("2.39".into()),
            glibcxx_minor: Some(30),
            vulkan_loader: None,
        };
        assert!(entry_host_incompatibility(&entry, &newer)
            .unwrap()
            .contains("GLIBCXX_3.4.32"));
        let noble = HostFacts {
            glibc: Some("2.39".into()),
            glibcxx_minor: Some(33),
            vulkan_loader: None,
        };
        assert_eq!(entry_host_incompatibility(&entry, &noble), None);
    }

    #[test]
    fn vulkan_needs_loader_and_modern_libstdcxx() {
        let entry = linux_entry(
            json!({"minimum_glibc": "2.34", "minimum_glibcxx": "3.4.30", "requires_vulkan_loader": true}),
        );
        assert_eq!(entry_host_incompatibility(&entry, &ubuntu22()), None);
        let mut no_loader = ubuntu22();
        no_loader.vulkan_loader = Some(false);
        assert!(entry_host_incompatibility(&entry, &no_loader)
            .unwrap()
            .contains("mesa-vulkan-drivers"));
        let rhel9 = HostFacts {
            glibc: Some("2.34".into()),
            glibcxx_minor: Some(29),
            vulkan_loader: Some(true),
        };
        assert!(entry_host_incompatibility(&entry, &rhel9)
            .unwrap()
            .contains("GLIBCXX_3.4.30"));
        assert_eq!(
            entry_host_incompatibility(&entry, &HostFacts::default()),
            None
        );
    }

    #[test]
    fn non_linux_entries_are_never_rejected_on_glibc() {
        let entry = json!({"platform": {"system": "windows", "minimum_glibc": "9.99"}});
        assert_eq!(entry_host_incompatibility(&entry, &ubuntu22()), None);
    }

    #[test]
    fn gpu_classification_prefers_amd_and_discrete_intel() {
        assert_eq!(classify_pci_gpu(0x1002, 0x744c, 0x030000), Some("amd"));
        assert_eq!(classify_pci_gpu(0x8086, 0x56a0, 0x030000), Some("intel"));
        assert_eq!(classify_pci_gpu(0x8086, 0xe20b, 0x030000), Some("intel"));
        assert_eq!(
            classify_pci_gpu(0x8086, 0x9a49, 0x030000),
            None,
            "integrated Iris Xe stays on CPU"
        );
        assert_eq!(
            classify_pci_gpu(0x10de, 0x2684, 0x030000),
            None,
            "NVIDIA uses CUDA"
        );
        assert_eq!(
            classify_pci_gpu(0x1002, 0x1234, 0x040300),
            None,
            "AMD HDMI audio is not a GPU"
        );
        assert_eq!(
            classify_windows_adapters("Microsoft Basic Display Adapter\nAMD Radeon RX 7900 XTX\n"),
            Some("amd")
        );
        assert_eq!(
            classify_windows_adapters("Intel(R) Arc(TM) B580 Graphics"),
            Some("intel")
        );
        assert_eq!(classify_windows_adapters("Intel(R) UHD Graphics 770"), None);
    }
}
