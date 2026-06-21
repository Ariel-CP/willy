"""Flowchart generation utilities (Mermaid-first) for software projects."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FlowchartResult:
    ok: bool
    message: str
    project_path: str = ""
    mmd_path: str = ""
    svg_path: str = ""
    png_path: str = ""
    html_path: str = ""


class FlowchartManager:
    """Build Mermaid flowcharts from source-code structure and save per project."""

    SKIP_DIRS = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "outputs",
        ".pio",
        "build",
        "dist",
        "__pycache__",
    }
    SUPPORTED_EXTS = {".py", ".cpp", ".c", ".h", ".hpp", ".ino", ".js", ".ts"}

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def generate_from_project(self, project_path: str, title: str = "") -> FlowchartResult:
        project_abs = os.path.abspath(project_path or "")
        if not project_abs or not os.path.isdir(project_abs):
            return FlowchartResult(
                ok=False,
                message=f"Project path not found: {project_abs or project_path}",
            )

        flow_dir = os.path.join(project_abs, "outputs", "flows")
        os.makedirs(flow_dir, exist_ok=True)

        display_title = (title or os.path.basename(project_abs) or "project_flow").strip()
        safe_title = self._safe_name(display_title)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_title}_{stamp}"

        mmd_path = os.path.join(flow_dir, f"{base_name}.mmd")
        svg_path = os.path.join(flow_dir, f"{base_name}.svg")
        png_path = os.path.join(flow_dir, f"{base_name}.png")

        outline = self._collect_project_outline(project_abs)
        mermaid = self._build_mermaid(display_title, outline)

        try:
            with open(mmd_path, "w", encoding="utf-8") as fh:
                fh.write(mermaid)
        except Exception as exc:  # noqa: BLE001
            return FlowchartResult(
                ok=False,
                message=f"Could not write Mermaid file: {exc}",
                project_path=project_abs,
            )

        render_message, svg_ready, png_ready = self._render_if_available(
            mmd_path,
            svg_path,
            png_path,
            display_title,
            outline,
        )

        # HTML (Mermaid JS en navegador — no requiere mmdc)
        html_path = os.path.join(flow_dir, f"{base_name}.html")
        html_ok = self.render_as_html(mmd_path, html_path, title=display_title)

        return FlowchartResult(
            ok=True,
            message=render_message,
            project_path=project_abs,
            mmd_path=mmd_path,
            svg_path=svg_path if svg_ready else "",
            png_path=png_path if png_ready else "",
            html_path=html_path if html_ok else "",
        )

    def generate_from_ino_sketch(self, sketch_path: str, title: str = "") -> FlowchartResult:
        """Generate an Arduino-specific flowchart from a .ino sketch file.

        Shows Power-On → setup() → loop() with the actual function calls inside each.
        """
        ino_abs = os.path.abspath(sketch_path)
        if not os.path.isfile(ino_abs):
            return FlowchartResult(ok=False, message=f"Sketch not found: {ino_abs}")

        sketch_dir = os.path.dirname(ino_abs)
        flow_dir = os.path.join(self.base_dir, "outputs", "flows")
        os.makedirs(flow_dir, exist_ok=True)

        display_title = (title or os.path.splitext(os.path.basename(ino_abs))[0]).strip()
        safe_title = self._safe_name(display_title)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_title}_{stamp}"

        mmd_path = os.path.join(flow_dir, f"{base_name}.mmd")
        svg_path = os.path.join(flow_dir, f"{base_name}.svg")
        png_path = os.path.join(flow_dir, f"{base_name}.png")

        try:
            with open(ino_abs, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except Exception as exc:
            return FlowchartResult(ok=False, message=f"Cannot read sketch: {exc}")

        flow = self._parse_arduino_flow(source)
        mermaid = self._build_arduino_mermaid(display_title, flow)

        try:
            with open(mmd_path, "w", encoding="utf-8") as fh:
                fh.write(mermaid)
        except Exception as exc:
            return FlowchartResult(ok=False, message=f"Cannot write .mmd: {exc}")

        # HTML (Mermaid JS en navegador — no requiere mmdc)
        html_path = os.path.join(flow_dir, f"{base_name}.html")
        html_ok = self.render_as_html(mmd_path, html_path, title=display_title)

        # Build a minimal outline for the SVG fallback renderer
        outline = {
            "files": [os.path.basename(ino_abs)],
            "file_functions": {os.path.basename(ino_abs): flow.get("all_funcs", [])},
        }
        render_msg, svg_ready, png_ready = self._render_if_available(
            mmd_path, svg_path, png_path, display_title, outline
        )

        return FlowchartResult(
            ok=True,
            message=render_msg,
            project_path=sketch_dir,
            mmd_path=mmd_path,
            svg_path=svg_path if svg_ready else "",
            png_path=png_path if png_ready else "",
            html_path=html_path if html_ok else "",
        )

    # ------------------------------------------------------------------
    # Arduino-specific parser
    # ------------------------------------------------------------------

    def _parse_arduino_flow(self, source: str) -> dict:
        """Extract setup/loop bodies and user-defined function names from .ino source."""
        # Strip line and block comments
        source_clean = re.sub(r"//[^\n]*", "", source)
        source_clean = re.sub(r"/\*.*?\*/", "", source_clean, flags=re.DOTALL)

        def _extract_body(name: str) -> list[str]:
            """Return list of statement lines from the body of a top-level function."""
            pattern = rf"void\s+{re.escape(name)}\s*\(\s*\)\s*\{{"
            m = re.search(pattern, source_clean)
            if not m:
                return []
            start = m.end()
            depth = 1
            i = start
            while i < len(source_clean) and depth:
                if source_clean[i] == "{":
                    depth += 1
                elif source_clean[i] == "}":
                    depth -= 1
                i += 1
            body = source_clean[start : i - 1]
            # Extract meaningful statements: function calls and assignments
            calls: list[str] = []
            for line in body.splitlines():
                line = line.strip().rstrip(";")
                if not line or line in ("{", "}"):
                    continue
                # Skip pure declarations (type name;)
                if re.match(r"^[A-Za-z_][A-Za-z0-9_:<>*&\s]+\s+[A-Za-z_]\w*$", line):
                    continue
                calls.append(line[:60])
            return calls[:8]

        # All user-defined function names (void and non-void)
        all_funcs = re.findall(
            r"^\s*(?:void|int|bool|float|double|long|unsigned|String|byte|char)\s+([A-Za-z_]\w*)\s*\(",
            source_clean,
            re.MULTILINE,
        )
        # Exclude setup/loop and built-in-ish names
        user_funcs = [f for f in dict.fromkeys(all_funcs)
                      if f not in ("setup", "loop", "main", "Serial")]

        return {
            "setup": _extract_body("setup"),
            "loop": _extract_body("loop"),
            "user_funcs": user_funcs[:6],
            "all_funcs": [f for f in dict.fromkeys(all_funcs)][:8],
            "includes": re.findall(r'#include\s*[<"]([^>"]+)[>"]', source),
        }

    def _build_arduino_mermaid(self, title: str, flow: dict) -> str:
        """Build a Mermaid flowchart showing Arduino setup/loop flow."""
        setup_calls: list[str] = flow.get("setup", [])
        loop_calls: list[str] = flow.get("loop", [])
        includes: list[str] = flow.get("includes", [])

        def _node_id(prefix: str, idx: int) -> str:
            return f"{prefix}{idx}"

        def _label(text: str) -> str:
            # Escape quotes and Mermaid special chars
            return text.replace('"', "'").replace("[", "(").replace("]", ")")

        lines: list[str] = ["flowchart TD"]

        # Header nodes
        lines.append(f'    START(["⚡ Power On / Reset"])')
        if includes:
            lib_list = ", ".join(includes[:4])
            lines.append(f'    LIBS["📚 Libraries: {_label(lib_list)}"]')
            lines.append("    START --> LIBS --> SETUP")
        else:
            lines.append("    START --> SETUP")

        lines.append(f'    SETUP["🔧 setup()"]')

        # setup() body nodes
        prev = "SETUP"
        for i, stmt in enumerate(setup_calls):
            nid = _node_id("S", i)
            lines.append(f'    {nid}["{_label(stmt)}"]')
            lines.append(f"    {prev} --> {nid}")
            prev = nid

        # Transition to loop
        lines.append(f'    LOOP{{"🔁 loop()"}}')
        lines.append(f"    {prev} --> LOOP")

        # loop() body nodes
        prev_loop = "LOOP"
        for i, stmt in enumerate(loop_calls):
            nid = _node_id("L", i)
            lines.append(f'    {nid}["{_label(stmt)}"]')
            lines.append(f"    {prev_loop} --> {nid}")
            prev_loop = nid

        # Loop back arrow
        lines.append(f"    {prev_loop} --> LOOP")

        return "\n".join(lines) + "\n"

    def _collect_project_outline(self, project_path: str) -> dict:
        files: list[str] = []
        file_functions: dict[str, list[str]] = {}

        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]

            for filename in sorted(filenames):
                _, ext = os.path.splitext(filename)
                if ext.lower() not in self.SUPPORTED_EXTS:
                    continue

                rel = os.path.relpath(os.path.join(root, filename), project_path)
                files.append(rel)
                if len(files) > 30:
                    break

            if len(files) > 30:
                break

        files = files[:30]

        for rel in files[:10]:
            abs_path = os.path.join(project_path, rel)
            functions = self._extract_functions(abs_path, rel)
            if functions:
                file_functions[rel] = functions[:4]

        return {
            "files": files,
            "file_functions": file_functions,
        }

    def _extract_functions(self, abs_path: str, rel_path: str) -> list[str]:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(12000)
        except Exception:
            return []

        ext = os.path.splitext(rel_path)[1].lower()
        names: list[str] = []

        if ext == ".py":
            matches = re.findall(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.MULTILINE)
            names.extend(matches)
        else:
            matches = re.findall(
                r"^\s*[A-Za-z_][A-Za-z0-9_:\s\*\&<>]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;\n]*\)\s*\{",
                text,
                re.MULTILINE,
            )
            names.extend(matches)

        normalized: list[str] = []
        seen = set()
        for name in names:
            if name in {"if", "for", "while", "switch", "return"}:
                continue
            if name not in seen:
                normalized.append(name)
                seen.add(name)
        return normalized

    def _build_mermaid(self, title: str, outline: dict) -> str:
        files: list[str] = outline.get("files", [])
        file_functions: dict[str, list[str]] = outline.get("file_functions", {})

        lines: list[str] = []
        lines.append("flowchart TD")
        lines.append(f"    A[\"Start: {self._label(title)}\"]")
        lines.append("    B[\"Scan project structure\"]")
        lines.append("    A --> B")

        if not files:
            lines.append("    C[\"No source files found\"]")
            lines.append("    B --> C")
            lines.append("    Z[\"Flow generated\"]")
            lines.append("    C --> Z")
            return "\n".join(lines) + "\n"

        prev_node = "B"
        for idx, rel in enumerate(files[:12], start=1):
            node = f"F{idx}"
            lines.append(f"    {node}[\"File: {self._label(rel)}\"]")
            lines.append(f"    {prev_node} --> {node}")
            prev_node = node

            fnames = file_functions.get(rel, [])
            for jdx, fname in enumerate(fnames[:2], start=1):
                fnode = f"{node}_{jdx}"
                lines.append(f"    {fnode}[\"Function: {self._label(fname)}\"]")
                lines.append(f"    {node} --> {fnode}")

        lines.append("    Z[\"Flow generated by Willy\"]")
        lines.append(f"    {prev_node} --> Z")
        return "\n".join(lines) + "\n"

    def _render_if_available(
        self,
        mmd_path: str,
        svg_path: str,
        png_path: str,
        title: str,
        outline: dict,
    ) -> tuple[str, bool, bool]:
        mmdc = self._resolve_mmdc_bin()
        if not mmdc:
            svg_ok = self._render_basic_svg(svg_path, title, outline)
            png_ok = self._render_png_from_svg(svg_path, png_path) if svg_ok else False
            if svg_ok and png_ok:
                return (
                    "Flowchart saved as .mmd and rendered locally as SVG/PNG (mmdc not found).",
                    True,
                    True,
                )
            if svg_ok:
                return (
                    "Flowchart saved as .mmd and rendered locally as SVG (mmdc not found).",
                    True,
                    False,
                )
            return (
                "Flowchart saved as .mmd, but no renderer available (mmdc missing and local SVG failed).",
                False,
                False,
            )

        svg_ok = self._run_mmdc(mmdc, mmd_path, svg_path, "svg")
        png_ok = self._run_mmdc(mmdc, mmd_path, png_path, "png")
        used_local_svg = False
        used_local_png = False

        if not svg_ok:
            svg_ok = self._render_basic_svg(svg_path, title, outline)
            used_local_svg = svg_ok

        if not png_ok and svg_ok:
            png_ok = self._render_png_from_svg(svg_path, png_path)
            used_local_png = png_ok

        if svg_ok or png_ok:
            if used_local_svg or used_local_png:
                return (
                    "Flowchart saved as .mmd; mmdc had partial/full failure, local renderer completed remaining output.",
                    svg_ok,
                    png_ok,
                )
            return ("Flowchart generated with mmdc from Mermaid source.", svg_ok, png_ok)

        return (
            "Flowchart saved as .mmd, but SVG/PNG render failed with both mmdc and local renderer.",
            False,
            False,
        )

    def _resolve_mmdc_bin(self) -> str:
        candidates = [
            shutil.which("mmdc"),
            os.path.expanduser("~/.local/node_modules/.bin/mmdc"),
            os.path.expanduser("~/.npm-global/bin/mmdc"),
            os.path.join(self.base_dir, "node_modules", ".bin", "mmdc"),
        ]

        for path in candidates:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return ""

    def render_as_html(self, mmd_path: str, html_path: str, title: str = "") -> bool:
        """Generate a standalone HTML file that renders the Mermaid diagram via CDN.

        Returns True on success.
        """
        try:
            with open(mmd_path, "r", encoding="utf-8") as fh:
                mmd_content = fh.read().strip()
        except Exception:
            return False

        display_title = title or os.path.splitext(os.path.basename(mmd_path))[0]
        # Escape for embedding inside a <pre> tag
        escaped = mmd_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{display_title} — Willy Flowchart</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: #0f1117;
      color: #e2e8f0;
      font-family: 'Segoe UI', system-ui, sans-serif;
    }}
    h2 {{
      margin: 0 0 18px;
      font-size: 1.2rem;
      color: #94a3b8;
      letter-spacing: 0.04em;
    }}
    .mermaid {{
      background: #1e293b;
      border-radius: 12px;
      padding: 28px 20px;
      display: inline-block;
      min-width: 400px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    }}
    .footer {{
      margin-top: 16px;
      font-size: 0.75rem;
      color: #475569;
    }}
  </style>
</head>
<body>
  <h2>⚡ {display_title}</h2>
  <div class="mermaid">
{mmd_content}
  </div>
  <p class="footer">Generado por Willy · {display_title}</p>
  <script>
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'dark',
      flowchart: {{ curve: 'basis', padding: 20 }},
    }});
  </script>
</body>
</html>
"""
        try:
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(html)
            return True
        except Exception:
            return False

    def _render_basic_svg(self, svg_path: str, title: str, outline: dict) -> bool:
        files: list[str] = (outline or {}).get("files", [])[:12]
        file_functions: dict[str, list[str]] = (outline or {}).get("file_functions", {})

        main_nodes: list[str] = [
            f"Start: {title or 'project_flow'}",
            "Scan project structure",
        ]
        if files:
            main_nodes.extend([f"File: {rel}" for rel in files])
        else:
            main_nodes.append("No source files found")
        main_nodes.append("Flow generated by Willy")

        width = 1180
        margin_top = 28
        main_x = 70
        main_w = 360
        main_h = 54
        main_gap = 28
        branch_x = 520
        branch_w = 290
        branch_h = 40
        branch_gap = 12

        y_positions: list[int] = []
        y_cursor = margin_top
        for _ in main_nodes:
            y_positions.append(y_cursor)
            y_cursor += main_h + main_gap

        branch_bottom = 0
        branch_start_index = 2
        for idx, rel in enumerate(files):
            fnames = file_functions.get(rel, [])[:2]
            if not fnames:
                continue
            file_index = branch_start_index + idx
            if file_index >= len(y_positions):
                continue
            anchor_y = y_positions[file_index]
            local_y = anchor_y
            for _ in fnames:
                if local_y + branch_h > branch_bottom:
                    branch_bottom = local_y + branch_h
                local_y += branch_h + branch_gap

        base_height = y_positions[-1] + main_h + margin_top
        height = max(base_height, branch_bottom + margin_top, 280)

        parts: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            "  <defs>",
            "    <marker id=\"arrow\" markerWidth=\"12\" markerHeight=\"8\" refX=\"10\" refY=\"4\" orient=\"auto\" markerUnits=\"strokeWidth\">",
            "      <path d=\"M0,0 L12,4 L0,8 z\" fill=\"#1f2937\"/>",
            "    </marker>",
            "  </defs>",
            "  <rect x=\"0\" y=\"0\" width=\"100%\" height=\"100%\" fill=\"#f8fafc\"/>",
        ]

        for idx, label in enumerate(main_nodes):
            y = y_positions[idx]
            lines = self._svg_lines(label, max_chars=34, max_lines=2)
            text_y = y + 23
            if len(lines) == 2:
                text_y = y + 18

            parts.append(
                f'  <rect x="{main_x}" y="{y}" rx="10" ry="10" width="{main_w}" height="{main_h}" fill="#ffffff" stroke="#0f172a" stroke-width="1.2"/>'
            )
            for line_idx, line in enumerate(lines):
                parts.append(
                    f'  <text x="{main_x + (main_w // 2)}" y="{text_y + (line_idx * 16)}" font-family="Arial, sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">{self._svg_escape(line)}</text>'
                )

            if idx < len(main_nodes) - 1:
                y1 = y + main_h
                y2 = y_positions[idx + 1]
                x_mid = main_x + (main_w // 2)
                parts.append(
                    f'  <line x1="{x_mid}" y1="{y1}" x2="{x_mid}" y2="{y2}" stroke="#1f2937" stroke-width="1.3" marker-end="url(#arrow)"/>'
                )

        for idx, rel in enumerate(files):
            fnames = file_functions.get(rel, [])[:2]
            if not fnames:
                continue
            file_index = branch_start_index + idx
            if file_index >= len(y_positions):
                continue

            from_x = main_x + main_w
            from_y = y_positions[file_index] + (main_h // 2)
            local_y = y_positions[file_index]

            for fname in fnames:
                lines = self._svg_lines(f"Function: {fname}", max_chars=30, max_lines=2)
                text_y = local_y + 22
                if len(lines) == 2:
                    text_y = local_y + 17

                parts.append(
                    f'  <line x1="{from_x}" y1="{from_y}" x2="{branch_x}" y2="{local_y + (branch_h // 2)}" stroke="#334155" stroke-width="1.2" marker-end="url(#arrow)"/>'
                )
                parts.append(
                    f'  <rect x="{branch_x}" y="{local_y}" rx="8" ry="8" width="{branch_w}" height="{branch_h}" fill="#eef2ff" stroke="#334155" stroke-width="1.1"/>'
                )
                for line_idx, line in enumerate(lines):
                    parts.append(
                        f'  <text x="{branch_x + (branch_w // 2)}" y="{text_y + (line_idx * 15)}" font-family="Arial, sans-serif" font-size="12" fill="#0f172a" text-anchor="middle">{self._svg_escape(line)}</text>'
                    )

                local_y += branch_h + branch_gap

        parts.append("</svg>")
        svg_text = "\n".join(parts) + "\n"

        try:
            with open(svg_path, "w", encoding="utf-8") as fh:
                fh.write(svg_text)
        except Exception:
            return False

        return os.path.isfile(svg_path)

    @staticmethod
    def _render_png_from_svg(svg_path: str, png_path: str) -> bool:
        if not os.path.isfile(svg_path):
            return False

        try:
            import cairosvg
        except Exception:
            return False

        try:
            cairosvg.svg2png(url=svg_path, write_to=png_path)
        except Exception:
            return False

        return os.path.isfile(png_path)

    @staticmethod
    def _svg_escape(text: str) -> str:
        value = text or ""
        value = value.replace("&", "&amp;")
        value = value.replace("<", "&lt;")
        value = value.replace(">", "&gt;")
        value = value.replace('"', "&quot;")
        value = value.replace("'", "&#39;")
        return value

    @staticmethod
    def _svg_lines(text: str, max_chars: int = 30, max_lines: int = 2) -> list[str]:
        words = (text or "").split()
        if not words:
            return [""]

        lines: list[str] = []
        idx = 0

        while idx < len(words) and len(lines) < max_lines:
            line_words: list[str] = []
            while idx < len(words):
                candidate = " ".join(line_words + [words[idx]])
                if not line_words or len(candidate) <= max_chars:
                    line_words.append(words[idx])
                    idx += 1
                else:
                    break

            if not line_words:
                break

            if len(lines) == max_lines - 1 and idx < len(words):
                tail = " ".join(line_words + words[idx:])
                if len(tail) > max_chars:
                    tail = tail[: max_chars - 3].rstrip() + "..."
                lines.append(tail)
                return lines

            line = " ".join(line_words)
            if len(line) > max_chars:
                line = line[: max_chars - 3].rstrip() + "..."
            lines.append(line)

        return lines[:max_lines] or [""]

    @staticmethod
    def _run_mmdc(mmdc_bin: str, input_path: str, output_path: str, out_type: str) -> bool:
        cmd = [
            mmdc_bin,
            "-i",
            input_path,
            "-o",
            output_path,
            "-e",
            out_type,
            "-b",
            "transparent",
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
                timeout=45,
            )
        except Exception:
            return False

        return proc.returncode == 0 and os.path.isfile(output_path)

    @staticmethod
    def _safe_name(name: str) -> str:
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "project_flow").strip())
        value = value.strip("._")
        return value or "project_flow"

    @staticmethod
    def _label(text: str) -> str:
        clean = (text or "").replace('"', "'")
        clean = clean.replace("[", "(").replace("]", ")")
        return clean
