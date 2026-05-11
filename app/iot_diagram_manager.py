"""IoT schematic generation utilities based on SchemDraw."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DiagramResult:
    ok: bool
    message: str
    png_path: str = ""
    svg_path: str = ""
    bom_path: str = ""
    netlist_path: str = ""


class IoTDiagramManager:
    """Build simple electronic schematics and BOM files from JSON-like inputs."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.output_dir = os.path.join(base_dir, "outputs", "schematics")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_schematic(
        self,
        title: str,
        board: str,
        components: list[dict[str, Any]],
        connections: list[dict[str, Any]],
    ) -> DiagramResult:
        if not components:
            return DiagramResult(False, "No components provided.")

        try:
            import schemdraw
            import schemdraw.elements as elm
        except Exception as exc:  # noqa: BLE001
            return DiagramResult(
                False,
                "SchemDraw is not installed. Install dependency 'schemdraw'.",
                bom_path=str(exc),
            )

        safe_title = self._safe_name(title or "iot_schematic")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_title}_{stamp}"
        png_path = os.path.join(self.output_dir, f"{base_name}.png")
        svg_path = os.path.join(self.output_dir, f"{base_name}.svg")
        bom_path = os.path.join(self.output_dir, f"{base_name}_bom.csv")
        netlist_path = os.path.join(self.output_dir, f"{base_name}.net")
        warnings: list[str] = []

        # Build a practical linear-style diagram for readability.
        try:
            with schemdraw.Drawing(file=svg_path, show=False) as d:
                self._draw_schematic(d, elm, board, components, connections)

            # PNG output is optional and depends on backend support.
            try:
                with schemdraw.Drawing(file=png_path, show=False) as d_png:
                    self._draw_schematic(d_png, elm, board, components, connections)
            except Exception:
                png_path = ""
                warnings.append("PNG export not available with current drawing backend.")

            self._write_bom(bom_path, title, board, components, connections)
            self._write_netlist(netlist_path, board, connections)
        except Exception as exc:  # noqa: BLE001
            return DiagramResult(False, f"Failed to generate schematic: {exc}")

        message = "Schematic generated successfully."
        if warnings:
            message += " " + " ".join(warnings)

        return DiagramResult(
            ok=True,
            message=message,
            png_path=png_path,
            svg_path=svg_path,
            bom_path=bom_path,
            netlist_path=netlist_path,
        )

    def _draw_schematic(
        self,
        drawing,
        elm,
        board: str,
        components: list[dict[str, Any]],
        connections: list[dict[str, Any]],
    ) -> None:
        drawing += elm.SourceV().label("5V")
        drawing += elm.Line().right(1.2)
        drawing += elm.Dot().label(board or "MCU", loc="top")

        for comp in components:
            comp_type = (comp.get("type") or "").lower()
            label = comp.get("label") or comp.get("name") or comp_type or "part"

            if "res" in comp_type:
                drawing += elm.Resistor().down().label(label)
            elif "led" in comp_type:
                drawing += elm.LED().down().label(label)
            elif "cap" in comp_type:
                drawing += elm.Capacitor().down().label(label)
            elif "sensor" in comp_type:
                drawing += elm.Resistor().down().label(f"SENSOR {label}")
            elif "switch" in comp_type or "button" in comp_type:
                drawing += elm.Resistor().down().label(f"SW {label}")
            else:
                drawing += elm.Resistor().down().label(label)

            drawing += elm.Line().down(0.6)
            drawing += elm.Ground()
            drawing += elm.Line().up(0.6)
            drawing += elm.Line().right(1.2)

        drawing += elm.Dot().label(f"Nets: {len(connections)}", loc="bottom")

    def _write_bom(
        self,
        bom_path: str,
        title: str,
        board: str,
        components: list[dict[str, Any]],
        connections: list[dict[str, Any]],
    ) -> None:
        with open(bom_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["title", title])
            writer.writerow(["board", board])
            writer.writerow(["components", len(components)])
            writer.writerow(["connections", len(connections)])
            writer.writerow([])
            writer.writerow(["id", "type", "label", "value", "notes"])

            for idx, comp in enumerate(components, start=1):
                writer.writerow(
                    [
                        comp.get("id") or f"C{idx}",
                        comp.get("type") or "component",
                        comp.get("label") or comp.get("name") or "",
                        comp.get("value") or "",
                        comp.get("notes") or "",
                    ]
                )

    def _safe_name(self, value: str) -> str:
        chars = []
        for ch in value.strip().lower():
            if ch.isalnum() or ch in {"_", "-"}:
                chars.append(ch)
            elif ch.isspace():
                chars.append("_")
        return "".join(chars) or "schematic"

    def _write_netlist(
        self,
        netlist_path: str,
        board: str,
        connections: list[dict[str, Any]],
    ) -> None:
        with open(netlist_path, "w", encoding="utf-8") as fh:
            fh.write("# Willy IoT Netlist\n")
            fh.write(f"BOARD {board}\n")
            fh.write(f"NETS {len(connections)}\n")
            fh.write("\n")
            for idx, conn in enumerate(connections, start=1):
                src = conn.get("from", "")
                dst = conn.get("to", "")
                signal = conn.get("signal", "")
                fh.write(f"N{idx:03d} {src} -> {dst}")
                if signal:
                    fh.write(f" [{signal}]")
                fh.write("\n")
