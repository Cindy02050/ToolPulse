from toolpulse.state.files import FileStateTracker


class StubFiles(FileStateTracker):
    def __init__(self) -> None:
        super().__init__()
        self.last_read: str | None = None
        self.last_edit: str | None = None

    def record_read(self, path: str) -> None:
        self.last_read = path; super().record_read(path)

    def record_edit(self, path: str) -> None:
        self.last_edit = path; super().record_edit(path)


class StubState:
    def __init__(self) -> None:
        self.files = StubFiles()
