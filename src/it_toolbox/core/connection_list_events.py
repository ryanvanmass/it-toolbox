from PySide6.QtCore import QObject, Signal


class _ConnectionListEvents(QObject):
    #: Emitted (on the main thread) after Settings changes how Connection
    #: Manager's Manual list is laid out (grouped by connection type or
    #: flat). Lets Connection Manager rebuild that list right away,
    #: without Settings importing it.
    layout_changed = Signal()


connection_list_events = _ConnectionListEvents()
