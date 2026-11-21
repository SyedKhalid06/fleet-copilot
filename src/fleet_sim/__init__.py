"""Synthetic Volvo-style fleet data: rFMS telematics, J1939 fault codes and workshop work orders."""
from .config import SimConfig, Depot
from .generate import generate_all

__all__ = ["SimConfig", "Depot", "generate_all"]
