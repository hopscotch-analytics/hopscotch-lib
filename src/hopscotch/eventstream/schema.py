from dataclasses import dataclass, field
from typing import List


@dataclass
class EventstreamSchema:
    path_cols: List[str] = field(default_factory=lambda: ["user_id"])
    event_cols: List[str] = field(default_factory=lambda: ["event"])
    timestamp: str = "timestamp"
    event_type: str = "event_type"
    index: str = "index"
    subindex: str = "subindex"
    segment_cols: List[str] = field(default_factory=list)
    custom_cols: List[str] = field(default_factory=list)

    @property
    def path_col(self):
        return self.path_cols[0]

    @property
    def event_col(self):
        return self.event_cols[0]

    @property
    def public_cols(self):
        return self.path_cols + self.event_cols + [self.timestamp] + self.segment_cols + self.custom_cols

    @property
    def cols(self):
        return (
            self.path_cols + self.event_cols + [self.timestamp]
            + self.segment_cols + self.custom_cols
            + [self.event_type, self.index, self.subindex]
        )

    def copy(self) -> "EventstreamSchema":
        return EventstreamSchema(
            path_cols=self.path_cols.copy(),
            event_cols=self.event_cols.copy(),
            timestamp=self.timestamp,
            event_type=self.event_type,
            index=self.index,
            subindex=self.subindex,
            segment_cols=self.segment_cols.copy(),
            custom_cols=self.custom_cols.copy(),
        )
