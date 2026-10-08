"""Cross-platform process locks with explicit release and bounded file authority."""
import contextlib
import os
import stat
from pathlib import Path


@contextlib.contextmanager
def file_lock(path, shared=False, blocking=True, busy_message="Process control is busy."):
    path = Path(path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise RuntimeError("Process control refuses a linked lock.")
    fd = os.open(str(path), flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError("Invalid process lock.")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt

            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("internal", ctypes.c_size_t),
                    ("internal_high", ctypes.c_size_t),
                    ("offset", wintypes.DWORD),
                    ("offset_high", wintypes.DWORD),
                    ("event", wintypes.HANDLE),
                ]

            overlapped = Overlapped()
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.LockFileEx.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(Overlapped),
            ]
            kernel.LockFileEx.restype = wintypes.BOOL
            kernel.UnlockFileEx.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(Overlapped),
            ]
            handle = msvcrt.get_osfhandle(fd)
            flags = (0 if shared else 2) | (0 if blocking else 1)
            if not kernel.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped)):
                raise RuntimeError(
                    busy_message
                )
            try:
                yield
            finally:
                kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
        else:
            import fcntl

            try:
                fcntl.flock(
                    fd,
                    (fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                    | (0 if blocking else fcntl.LOCK_NB),
                )
            except BlockingIOError as exc:
                raise RuntimeError(
                    busy_message
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

