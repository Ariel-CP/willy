"""IoT schematic generation utilities based on SchemDraw."""

from __future__ import annotations

import csv
import os
import shutil
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
        project_path: str = "",
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
        warnings.extend(self._validate_connections(board, components, connections))

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

        # --- Copia al directorio del proyecto (si se proporcionó) ---
        project_svg = svg_path
        project_png = png_path
        project_bom = bom_path
        project_net = netlist_path
        if project_path and os.path.isdir(project_path):
            proj_diag_dir = os.path.join(project_path, "diagrams")
            os.makedirs(proj_diag_dir, exist_ok=True)
            try:
                project_svg = os.path.join(proj_diag_dir, f"{base_name}.svg")
                shutil.copy2(svg_path, project_svg)
                if png_path and os.path.isfile(png_path):
                    project_png = os.path.join(proj_diag_dir, f"{base_name}.png")
                    shutil.copy2(png_path, project_png)
                project_bom = os.path.join(proj_diag_dir, f"{base_name}_bom.csv")
                shutil.copy2(bom_path, project_bom)
                project_net = os.path.join(proj_diag_dir, f"{base_name}.net")
                shutil.copy2(netlist_path, project_net)
            except OSError:
                # Si falla la copia, seguimos usando los paths globales
                project_svg = svg_path
                project_png = png_path
                project_bom = bom_path
                project_net = netlist_path

        message = "Schematic generated successfully."
        if warnings:
            shown = warnings[:6]
            hidden = len(warnings) - len(shown)
            message += " " + " ".join(shown)
            if hidden > 0:
                message += f" (+{hidden} warning(s) more)"

        return DiagramResult(
            ok=True,
            message=message,
            png_path=project_png,
            svg_path=project_svg,
            bom_path=project_bom,
            netlist_path=project_net,
        )

    def _draw_schematic(
        self,
        drawing,
        elm,
        board: str,
        components: list[dict[str, Any]],
        connections: list[dict[str, Any]],
    ) -> None:
        # Professional wiring layout:
        # - Header with board and component inventory
        # - Row-per-connection map with explicit FROM -> TO and signal labels
        board_label = (board or "MCU").upper()
        drawing += elm.Dot().label(f"BOARD: {board_label}", loc="top")

        # Component inventory line (compact, useful for quick visual checks)
        comp_tokens: list[str] = []
        for idx, comp in enumerate(components, start=1):
            cid = str(comp.get("id") or f"C{idx}").strip()
            ctype = str(comp.get("type") or "component").strip()
            clabel = str(comp.get("label") or comp.get("name") or "").strip()
            token = f"{cid}:{ctype}"
            if clabel:
                token += f"({clabel})"
            comp_tokens.append(token)

        inventory = " | ".join(comp_tokens) if comp_tokens else "(sin componentes)"
        drawing += elm.Line().down(0.8)
        drawing += elm.Dot(open=True).label(f"PARTS: {inventory}", loc="right")

        drawing += elm.Line().down(0.9)
        drawing += elm.Dot(open=True).label("WIRING MAP", loc="right")

        if not connections:
            drawing += elm.Line().down(0.8)
            drawing += elm.Dot(open=True).label("(sin conexiones declaradas)", loc="right")
            return

        row_gap = 0.9
        span = 8.0
        max_rows = 18
        # Group by signal bus so developers can read wiring intent quickly.
        grouped: dict[str, list[dict[str, Any]]] = {}
        for conn in connections:
            signal = str(conn.get("signal", "")).strip()
            group = self._signal_group(signal)
            grouped.setdefault(group, []).append(conn)

        group_order = ["POWER", "GND", "I2C", "SPI", "UART", "PWM", "DIGITAL", "ANALOG", "OTHER"]
        ordered_groups = [g for g in group_order if g in grouped]

        rendered = 0
        for group in ordered_groups:
            if rendered >= max_rows:
                break

            # Group header line
            drawing += elm.Line().down(row_gap)
            drawing += elm.Dot(open=True).label(f"[{group}]", loc="right")

            for conn in grouped[group]:
                if rendered >= max_rows:
                    break

                rendered += 1
                src = str(conn.get("from", "")).strip() or "?"
                dst = str(conn.get("to", "")).strip() or "?"
                signal = str(conn.get("signal", "")).strip() or f"NET_{rendered:02d}"
                color = self._signal_color(signal)

                # Move to the next row start.
                drawing += elm.Line().down(row_gap)

                # Keep left anchor for successive rows.
                drawing.push()

                # Left endpoint (source pin)
                drawing += elm.Dot(color=color).label(f"{rendered:02d}  {src}", loc="left")

                # Wire + signal name in the middle
                drawing += elm.Line().right(span / 2).color(color)
                drawing += elm.Dot(open=True, color=color).label(signal, loc="top")
                drawing += elm.Line().right(span / 2).color(color)

                # Right endpoint (destination pin)
                drawing += elm.Dot(color=color).label(dst, loc="right")

                drawing.pop()

        if len(connections) > max_rows:
            drawing += elm.Line().down(row_gap)
            drawing += elm.Dot(open=True).label(
                f"... +{len(connections) - max_rows} conexiones adicionales (ver .net)",
                loc="right",
            )

        # Compact legend to standardize reading across generated diagrams.
        drawing += elm.Line().down(1.0)
        drawing += elm.Dot(open=True).label("LEGEND", loc="right")
        legend_order = ["POWER", "GND", "I2C", "SPI", "UART", "PWM", "DIGITAL", "ANALOG", "OTHER"]
        for group in legend_order:
            drawing += elm.Line().down(0.6)
            drawing.push()
            color = self._signal_color(group)
            drawing += elm.Dot(color=color)
            drawing += elm.Line().right(1.2).color(color)
            drawing += elm.Dot(open=True, color=color).label(group, loc="right")
            drawing.pop()

    def _validate_connections(
        self,
        board: str,
        components: list[dict[str, Any]],
        connections: list[dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        board_u = (board or "").upper()

        def _norm_pin(value: str) -> str:
            return " ".join((value or "").upper().split())

        def _is_power(value: str) -> bool:
            pin = _norm_pin(value)
            return any(k in pin for k in ("5V", "3V3", "3.3V", "VCC", "VIN", "POWER"))

        def _is_gnd(value: str) -> bool:
            return "GND" in _norm_pin(value)

        def _extract_component(endpoint: str) -> str:
            text = (endpoint or "").strip()
            if not text:
                return ""
            return text.split()[0].upper()

        driven_endpoints: dict[str, list[str]] = {}

        def _has_uno_pin(pin_text: str, pin_name: str) -> bool:
            token = _norm_pin(pin_text)
            parts = token.split(" ")
            return any(part == pin_name for part in parts)

        for idx, conn in enumerate(connections, start=1):
            src = str(conn.get("from", "")).strip()
            dst = str(conn.get("to", "")).strip()
            signal = str(conn.get("signal", "")).strip().upper()
            src_n = _norm_pin(src)
            dst_n = _norm_pin(dst)

            if not src or not dst:
                warnings.append(f"[STD] N{idx:03d}: conexión incompleta (from/to vacío).")
                continue

            if src_n == dst_n:
                warnings.append(f"[STD] N{idx:03d}: fuente y destino son el mismo nodo ({src}).")

            if (_is_power(src) and _is_gnd(dst)) or (_is_gnd(src) and _is_power(dst)):
                warnings.append(f"[SAFETY] N{idx:03d}: posible corto entre POWER y GND ({src} -> {dst}).")

            driven_endpoints.setdefault(dst_n, []).append(src_n)

            # Arduino Uno standard bus hints.
            if "UNO" in board_u:
                if "SDA" in signal and "A4" not in src_n and "A4" not in dst_n:
                    warnings.append(f"[UNO] N{idx:03d}: SDA recomendado en A4.")
                if "SCL" in signal and "A5" not in src_n and "A5" not in dst_n:
                    warnings.append(f"[UNO] N{idx:03d}: SCL recomendado en A5.")
                if "MOSI" in signal and "D11" not in src_n and "D11" not in dst_n:
                    warnings.append(f"[UNO] N{idx:03d}: MOSI recomendado en D11.")
                if "MISO" in signal and "D12" not in src_n and "D12" not in dst_n:
                    warnings.append(f"[UNO] N{idx:03d}: MISO recomendado en D12.")
                if ("SCK" in signal or signal.endswith("CLK")) and "D13" not in src_n and "D13" not in dst_n:
                    warnings.append(f"[UNO] N{idx:03d}: SCK/CLK recomendado en D13.")

                if (
                    _has_uno_pin(src_n, "D0")
                    or _has_uno_pin(src_n, "D1")
                    or _has_uno_pin(dst_n, "D0")
                    or _has_uno_pin(dst_n, "D1")
                ):
                    warnings.append(f"[UNO] N{idx:03d}: evita D0/D1 para periféricos si usarás USB Serial.")

        # Components should typically have at least one GND and one power net.
        power_map: dict[str, bool] = {}
        gnd_map: dict[str, bool] = {}
        connected_map: dict[str, bool] = {}
        for conn in connections:
            for endpoint in (str(conn.get("from", "")), str(conn.get("to", ""))):
                cid = _extract_component(endpoint)
                if not cid or cid in {"UNO", "ARDUINO", "MCU"}:
                    continue
                connected_map[cid] = True
                if _is_power(endpoint):
                    power_map[cid] = True
                if _is_gnd(endpoint):
                    gnd_map[cid] = True

        for idx, comp in enumerate(components, start=1):
            cid = str(comp.get("id") or f"C{idx}").strip().upper()
            if not connected_map.get(cid):
                warnings.append(f"[STD] {cid}: componente sin conexiones.")
                continue
            if not power_map.get(cid):
                warnings.append(f"[POWER] {cid}: sin pin de alimentación declarado (VCC/5V/3V3/VIN).")
            if not gnd_map.get(cid):
                warnings.append(f"[POWER] {cid}: sin pin GND declarado.")

        # Multiple sources driving the same destination can indicate net conflict.
        for dst, src_list in driven_endpoints.items():
            uniq_src = sorted(set(src_list))
            if len(uniq_src) > 1:
                warnings.append(f"[CONFLICT] destino {dst} tiene múltiples fuentes: {', '.join(uniq_src)}.")

        # Deduplicate while preserving order.
        deduped: list[str] = []
        seen: set[str] = set()
        for item in warnings:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def _signal_group(self, signal: str) -> str:
        s = (signal or "").upper()
        if any(k in s for k in ("5V", "3V3", "VCC", "POWER", "VIN")):
            return "POWER"
        if "GND" in s:
            return "GND"
        if any(k in s for k in ("I2C", "SDA", "SCL")):
            return "I2C"
        if any(k in s for k in ("SPI", "MOSI", "MISO", "SCK", "CS")):
            return "SPI"
        if any(k in s for k in ("UART", "TX", "RX")):
            return "UART"
        if "PWM" in s:
            return "PWM"
        if any(k in s for k in ("A0", "A1", "A2", "A3", "A4", "A5", "ANALOG")):
            return "ANALOG"
        if any(k in s for k in ("D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12", "D13", "CLK", "DATA", "DIO")):
            return "DIGITAL"
        return "OTHER"

    def _signal_color(self, signal: str) -> str:
        group = self._signal_group(signal)
        return {
            "POWER": "#e11d48",   # red
            "GND": "#334155",     # slate
            "I2C": "#2563eb",     # blue
            "SPI": "#7c3aed",     # violet
            "UART": "#0d9488",    # teal
            "PWM": "#ea580c",     # orange
            "DIGITAL": "#059669", # green
            "ANALOG": "#ca8a04",  # amber
            "OTHER": "#6b7280",   # gray
        }.get(group, "#6b7280")

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
