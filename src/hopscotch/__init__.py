from hopscotch.eventstream.eventstream import Eventstream
from hopscotch.eventstream.schema import EventstreamSchema

try:
    from importlib.metadata import version
    __version__ = version("hopscotch-analytics")
except Exception:
    __version__ = "unknown"

__all__ = ["Eventstream", "EventstreamSchema", "__version__"]
