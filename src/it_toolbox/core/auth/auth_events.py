from PySide6.QtCore import QObject, Signal


class _AuthEvents(QObject):
    #: Emitted (on the main thread) after the gcloud account changes — the
    #: new account's email, or None once signed out. Lets independent views
    #: (Settings, where sign-in/out happens, and Connection Manager's GCP
    #: tree) stay in sync without importing each other.
    account_changed = Signal(object)


auth_events = _AuthEvents()
