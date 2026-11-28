"""The shared browser writer/sequence wire contract, without storage or I/O."""
from dataclasses import dataclass
import re

WRITER_HEADER = "x-bdobb-state-writer"
SEQUENCE_HEADER = "x-bdobb-state-sequence"
WRITER = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
SEQUENCE = re.compile(r"[1-9][0-9]{0,15}")
MAX_SEQUENCE = 9007199254740991


@dataclass(frozen=True)
class StateVersion:
    writer: str
    sequence: int

    def __post_init__(self):
        if (not isinstance(self.writer, str) or not WRITER.fullmatch(self.writer)
                or type(self.sequence) is not int or not 1 <= self.sequence <= MAX_SEQUENCE):
            raise ValueError("Invalid state version")


def read_version(headers):
    writers, sequences = headers.getlist(WRITER_HEADER), headers.getlist(SEQUENCE_HEADER)
    if not writers and not sequences:
        return None
    if len(writers) != 1 or len(sequences) != 1 or not SEQUENCE.fullmatch(sequences[0]):
        raise ValueError("Invalid state version")
    return StateVersion(writers[0], int(sequences[0]))
