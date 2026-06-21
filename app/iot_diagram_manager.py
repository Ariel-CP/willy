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
    html_path: str = ""


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

    # ------------------------------------------------------------------
    # HTML wiring diagram
    # ------------------------------------------------------------------

    # Wire colors by signal type
    _WIRE_COLORS: dict[str, str] = {
        "VCC": "#ef4444", "5V": "#ef4444", "3.3V": "#f97316", "3V3": "#f97316",
        "GND": "#1e293b",
        "SDA": "#3b82f6", "SCL": "#06b6d4",
        "MOSI": "#8b5cf6", "MISO": "#a78bfa", "SCK": "#7c3aed", "CS": "#6d28d9",
        "TX": "#22c55e", "RX": "#16a34a",
        "PWM": "#f59e0b", "DIGITAL": "#f59e0b", "ANALOG": "#ec4899",
    }

    def _wire_color(self, signal: str) -> str:
        up = signal.upper()
        for key, color in self._WIRE_COLORS.items():
            if key in up:
                return color
        return "#94a3b8"

    def render_connection_html(
        self,
        title: str,
        board: str,
        components: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        html_path: str,
    ) -> bool:
        """Generate a standalone HTML file with a visual wiring diagram.

        Shows board + component blocks connected by colored wires.
        """
        board_label = (board or "MCU").upper()
        display_title = title or "Wiring Diagram"
        safe_board = board_label.replace(":", " ").replace("_", " ")

        # Collect unique signals to assign y positions
        rows: list[dict] = []
        for i, conn in enumerate(connections[:24]):
            rows.append({
                "from": str(conn.get("from", "")).strip() or f"PIN_{i}",
                "to": str(conn.get("to", "")).strip() or "?",
                "signal": str(conn.get("signal", "")).strip() or f"NET{i:02d}",
            })

        # --- SVG layout constants ---
        W, H = 900, max(320, 60 + len(rows) * 36 + 60)
        BOARD_X, BOARD_Y, BOARD_W, BOARD_H = 40, 60, 200, max(200, len(rows) * 32 + 40)
        COMP_X, COMP_Y, COMP_W = 620, 60, 200
        COMP_H = BOARD_H
        MID_X = (BOARD_X + BOARD_W + COMP_X) // 2

        svg_parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" style="max-width:100%;border-radius:12px">',
            f'<rect width="{W}" height="{H}" fill="#0f172a" rx="12"/>',
            # Board box
            f'<rect x="{BOARD_X}" y="{BOARD_Y}" width="{BOARD_W}" height="{BOARD_H}" '
            f'fill="#1e3a5f" stroke="#3b82f6" stroke-width="2" rx="8"/>',
            f'<text x="{BOARD_X + BOARD_W//2}" y="{BOARD_Y + 22}" text-anchor="middle" '
            f'font-family="monospace" font-size="13" font-weight="bold" fill="#93c5fd">{safe_board}</text>',
            # Component box
            f'<rect x="{COMP_X}" y="{COMP_Y}" width="{COMP_W}" height="{COMP_H}" '
            f'fill="#1a2e1a" stroke="#22c55e" stroke-width="2" rx="8"/>',
        ]

        # Component labels
        comp_names = list(dict.fromkeys(
            str(c.get("label") or c.get("type") or c.get("id") or "Component")
            for c in components
        ))[:4]
        for ci, cname in enumerate(comp_names):
            svg_parts.append(
                f'<text x="{COMP_X + COMP_W//2}" y="{COMP_Y + 22 + ci * 18}" '
                f'text-anchor="middle" font-family="monospace" font-size="12" '
                f'font-weight="bold" fill="#86efac">{cname[:22]}</text>'
            )

        # Wires + pin labels
        row_start_y = BOARD_Y + 48
        for i, row in enumerate(rows):
            y = row_start_y + i * 34
            color = self._wire_color(row["signal"])
            bx = BOARD_X + BOARD_W   # right edge of board
            cx = COMP_X              # left edge of comp box
            # Wire (bezier curve)
            svg_parts.append(
                f'<path d="M{bx},{y} C{MID_X},{y} {MID_X},{y} {cx},{y}" '
                f'fill="none" stroke="{color}" stroke-width="2.5" opacity="0.85"/>'
            )
            # Board pin dot + label
            svg_parts.append(f'<circle cx="{bx}" cy="{y}" r="4" fill="{color}"/>')
            svg_parts.append(
                f'<text x="{bx - 6}" y="{y + 4}" text-anchor="end" '
                f'font-family="monospace" font-size="11" fill="#e2e8f0">{row["from"]}</text>'
            )
            # Signal label in middle
            svg_parts.append(
                f'<text x="{MID_X}" y="{y - 6}" text-anchor="middle" '
                f'font-family="monospace" font-size="10" fill="{color}">{row["signal"]}</text>'
            )
            # Component pin dot + label
            svg_parts.append(f'<circle cx="{cx}" cy="{y}" r="4" fill="{color}"/>')
            svg_parts.append(
                f'<text x="{cx + 6}" y="{y + 4}" text-anchor="start" '
                f'font-family="monospace" font-size="11" fill="#e2e8f0">{row["to"]}</text>'
            )

        svg_parts.append('</svg>')
        svg_inline = "\n".join(svg_parts)

        # Connection table rows
        table_rows = ""
        for row in rows:
            color = self._wire_color(row["signal"])
            table_rows += (
                f'<tr>'
                f'<td style="color:#93c5fd">{row["from"]}</td>'
                f'<td><span style="background:{color};color:#fff;padding:2px 8px;'
                f'border-radius:4px;font-size:0.85em">{row["signal"]}</span></td>'
                f'<td style="color:#86efac">{row["to"]}</td>'
                f'</tr>'
            )

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{display_title} — Willy Wiring</title>
  <style>
    body{{margin:0;padding:20px;background:#0f172a;color:#e2e8f0;
         font-family:'Segoe UI',system-ui,sans-serif;}}
    h2{{margin:0 0 16px;font-size:1.15rem;color:#94a3b8}}
    .diagram{{margin-bottom:24px}}
    table{{border-collapse:collapse;width:100%;max-width:700px;
           background:#1e293b;border-radius:10px;overflow:hidden;box-shadow:0 2px 16px #0006}}
    th{{background:#0f172a;padding:10px 14px;text-align:left;
        font-size:0.8rem;color:#64748b;letter-spacing:.06em;text-transform:uppercase}}
    td{{padding:9px 14px;border-bottom:1px solid #334155;font-size:0.88rem}}
    tr:last-child td{{border-bottom:none}}
    .footer{{margin-top:14px;font-size:.72rem;color:#475569}}
  </style>
</head>
<body>
  <h2>🔌 {display_title}</h2>
  <div class="diagram">{svg_inline}</div>
  <table>
    <thead><tr><th>Placa ({safe_board})</th><th>Señal</th><th>Componente</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
  <p class="footer">Generado por Willy</p>
</body>
</html>
"""
        try:
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(html)
            return True
        except Exception:
            return False

    def generate_from_ino_source(
        self,
        ino_path: str,
        board: str = "Arduino Uno",
        title: str = "",
    ) -> DiagramResult:
        """Auto-detect components and connections from a .ino file and generate wiring HTML."""
        import re
        try:
            with open(ino_path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except Exception as exc:
            return DiagramResult(ok=False, message=f"Cannot read sketch: {exc}")

        display_title = title or os.path.splitext(os.path.basename(ino_path))[0]
        safe_title = self._safe_name(display_title)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = os.path.join(self.output_dir, f"{safe_title}_{stamp}_wiring.html")

        components: list[dict[str, Any]] = []
        connections: list[dict[str, Any]] = []

        # --- Board detection from source ---
        if re.search(r'esp32|ESP32', source):
            board = "ESP32"
            sda_pin, scl_pin = "GPIO21", "GPIO22"
        elif re.search(r'esp8266|ESP8266|NodeMCU', source):
            board = "ESP8266"
            sda_pin, scl_pin = "D2", "D1"
        else:
            board = "Arduino Uno"
            sda_pin, scl_pin = "A4", "A5"

        # --- LiquidCrystal_I2C ---
        m = re.search(r'LiquidCrystal_I2C\s+\w+\s*\(\s*(0x[0-9a-fA-F]+|\d+)\s*,\s*(\d+)\s*,\s*(\d+)', source)
        if m:
            addr, cols, rows_n = m.group(1), m.group(2), m.group(3)
            components.append({"id": "LCD1", "type": "LCD", "label": f"LCD I2C {cols}x{rows_n} ({addr})"})
            connections += [
                {"from": "5V",    "to": "LCD1 VCC", "signal": "5V"},
                {"from": "GND",   "to": "LCD1 GND", "signal": "GND"},
                {"from": sda_pin, "to": "LCD1 SDA", "signal": "SDA"},
                {"from": scl_pin, "to": "LCD1 SCL", "signal": "SCL"},
            ]

        # --- DHT sensor ---
        m = re.search(r'DHT\s+\w+\s*\(\s*(\d+)\s*,', source)
        if m:
            pin = m.group(1)
            components.append({"id": "DHT1", "type": "DHT", "label": f"DHT sensor (pin {pin})"})
            connections += [
                {"from": "3.3V",    "to": "DHT1 VCC",  "signal": "3.3V"},
                {"from": "GND",     "to": "DHT1 GND",  "signal": "GND"},
                {"from": f"D{pin}", "to": "DHT1 DATA", "signal": "DIGITAL"},
            ]

        # --- SSD1306 / OLED ---
        if re.search(r'Adafruit_SSD1306|SSD1306', source):
            components.append({"id": "OLED1", "type": "OLED", "label": "OLED SSD1306 I2C"})
            connections += [
                {"from": "3.3V",   "to": "OLED1 VCC", "signal": "3.3V"},
                {"from": "GND",    "to": "OLED1 GND", "signal": "GND"},
                {"from": sda_pin,  "to": "OLED1 SDA", "signal": "SDA"},
                {"from": scl_pin,  "to": "OLED1 SCL", "signal": "SCL"},
            ]

        # --- Servo ---
        m = re.search(r'(\w+)\.attach\s*\(\s*(\d+)', source)
        if m:
            pin = m.group(2)
            components.append({"id": "SRV1", "type": "Servo", "label": f"Servo (pin {pin})"})
            connections += [
                {"from": "5V",      "to": "SRV1 VCC",    "signal": "5V"},
                {"from": "GND",     "to": "SRV1 GND",    "signal": "GND"},
                {"from": f"D{pin}", "to": "SRV1 Signal", "signal": "PWM"},
            ]

        # --- BME280 ---
        if re.search(r'Adafruit_BME280|BME280', source):
            components.append({"id": "BME1", "type": "BME280", "label": "BME280 I2C"})
            connections += [
                {"from": "3.3V",  "to": "BME1 VCC", "signal": "3.3V"},
                {"from": "GND",   "to": "BME1 GND", "signal": "GND"},
                {"from": sda_pin, "to": "BME1 SDA", "signal": "SDA"},
                {"from": scl_pin, "to": "BME1 SCL", "signal": "SCL"},
            ]

        # --- Generic Wire.begin() (unknown I2C device) ---
        if not components and re.search(r'Wire\.begin', source):
            components.append({"id": "I2C1", "type": "I2C Device", "label": "I2C Device (addr desconocida)"})
            connections += [
                {"from": sda_pin, "to": "I2C1 SDA", "signal": "SDA"},
                {"from": scl_pin, "to": "I2C1 SCL", "signal": "SCL"},
            ]

        if not components:
            return DiagramResult(ok=False, message="No se detectaron componentes conocidos en el sketch.")

        ok = self.render_connection_html(display_title, board, components, connections, html_path)
        return DiagramResult(
            ok=ok,
            message=f"Wiring diagram: {len(connections)} conexiones detectadas.",
            html_path=html_path if ok else "",
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
