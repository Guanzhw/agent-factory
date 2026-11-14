"""Owner-authenticated downloads, separate from unrestricted Agent coding tools."""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path, PureWindowsPath
import sys
from typing import cast

def _parts(value, *, directory=False):
    if (not value or '\\' in value or '\0' in value or value.startswith('/')
            or any(part in {'', '..'} for part in value.split('/'))):
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    parts = value.split('/')
    if any(part == '.' for part in parts) and not (directory and value == '.'):
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    if sys.platform == 'win32' and value != '.' and any(
            PureWindowsPath(part).is_reserved() or part.endswith((' ', '.'))
            or any(char in '<>:"|?*' or ord(char) < 32 for char in part) for part in parts):
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    return [] if value == '.' else parts


def _workspace_parts(workspace, value, *, directory=False):
    """Resolve normal absolute/relative syntax before applying session ownership."""
    if not isinstance(value, str) or not value or '\0' in value:
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    root = os.path.realpath(workspace)
    target = os.path.realpath(value if os.path.isabs(value) else os.path.join(root, value))
    if target != root and not target.startswith(os.path.join(root, '')):
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    relative = Path(os.path.relpath(target, root))
    if not relative.parts and not directory:
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    return list(relative.parts)


def _windows_path(path):
    absolute = os.path.abspath(path)
    if absolute.startswith('\\\\?\\'):
        return Path(absolute)
    return Path('\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute)


@contextmanager
def _windows_directory(root, parts=(), *, create=False):
    # Deny ancestor rename/deletion while allowing native Workspace child replacement.
    if sys.platform != 'win32':
        raise ValueError('RESEARCH_WORKSPACE_CONFIGURATION_INVALID')
    import pywintypes
    import win32con
    import win32file
    path = _windows_path(root)
    with ExitStack() as held:
        current = Path(path.anchor)
        for index, part in enumerate((path.anchor, *path.parts[1:], *parts)):
            if index:
                current /= part
                if create:
                    try:
                        current.mkdir(mode=0o700)
                    except FileExistsError:
                        pass
            try:
                handle = cast('pywintypes.HANDLEType', win32file.CreateFile(str(current), win32con.GENERIC_READ,
                    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None, win32con.OPEN_EXISTING,
                    win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS, None))
                held.callback(handle.Close)
                attributes = win32file.GetFileInformationByHandle(int(handle))[0]
            except pywintypes.error:
                # pywin32.error derives from Exception, not OSError. No user
                # file has been opened or written at this directory boundary.
                raise OSError('RESEARCH_WORKSPACE_PATH_INVALID') from None
            if not attributes & win32con.FILE_ATTRIBUTE_DIRECTORY or attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
        yield current


@contextmanager
def _directory(root, parts=(), *, create=False):
    if sys.platform == 'win32':
        with _windows_directory(root, parts, create=create) as directory:
            yield directory
        return
    if os.name != 'posix':
        raise ValueError('RESEARCH_WORKSPACE_CONFIGURATION_INVALID')
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY') | getattr(os, 'O_NOFOLLOW')
    descriptor = os.open('/', flags)
    try:
        for part in (*Path(root).parts[1:], *parts):
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _open_file(parent, name):
    leaf = os.path.basename(name)
    if leaf != name or leaf in {'', '.', '..'}:
        raise ValueError('RESEARCH_WORKSPACE_PATH_INVALID')
    if sys.platform == 'win32':
        import msvcrt
        import pywintypes
        import win32con
        import win32file
        import winerror
        _parts(name)
        try:
            handle = cast('pywintypes.HANDLEType', win32file.CreateFile(str(parent / name),
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING,
                win32file.FILE_FLAG_OPEN_REPARSE_POINT, None))
        except pywintypes.error as error:
            if error.winerror == winerror.ERROR_FILE_NOT_FOUND:
                raise FileNotFoundError('RESEARCH_FILE_UNAVAILABLE') from None
            raise OSError('RESEARCH_FILE_UNAVAILABLE') from None
        try:
            info = win32file.GetFileInformationByHandle(int(handle))
            if (info[0] & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DIRECTORY)
                    or win32file.GetFileType(int(handle)) != win32con.FILE_TYPE_DISK):
                raise ValueError('RESEARCH_FILE_UNSUPPORTED')
            descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
            handle.Detach()  # The CRT descriptor now owns this exact file handle.
            return descriptor
        except (pywintypes.error, OSError, ValueError):
            raise OSError('RESEARCH_FILE_UNSUPPORTED') from None
        finally:
            handle.Close()
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW') | getattr(os, 'O_NONBLOCK')
    return os.open(leaf, flags, 0o600, dir_fd=parent)


