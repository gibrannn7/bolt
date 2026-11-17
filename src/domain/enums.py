from enum import Enum


class VenueType(str, Enum):
    HYPERLIQUID = "HYPERLIQUID"
    POLYMARKET = "POLYMARKET"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    NEUTRAL = "NEUTRAL"


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    SEMI_AUTO = "SEMI_AUTO"
    FULL_AUTO = "FULL_AUTO"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    CANCELLED = "CANCELLED"
