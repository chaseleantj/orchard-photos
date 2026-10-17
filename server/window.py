"""The page in its own native window, through pywebview: WebKit on macOS, WebView2 on Windows, and GTK or Qt on Linux."""
import logging
import os
from pathlib import Path
import signal
import sys
import sysconfig

import webview
from webview.guilib import initialize

ROOT = Path(__file__).resolve().parent.parent
SIZE = (1280, 860)
MIN_SIZE = (720, 520)
# Set by the Mac app that scripts/install-app builds, to the path of its bundle.
BUNDLE_VARIABLE = 'ORCHARD_BUNDLE'
# The app's Contents/MacOS/python links to this file in the environment, a link to Python's own app binary.
APP_PYTHON = 'app-python'
# The window's icon, in the format each toolkit reads: Windows' WinForms takes only an .ico, and GTK or Qt a PNG.
ICONS = {'darwin': ROOT / 'assets' / 'orchard.icns', 'win32': ROOT / 'assets' / 'orchard.ico'}
DEFAULT_ICON = ROOT / 'public' / 'apple-touch-icon.png'


def become_app(name: str):
    """On macOS, show this process as the app rather than as Python. Runs before anything starts AppKit."""
    if sys.platform != 'darwin':
        return
    enter_app_bundle()
    # Run from a terminal, this process is still Python's app, so the menu bar would say Python.
    from Foundation import NSBundle
    NSBundle.mainBundle().infoDictionary()['CFBundleName'] = name


def unavailable() -> str | None:
    """Why this computer can't show the window, or None when it can."""
    if sys.platform == 'linux' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return 'there is no display'
    # pywebview logs a traceback for each toolkit it can't load, and the caller says why in one line instead.
    log = logging.getLogger('pywebview')
    log.disabled = True
    try:
        initialize()
    except webview.WebViewException:
        if sys.platform == 'linux':
            return 'WebKitGTK for Python is missing. On Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1'
        return 'pywebview could not load its window toolkit'
    finally:
        log.disabled = False
    return None


def enter_app_bundle():
    """When the Mac app started this process, run it again through the link inside the app to Python's own app binary.

    macOS takes an app's name and Dock icon from the bundle its executable sits in, so the window then belongs to the
    app the user clicked, instead of a second Dock icon called Python. Only framework builds of Python, like
    Homebrew's and python.org's, have that small app binary; other builds show the window as Python."""
    bundle = os.environ.pop(BUNDLE_VARIABLE, None)
    if not bundle or not sysconfig.get_config_var('PYTHONFRAMEWORK'):
        return
    # The app's link points here, so the signed app never changes, and this follows whichever Python made the
    # environment.
    link = Path(sys.prefix, APP_PYTHON)
    target = Path(sys.base_prefix, 'Resources', 'Python.app', 'Contents', 'MacOS', 'Python')
    executable = Path(bundle, 'Contents', 'MacOS', 'python')
    try:
        if not link.is_symlink() or link.readlink() != target:
            link.unlink(missing_ok=True)
            link.symlink_to(target)
    except OSError:
        return
    if not executable.is_symlink():
        return
    # How a framework build's own python command starts its app binary, so it still uses this environment.
    os.environ['__PYVENV_LAUNCHER__'] = sys.executable
    os.execv(executable, [str(executable), *sys.orig_argv[1:]])


class Window:
    def __init__(self, name: str, url: str):
        self.name = name
        webview.settings['ALLOW_DOWNLOADS'] = True
        self.view = webview.create_window(name, url, width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE, text_select=True)
        self.view.events.before_show += self.restore_frame

    def restore_frame(self):
        """Reopen at the size and place the window had last time. Only macOS has this built in."""
        if sys.platform == 'darwin':
            self.view.native.setFrameUsingName_(self.name)
            self.view.native.setFrameAutosaveName_(self.name)

    def run(self):
        """Show the window, and return once it is closed."""
        icon = ICONS.get(sys.platform, DEFAULT_ICON)
        # Ctrl+C in the terminal quits at once, like the window's own Quit. GTK's loop would otherwise hold Python's
        # handler back until the window next has an event. pywebview sets its own on macOS.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        # private_mode=False keeps the page's saved settings, like the theme and filters, between runs. macOS keeps
        # them, and the window's frame, per app, so the Dock app and a terminal run each have their own.
        webview.start(private_mode=False, icon=str(icon))

    def choose_folder(self, start: Path | None) -> str | None:
        """Ask with the system folder dialog. Returns None when cancelled."""
        chosen = self.view.create_file_dialog(webview.FileDialog.FOLDER, directory=str(start or ''))
        return chosen[0] if chosen else None

    def bring_forward(self):
        self.view.restore()
        self.view.show()
