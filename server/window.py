"""The page in its own native window, through pywebview: WebKit on macOS, WebView2 on Windows, and GTK or Qt on Linux."""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import re
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
# The Mac app's Contents/MacOS/python links to this file in the environment, a link to Python's own app binary.
APP_PYTHON = 'app-python'
# Windows' WinForms crashes on anything but an .ico, and GTK and Qt take a PNG.
ICONS = {'darwin': ROOT / 'assets' / 'orchard.icns', 'win32': ROOT / 'assets' / 'orchard.ico'}
DEFAULT_ICON = ROOT / 'public' / 'apple-touch-icon.png'
# The Mac's standard Window menu, which pywebview leaves out, as (title, action, key) with None for a separator.
# pywebview's page view has its own ⌘W, but the key never reaches it, so Close Window carries it.
WINDOW_MENU = (('Minimize', 'performMiniaturize:', 'm'), ('Zoom', 'performZoom:', ''), None, ('Bring All to Front', 'arrangeInFront:', ''),
               ('Close Window', 'performClose:', 'w'))
# An image the page lets drag out names its id in the drag's data after a mark, as dragImage in web/src/types.ts
# writes it.
MARKED_IMAGE = re.compile(rb'library-image:([0-9a-f]{64})')
# The longest a drag leaving the window waits for its image's file, which Photos may have to write out first.
FILE_WAIT = 2


def become_app(name: str):
    """On macOS, show this process as the app rather than as Python. Runs before anything starts AppKit."""
    if sys.platform != 'darwin':
        return
    enter_app_bundle()
    # Run from a terminal, this process is Python's app, so the menu bar would say Python.
    from Foundation import NSBundle
    NSBundle.mainBundle().infoDictionary()['CFBundleName'] = name


def unavailable() -> str | None:
    """Why this computer can't show the window, or None when it can."""
    if sys.platform == 'linux' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return 'there is no display'
    # pywebview logs a traceback for each toolkit it can't load. The caller says why in one line instead.
    log = logging.getLogger('pywebview')
    log.disabled = True
    try:
        initialize()
    except webview.WebViewException:
        if sys.platform == 'linux':
            return 'WebKitGTK for Python is missing. On Ubuntu: sudo apt update && sudo apt install python3-gi gir1.2-webkit2-4.1'
        return 'pywebview could not load its window toolkit'
    # A toolkit that is there but fails to load, like pythonnet when .NET refuses its DLL, raises its own error. The
    # browser still works, so that is no reason to stop.
    except Exception as error:
        return f'its window toolkit failed to load: {error}'.replace('\n', ' ')
    finally:
        log.disabled = False
    return None


def enter_app_bundle():
    """When the Mac app started this process, run it again through the link inside the app to Python's own app binary.

    macOS takes an app's name and Dock icon from the bundle its executable sits in, so the window then belongs to the
    app, instead of a second Dock icon called Python. Only framework builds of Python, like Homebrew's and
    python.org's, have that app binary."""
    bundle = os.environ.pop(BUNDLE_VARIABLE, None)
    if not bundle or not sysconfig.get_config_var('PYTHONFRAMEWORK'):
        return
    # The app's link points here, so the signed app never changes while this follows the environment's Python.
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


def window_menu():
    import AppKit

    menu = AppKit.NSMenu.alloc().initWithTitle_('Window')
    for item in WINDOW_MENU:
        if item:
            menu.addItemWithTitle_action_keyEquivalent_(*item)
        else:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
    return menu


def add_window_menu(window):
    """Add the Window menu to the menu bar, and list the window in it."""
    import AppKit

    app = AppKit.NSApplication.sharedApplication()
    menu = window_menu()
    item = AppKit.NSMenuItem.alloc().init()
    item.setSubmenu_(menu)
    app.mainMenu().addItem_(item)
    app.setWindowsMenu_(menu)
    # macOS lists windows as they open, and this one is already open.
    app.addWindowsItem_title_filename_(window, window.title(), False)


def marked_image(data) -> str | None:
    """The image id that WebKit's copy of a drag's page data names after its mark, or None."""
    found = MARKED_IMAGE.search(bytes(data or b''))
    return found and found[1].decode()


