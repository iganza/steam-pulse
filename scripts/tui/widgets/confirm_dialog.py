"""Confirmation dialog — modal screen for confirming actions."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ConfirmDialog(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > Vertical {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    ConfirmDialog .dialog-buttons {
        layout: horizontal;
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    ConfirmDialog .dialog-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, prompt: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt)
            with Vertical(classes="dialog-buttons"):
                yield Button("Yes", variant="primary", id="confirm-yes")
                yield Button("No", variant="default", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def key_y(self) -> None:
        self.dismiss(True)

    def key_n(self) -> None:
        self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)


class TypeConfirmDialog(ModalScreen[bool]):
    """Double-confirmation dialog requiring the user to type a confirmation string."""

    DEFAULT_CSS = """
    TypeConfirmDialog {
        align: center middle;
    }

    TypeConfirmDialog > Vertical {
        width: 70;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, prompt: str, confirm_text: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.prompt = prompt
        self.confirm_text = confirm_text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt)
            yield Label(f'Type "[bold]{self.confirm_text}[/bold]" to confirm:')
            yield Input(placeholder=self.confirm_text, id="confirm-input")
            with Vertical(classes="dialog-buttons"):
                yield Button("Confirm", variant="error", id="confirm-yes")
                yield Button("Cancel", variant="default", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            inp = self.query_one("#confirm-input", Input)
            self.dismiss(inp.value.strip() == self.confirm_text)
        else:
            self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)
