"""mDNS (Zeroconf) service registration for automatic LAN discovery."""

from __future__ import annotations

import logging
import socket

from config import APP_VERSION, MDNS_SERVICE_TYPE, get_all_lan_ipv4, get_primary_lan_ip

logger = logging.getLogger("quickdrop.mdns")


class MdnsAdvertiser:
    """Publishes _quickdrop._tcp.local. so Android NsdManager discovers this PC."""

    def __init__(self, device_name: str, port: int) -> None:
        self.device_name = device_name
        self.port = port
        self._zeroconf = None
        self._service_info = None

    def start(self) -> bool:
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf

            lan_ips = get_all_lan_ipv4()
            primary_ip = get_primary_lan_ip()
            packed_ips = [socket.inet_aton(ip) for ip in lan_ips]
            safe_host = "".join(
                ch if ch.isalnum() or ch == "-" else "-" for ch in self.device_name
            ).strip("-") or "quickdrop-pc"
            instance_name = f"QuickDrop-{safe_host}.{MDNS_SERVICE_TYPE}"
            server_fqdn = f"{safe_host.lower()}.local."

            properties = {
                "version": APP_VERSION,
                "host": self.device_name,
                "ip": primary_ip,
                "port": str(self.port),
                "platform": "windows",
            }

            self._service_info = ServiceInfo(
                type_=MDNS_SERVICE_TYPE,
                name=instance_name,
                addresses=packed_ips,
                port=self.port,
                properties=properties,
                server=server_fqdn,
            )
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._zeroconf.register_service(self._service_info, allow_name_change=True)
            logger.info(
                "mDNS registrado: %s en %s:%d",
                instance_name,
                ", ".join(lan_ips),
                self.port,
            )
            return True
        except Exception as exc:
            logger.warning("No se pudo iniciar mDNS/Zeroconf (fallback a IP manual): %s", exc)
            self.stop()
            return False

    def stop(self) -> None:
        if self._zeroconf is not None:
            try:
                if self._service_info is not None:
                    self._zeroconf.unregister_service(self._service_info)
            except Exception:
                pass
            try:
                self._zeroconf.close()
            except Exception:
                pass
        self._zeroconf = None
        self._service_info = None