def drag_images_out(host, image_file: Callable[[str], Path | None]):
    """Let an image dragged out of the macOS window arrive in other apps as its file, image_file(id), as a file dragged
    from Finder does. A file would replace the page's own drag data, which the window's drops read, like the search
    bar's Find similar, so the file joins the drag only while it is outside the window."""
    import AppKit
    from Foundation import NSURL
    import objc

    finding = ThreadPoolExecutor(1)
    drag = {}

    # WebKit starts a drag through this older AppKit call, with the page's data already on the pasteboard.
    def dragImage_at_offset_event_pasteboard_source_slideBack_(self, image, at, offset, event, board, source, slide):
        drag.clear()
        image_id = marked_image(board.dataForType_('com.apple.WebKit.custom-pasteboard-data'))
        if image_id:
            drag.update(file=finding.submit(image_file, image_id), window=self.window(), outside=False,
                        page={kind: board.dataForType_(kind) for kind in board.types()})
        return objc.super(host, self).dragImage_at_offset_event_pasteboard_source_slideBack_(
            image, at, offset, event, board, source, slide)

    def moved(self, session, point):
        if not drag or AppKit.NSPointInRect(point, drag['window'].frame()) != drag['outside']:
            return
        board = session.draggingPasteboard()
        if drag['outside']:
            board.declareTypes_owner_(list(drag['page']), None)
            for kind, data in drag['page'].items():
                if data is not None:
                    board.setData_forType_(data, kind)
        else:
            try:
                path = drag['file'].result(timeout=FILE_WAIT)
            # Raising here would take the window down. An image without a file leaves the drag as it was.
            except Exception:
                path = None
            if path is None:
                drag.clear()
                return
            board.addTypes_owner_(['public.file-url'], None)
            board.setString_forType_(NSURL.fileURLWithPath_(str(path)).absoluteString(), 'public.file-url')
        drag['outside'] = not drag['outside']

    # The file is the user's own, so other apps only ever copy it, never move or delete it.
    def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
        if drag and context == AppKit.NSDraggingContextOutsideApplication:
            return AppKit.NSDragOperationCopy
        return objc.super(host, self).draggingSession_sourceOperationMaskForDraggingContext_(session, context)

    objc.classAddMethods(host, [
        dragImage_at_offset_event_pasteboard_source_slideBack_,
        draggingSession_sourceOperationMaskForDraggingContext_,
        objc.selector(moved, selector=b'draggingSession:movedToPoint:', signature=b'v@:@{CGPoint=dd}'),
    ])


class Window:
    def __init__(self, name: str, url: str, image_file: Callable[[str], Path | None]):
        """image_file(id) is the file an image dragged out of the window carries, or None for none."""
        self.name = name
        webview.settings['ALLOW_DOWNLOADS'] = True
        # draggable=True, or pywebview cancels every drag that starts on an image, like one carried to the search bar.
        self.view = webview.create_window(name, url, width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE, text_select=True, draggable=True)
        self.view.events.before_show += self.restore_frame
        if sys.platform == 'darwin':
            from PyObjCTools import AppHelper

            # before_show runs on the main thread just before pywebview builds the menu bar and starts its loop,
            # so the call waits in the loop's queue until the bar is there.
            self.view.events.before_show += lambda: AppHelper.callAfter(add_window_menu, self.view.native)
            from webview.platforms.cocoa import BrowserView

            drag_images_out(BrowserView.WebKitHost, image_file)

    def restore_frame(self):
        """Reopen at the size and place the window had last time. Only macOS has this built in."""
        if sys.platform == 'darwin':
            self.view.native.setFrameUsingName_(self.name)
            self.view.native.setFrameAutosaveName_(self.name)

    def run(self):
        """Show the window, and return once it is closed."""
        icon = ICONS.get(sys.platform, DEFAULT_ICON)
        # Ctrl+C quits at once. GTK's loop would otherwise hold Python's handler back until the window's next event.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        # private_mode=False keeps the page's saved settings, like the theme and filters, between runs.
        webview.start(private_mode=False, icon=str(icon))

    def choose_folder(self, start: Path | None) -> str | None:
        """Ask with the system folder dialog. Returns None when cancelled."""
        chosen = self.view.create_file_dialog(webview.FileDialog.FOLDER, directory=str(start or ''))
        return chosen[0] if chosen else None

    def bring_forward(self):
        self.view.restore()
        self.view.show()
