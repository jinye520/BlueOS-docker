import logging
from typing import Dict, List

import requests
from bridges.bridges import Bridge
from bridges.serialhelper import Baudrate
from commonwealth.settings.manager import Manager
from pydantic import BaseModel, conint
from serial.tools.list_ports_linux import SysFS

from settings import BridgeSettingsSpecV1, SettingsV1


class BridgeSpec(BaseModel):
    """Basic interface for 'bridges' links."""

    serial_path: str
    baud: Baudrate
    ip: str
    udp_port: conint(gt=1023, lt=65536)  # type: ignore

    def __str__(self) -> str:
        return f"{self.serial_path}:{self.baud}//{self.ip}:{self.udp_port}"

    def __hash__(self) -> int:
        return hash(str(self))

    @staticmethod
    def from_settings_spec(settings_spec: BridgeSettingsSpecV1) -> "BridgeSpec":
        return BridgeSpec(
            serial_path=settings_spec.serial_path,
            baud=settings_spec.baudrate,
            ip=settings_spec.ip,
            udp_port=settings_spec.udp_port,
        )


class Bridget:
    """Manager for 'bridges' links."""

    def __init__(self) -> None:
        self._bridges: Dict[BridgeSpec, Bridge] = {}
        self._settings_manager = Manager("bridget", SettingsV1)
        self._settings_manager.load()
        for bridge_settings_spec in self._settings_manager.settings.specs:
            try:
                logging.debug(f"Adding following bridge from persistency '{bridge_settings_spec}'.")
                self.add_bridge(BridgeSpec.from_settings_spec(bridge_settings_spec))
            except Exception as error:
                logging.exception(f"Could not add bridge '{bridge_settings_spec}'. {error}")

    def available_serial_ports(self) -> List[str]:
        try:
            response = requests.get("http://localhost:6030/serial", timeout=1)
            data = response.json()
            return [port["name"] for port in data["ports"] if port["name"] is not None]
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            return []

    def get_bridges(self) -> List[BridgeSpec]:
        return [spec for spec, bridge in self._bridges.items()]

    def add_bridge(self, bridge_spec: BridgeSpec) -> None:
        if bridge_spec in self._bridges:
            raise RuntimeError("Bridge already exist.")
        new_bridge = Bridge(
            SysFS(bridge_spec.serial_path),
            bridge_spec.baud,
            bridge_spec.ip,
            bridge_spec.udp_port,
            automatic_disconnect=False,
        )
        self._bridges[bridge_spec] = new_bridge
        settings_spec = BridgeSettingsSpecV1.from_spec(bridge_spec)
        if settings_spec not in self._settings_manager.settings.specs:
            self._settings_manager.settings.specs.append(settings_spec)
            self._settings_manager.save()

    def remove_bridge(self, bridge_spec: BridgeSpec) -> None:
        bridge = self._bridges.pop(bridge_spec, None)
        self._settings_manager.settings.specs.remove(BridgeSettingsSpecV1.from_spec(bridge_spec))
        self._settings_manager.save()
        if bridge is None:
            raise RuntimeError("Bridge doesn't exist.")
        bridge.stop()

    def stop(self) -> None:
        logging.debug("Stopping Bridget and removing all bridges.")
        for bridge_spec in self._bridges:
            self.remove_bridge(bridge_spec)

    def __del__(self) -> None:
        self.stop()
