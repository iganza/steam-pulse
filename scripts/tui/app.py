"""SteamPulse Admin TUI — main Textual application."""

from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, ContentSwitcher, Footer, Header, Static

from tui.aws import AwsClients
from tui.config import connect_db
from tui.screens.analysis import AnalysisScreen
from tui.screens.dashboard import DashboardScreen
from tui.screens.games import GamesBrowserScreen
from tui.screens.logs import LogsScreen
from tui.screens.queues import QueuesScreen
from tui.screens.reviews import ReviewsBrowserScreen
from tui.screens.sql import SQLConsoleScreen
from tui.screens.tags import TagsGenresScreen

NAV_ITEMS = [
    ("dashboard", "D", "Dashboard"),
    ("games", "G", "Games"),
    ("reviews", "R", "Reviews"),
    ("tags", "T", "Tags"),
    ("analysis", "A", "Analysis"),
    ("queues", "Q", "Queues"),
    ("logs", "L", "Logs"),
    ("sql", "S", "SQL"),
]


class Sidebar(Vertical):
    """Navigation sidebar with screen buttons."""

    def compose(self) -> ComposeResult:
        for screen_id, key, label in NAV_ITEMS:
            btn = Button(f"[{key}] {label}", id=f"nav-{screen_id}", classes="nav-btn")
            if screen_id == "dashboard":
                btn.add_class("-active")
            yield btn


class StatusBar(Static):
    """Header status bar showing env, DB, AWS status, and clock."""

    clock: reactive[str] = reactive("")

    def __init__(self, env: str | None, db_ok: bool, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.env = env
        self.db_ok = db_ok

    def on_mount(self) -> None:
        self._update_clock()
        self.set_interval(1, self._update_clock)

    def _update_clock(self) -> None:
        self.clock = datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")

    def render(self) -> str:
        env_label = self.env or "local"
        db_dot = "[green]\u25cf[/green]" if self.db_ok else "[red]\u25cf[/red]"
        aws_dot = (
            "[green]\u25cf[/green]"
            if self.env
            else "[dim]\u25cb[/dim]"
        )
        return (
            f"  SteamPulse Admin  \u2502  env: [bold]{env_label}[/bold]  "
            f"\u2502  DB: {db_dot}  \u2502  AWS: {aws_dot}  \u2502  {self.clock}"
        )

    def watch_clock(self) -> None:
        self.refresh()


HELP_TEXT = """\
[bold]Navigation[/bold]
  d  Dashboard       g  Games          r  Reviews
  t  Tags/Genres     a  Analysis       q  Queues
  l  Logs            s  SQL Console
  \\  Toggle sidebar  ?  This help      Ctrl+Q  Quit

[bold]Universal[/bold]
  Enter      Select / drill into row
  Escape     Close panel / modal
  PgUp/PgDn  Page through tables
  F5         Refresh current screen

[bold]Games (detail panel open)[/bold]
  1  Crawl metadata   2  Crawl reviews
  3  Crawl tags       4  Analyze game
  o  Open on Steam    /  Focus search

[bold]Analysis[/bold]
  1  Analyze selected game
  2  Batch analyze top unanalyzed

[bold]Queues (DLQ inspector open)[/bold]
  1  Retry message    2  Delete message

[bold]Logs[/bold]
  e  Toggle error-only filter

[bold]SQL Console[/bold]
  Ctrl+Enter  Run query      Ctrl+L  Templates
  Ctrl+S      Export CSV      Tab     Template selector
"""


class HelpScreen(ModalScreen[None]):
    """Help overlay showing all keybindings."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen > VerticalScroll {
        width: 65;
        height: 32;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(HELP_TEXT)

    def key_escape(self) -> None:
        self.dismiss()


class SteamPulseAdmin(App[None]):
    """SteamPulse Admin TUI application."""

    TITLE = "SteamPulse Admin"
    CSS_PATH = "styles.css"

    BINDINGS = [
        Binding("d", "switch_screen('dashboard')", "Dashboard", priority=False),
        Binding("g", "switch_screen('games')", "Games", priority=False),
        Binding("r", "switch_screen('reviews')", "Reviews", priority=False),
        Binding("t", "switch_screen('tags')", "Tags", priority=False),
        Binding("a", "switch_screen('analysis')", "Analysis", priority=False),
        Binding("q", "switch_screen('queues')", "Queues", priority=False),
        Binding("l", "switch_screen('logs')", "Logs", priority=False),
        Binding("s", "switch_screen('sql')", "SQL", priority=False),
        Binding("backslash", "toggle_sidebar", "Toggle Sidebar", priority=False),
        Binding("question_mark", "show_help", "Help", priority=False),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    current_screen: reactive[str] = reactive("dashboard")

    def __init__(self, env: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.env = env
        self.db_conn = connect_db(env)
        self.aws_available = env is not None
        self.aws = AwsClients(env)
        self._clock_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(self.env, self.db_conn is not None, id="status-bar")
        with Container(id="main-container"):
            yield Sidebar(id="sidebar")
            with ContentSwitcher(id="content-switcher", initial="dashboard"):
                yield DashboardScreen(id="dashboard")
                yield GamesBrowserScreen(id="games")
                yield ReviewsBrowserScreen(id="reviews")
                yield TagsGenresScreen(id="tags")
                yield AnalysisScreen(id="analysis")
                yield QueuesScreen(id="queues")
                yield LogsScreen(id="logs")
                yield SQLConsoleScreen(id="sql")
        yield Footer()

    def action_show_help(self) -> None:
        """Show the help overlay."""
        self.push_screen(HelpScreen())

    def action_switch_screen(self, screen_id: str) -> None:
        """Switch the content area to the selected screen."""
        switcher = self.query_one("#content-switcher", ContentSwitcher)
        switcher.current = screen_id
        self.current_screen = screen_id
        self._update_nav_highlight(screen_id)

    def _update_nav_highlight(self, active_id: str) -> None:
        """Update sidebar button highlighting."""
        for screen_id, _, _ in NAV_ITEMS:
            btn = self.query_one(f"#nav-{screen_id}", Button)
            if screen_id == active_id:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.display = not sidebar.display

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle sidebar button clicks."""
        btn_id = event.button.id or ""
        if btn_id.startswith("nav-"):
            screen_id = btn_id.removeprefix("nav-")
            self.action_switch_screen(screen_id)
