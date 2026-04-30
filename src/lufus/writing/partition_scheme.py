from enum import Enum, auto


class PartitionScheme(Enum):
    WINDOWS_NTFS = auto()
    WINDOWS_EXFAT = auto()
    SIMPLE_FAT32 = auto()
    LINUX = auto()
