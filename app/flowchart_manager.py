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

        return FlowchartResult(
            ok=True,
            message=render_message,
            project_path=project_abs,
            mmd_path=mmd_path,
            svg_path=svg_path if svg_ready else "",
            png_path=png_path if png_ready else "",
        )

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
