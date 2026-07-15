#!/usr/bin/env python3
"""Recommend LLM model profiles from local hardware and available providers."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from arka.llm.skill_profiles import TASK_PROFILES, known_task_profiles

# NL routing — "select best model for my pc", "optimize models for my hardware", …
_SELECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(?:select|pick|choose|find|recommend|suggest)\s+(?:the\s+)?"
        r"(?:best\s+)?(?:llm\s+)?models?\s+(?:for|based on|from|using)\s+"
        r"(?:my\s+)?(?:pc|mac|hardware|computer|machine|laptop|system|resources)\b"
    ),
    re.compile(r"(?i)\bwhat\s+(?:llm\s+)?model\s+should\s+I\s+use\b"),
    re.compile(
        r"(?i)\boptimize\s+(?:llm\s+)?models?\s+for\s+(?:my\s+)?"
        r"(?:hardware|pc|mac|computer|machine|laptop|system)\b"
    ),
    re.compile(
        r"(?i)\bbest\s+(?:llm\s+)?model(?:s)?\s+for\s+(?:my\s+)?"
        r"(?:pc|mac|hardware|computer|machine|laptop|system)\b"
    ),
    re.compile(r"(?i)\b(?:auto[- ]?)?(?:configure|apply|set)\s+(?:llm\s+)?models?\s+(?:for|from|based on)\s+(?:my\s+)?(?:hardware|pc|mac|resources)\b"),
    re.compile(r"(?i)^(?:select_model|model_select|best_model|model_advisor)\b"),
    re.compile(
        r"(?i)\b(?:select|pick|choose)\s+(?:the\s+)?best\s+(?:llm\s+)?models?\b"
    ),
    re.compile(r"(?i)\b(?:select|pick|choose)\s+(?:the\s+)?(?:best\s+)?model\b"),
    re.compile(r"(?i)\b(?:best|strongest)\s+(?:runnable\s+)?local\s+(?:llm\s+)?model\b"),
    re.compile(r"(?i)\brun\s+the\s+best\s+(?:local|offline)\s+model\b"),
    re.compile(r"(?i)\b(?:list)\s+(?:the\s+)?\d*\s*(?:(?:(?:strongest|best)\s+)?runnable|(?:strongest|best))\s+(?:local\s+)?models?\b"),
)

_APPLY_RE = re.compile(r"(?i)\b(?:apply|auto[- ]?apply|save|write|configure)\b")
_LOCAL_RE = re.compile(r"(?i)\b(?:local|offline|on[- ]device|on device)\b")


@dataclass
class HardwareSnapshot:
    platform: str
    cpu_cores: int
    cpu_model: str
    ram_total_gb: float
    ram_available_gb: float | None
    gpu_kind: str  # none | integrated | cuda | mps | metal
    gpu_name: str
    gpu_vram_gb: float | None
    disk_free_gb: float
    disk_total_gb: float
    on_battery: bool | None
    ollama_models: list[str] = field(default_factory=list)

    @property
    def ram_total_mb(self) -> int:
        return int(self.ram_total_gb * 1024)


@dataclass
class ProfileRecommendation:
    profile: str
    model: str
    reason: str


@dataclass
class AdvisorReport:
    tier: str
    tier_label: str
    hardware: HardwareSnapshot
    recommendations: list[ProfileRecommendation]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_label": self.tier_label,
            "hardware": asdict(self.hardware),
            "recommendations": [asdict(r) for r in self.recommendations],
            "notes": list(self.notes),
        }


TIER_LABELS = {
    "minimal": "Minimal — cloud-only, tiny/fast models",
    "cloud_light": "Cloud-light — fast cloud APIs, no local LLM",
    "balanced": "Balanced — cloud primary, optional small local models",
    "local_capable": "Local-capable — mix local Ollama + cloud for heavy tasks",
    "local_heavy": "Local-heavy — prefer local models when Ollama is available",
}


def _run(cmd: list[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _bytes_to_gb(n: int | float) -> float:
    return round(float(n) / (1024**3), 2)


def _parse_size_gb(text: str) -> float | None:
    raw = (text or "").strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMGT]?)(?:I?B)?$", raw)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    mult = {"": 1 / (1024**3), "K": 1 / (1024**2), "M": 1 / 1024, "G": 1, "T": 1024}.get(unit)
    if mult is None:
        return None
    return round(val * mult, 2)


def _cpu_model() -> str:
    try:
        if sys.platform == "darwin":
            proc = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        elif sys.platform.startswith("linux"):
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _cpu_cores() -> int:
    try:
        from arka.core.compute import cpu_count

        return cpu_count()
    except ImportError:
        return max(1, os.cpu_count() or 1)


def _ram_bytes() -> tuple[int, int | None]:
    total = 0
    available: int | None = None
    if sys.platform == "darwin":
        proc = _run(["sysctl", "-n", "hw.memsize"])
        if proc.returncode == 0 and proc.stdout.strip().isdigit():
            total = int(proc.stdout.strip())
        proc = _run(["vm_stat"])
        if proc.returncode == 0 and total:
            page_size = 4096
            ps = _run(["sysctl", "-n", "hw.pagesize"])
            if ps.returncode == 0 and ps.stdout.strip().isdigit():
                page_size = int(ps.stdout.strip())
            free_pages = 0
            for line in proc.stdout.splitlines():
                if "Pages free:" in line:
                    free_pages += int(re.sub(r"[^\d]", "", line.split(":")[1]) or "0")
                elif "Pages inactive:" in line:
                    free_pages += int(re.sub(r"[^\d]", "", line.split(":")[1]) or "0")
            available = free_pages * page_size
    elif sys.platform.startswith("linux"):
        try:
            info: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    key, _, val = line.partition(":")
                    info[key.strip()] = int(val.strip().split()[0]) * 1024
            total = info.get("MemTotal", 0)
            available = info.get("MemAvailable") or info.get("MemFree")
        except OSError:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total = int(stat.ullTotalPhys)
                available = int(stat.ullAvailPhys)
        except (AttributeError, OSError):
            pass
    return total, available


def _disk_gb(path: str = "/") -> tuple[float, float]:
    try:
        usage = shutil.disk_usage(path)
        return _bytes_to_gb(usage.free), _bytes_to_gb(usage.total)
    except OSError:
        return 0.0, 0.0


def _gpu_info() -> tuple[str, str, float | None]:
    """Return (kind, name, vram_gb)."""
    if shutil.which("nvidia-smi"):
        proc = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ]
        )
        if proc.returncode == 0 and proc.stdout.strip():
            line = proc.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            name = parts[0] if parts else "CUDA GPU"
            vram = None
            if len(parts) > 1:
                try:
                    vram = round(float(parts[1]) / 1024, 2)
                except ValueError:
                    vram = None
            return "cuda", name, vram

    if sys.platform == "darwin":
        proc = _run(["system_profiler", "SPDisplaysDataType"])
        if proc.returncode == 0 and proc.stdout.strip():
            name_m = re.search(r"Chipset Model:\s+(.+)", proc.stdout)
            name = name_m.group(1).strip() if name_m else "Apple GPU"
            if "Apple" in name or platform.machine().lower() in {"arm64", "aarch64"}:
                return "mps", name, None
            return "metal", name, None

    if sys.platform.startswith("linux") and shutil.which("lspci"):
        proc = _run(["lspci"])
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if re.search(r"VGA|3D|Display", line, re.I):
                    name = re.sub(r".*:\s*", "", line).strip()
                    kind = "integrated" if re.search(r"Intel|AMD.*Radeon.*Graphics", name, re.I) else "integrated"
                    return kind, name, None
    return "none", "", None


def _on_battery() -> bool | None:
    if sys.platform == "darwin" and shutil.which("pmset"):
        proc = _run(["pmset", "-g", "batt"])
        if proc.returncode == 0:
            if re.search(r"\bAC Power\b", proc.stdout):
                return False
            if re.search(r"\bBattery Power\b", proc.stdout):
                return True
    elif sys.platform.startswith("linux"):
        for base in Path("/sys/class/power_supply").glob("BAT*"):
            status = base / "status"
            try:
                val = status.read_text(encoding="utf-8").strip().lower()
            except OSError:
                continue
            if val in {"discharging", "charging", "full", "not charging"}:
                return val == "discharging"
    return None


def _ollama_models() -> list[str]:
    try:
        from arka.llm.fallback import fetch_ollama_models_live

        return fetch_ollama_models_live()
    except ImportError:
        return []


def _live_platform() -> str:
    try:
        from arka.platform_info import system as cached_system

        return cached_system()
    except ImportError:
        if sys.platform == "darwin":
            return "macos"
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform == "win32":
            return "windows"
        return sys.platform


def probe_hardware(*, include_ollama: bool = True) -> HardwareSnapshot:
    total_bytes, avail_bytes = _ram_bytes()
    disk_free, disk_total = _disk_gb("/" if sys.platform != "win32" else "C:\\")
    gpu_kind, gpu_name, gpu_vram = _gpu_info()
    return HardwareSnapshot(
        platform=_live_platform(),
        cpu_cores=_cpu_cores(),
        cpu_model=_cpu_model(),
        ram_total_gb=_bytes_to_gb(total_bytes) if total_bytes else 0.0,
        ram_available_gb=_bytes_to_gb(avail_bytes) if avail_bytes else None,
        gpu_kind=gpu_kind,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram,
        disk_free_gb=disk_free,
        disk_total_gb=disk_total,
        on_battery=_on_battery(),
        ollama_models=_ollama_models() if include_ollama else [],
    )


def classify_tier(hw: HardwareSnapshot) -> str:
    ram = hw.ram_total_gb
    vram = hw.gpu_vram_gb or 0.0
    gpu = hw.gpu_kind

    if ram < 8:
        base = "minimal"
    elif ram < 16 and gpu in {"none", "integrated"}:
        base = "cloud_light"
    elif gpu == "cuda" and (vram >= 16 or ram >= 64):
        base = "local_heavy"
    elif gpu == "cuda" and vram >= 8:
        base = "local_capable"
    elif gpu in {"mps", "metal"} and ram >= 32:
        base = "local_heavy"
    elif gpu in {"mps", "metal"} and ram >= 16:
        base = "local_capable"
    elif ram >= 32:
        base = "local_capable"
    elif ram >= 16:
        base = "balanced"
    else:
        base = "cloud_light"

    if hw.on_battery and base in {"local_heavy", "local_capable"}:
        return "balanced"
    if hw.on_battery and base == "balanced":
        return "cloud_light"
    if hw.disk_free_gb and hw.disk_free_gb < 8 and base in {"local_heavy", "local_capable"}:
        return "balanced"
    return base


def _provider_available(name: str) -> bool:
    try:
        from arka.llm.fallback import provider_available

        return provider_available(name)
    except ImportError:
        return False


_VISION_OLLAMA_RE = re.compile(r"(?i)(llava|moondream|bakllava|minicpm-v|\bvision\b)")


def _pick_ollama_model(models: list[str], *, prefer_local: bool, text_only: bool = True) -> str:
    if not models:
        return ""
    pool = models
    if text_only:
        text_models = [m for m in models if not _VISION_OLLAMA_RE.search(m)]
        if text_models:
            pool = text_models
    local = [m for m in pool if ":cloud" not in m.lower()]
    cloud = [m for m in pool if ":cloud" in m.lower()]
    pick_pool = local if prefer_local and local else (local or cloud or pool)
    ranked = sorted(pick_pool, key=lambda m: (_ollama_rank(m), m.lower()))
    return ranked[0] if ranked else ""


def _ollama_rank(model_id: str) -> tuple[int, int, str]:
    mid = model_id.lower()
    cloud = 1 if ":cloud" in mid else 0
    size = 99
    m = re.search(r":(\d+)b\b", mid)
    if m:
        size = int(m.group(1))
    elif "1b" in mid or "1.5b" in mid:
        size = 1
    tiny = 0 if size <= 3 else (1 if size <= 8 else 2)
    return (cloud, tiny, mid)


def best_runnable_local_model(hw: HardwareSnapshot | None = None) -> str:
    """Return the strongest installed Ollama model likely to fit this machine."""
    snap = hw or probe_hardware()
    models = [m for m in snap.ollama_models if ":cloud" not in m.lower() and not _VISION_OLLAMA_RE.search(m)]
    if not models:
        return ""
    budget = (snap.gpu_vram_gb or 0.0) or (snap.ram_available_gb or snap.ram_total_gb * 0.6)

    def size(model: str) -> float:
        match = re.search(r":(\d+(?:\.\d+)?)b\b", model.lower())
        return float(match.group(1)) if match else 7.0

    # Rough conservative fit: quantized models generally need ~0.8 GB/B,
    # with headroom for the OS and context window.
    runnable = [m for m in models if size(m) * 0.8 <= max(1.0, budget - 1.5)]
    pool = runnable or models
    return max(pool, key=lambda m: (size(m), _ollama_rank(m)[2]))


def strongest_runnable_local_models(hw: HardwareSnapshot | None = None, *, limit: int = 5) -> list[str]:
    """Return installed local models ranked strongest-first for this hardware."""
    snap = hw or probe_hardware()
    models = [m for m in snap.ollama_models if ":cloud" not in m.lower() and not _VISION_OLLAMA_RE.search(m)]
    budget = (snap.gpu_vram_gb or 0.0) or (snap.ram_available_gb or snap.ram_total_gb * 0.6)

    def size(model: str) -> float:
        match = re.search(r":(\d+(?:\.\d+)?)b\b", model.lower())
        return float(match.group(1)) if match else 7.0

    runnable = [m for m in models if size(m) * 0.8 <= max(1.0, budget - 1.5)] or models
    return sorted(runnable, key=lambda m: (size(m), m.lower()), reverse=True)[: max(1, limit)]


def _openrouter_default_model() -> str:
    try:
        from arka.llm.providers import get_provider

        spec = get_provider("openrouter")
        if spec and spec.default_model:
            return spec.default_model
    except ImportError:
        pass
    return "anthropic/claude-sonnet-4"


def _cloud_route_model() -> str:
    if _provider_available("groq"):
        return "groq/llama-3.1-8b-instant"
    if _provider_available("gemini"):
        return "gemini/gemini-2.0-flash"
    if _provider_available("openrouter"):
        return f"openrouter/{_openrouter_default_model()}"
    return "groq/llama-3.1-8b-instant"


def _cloud_chat_model(*, fast: bool = False) -> str:
    if fast and _provider_available("groq"):
        return "groq/llama-3.3-70b-versatile"
    if _provider_available("gemini"):
        return "gemini/gemini-2.5-flash" if not fast else "gemini/gemini-2.0-flash"
    if _provider_available("groq"):
        return "groq/llama-3.3-70b-versatile"
    if _provider_available("openrouter"):
        return f"openrouter/{_openrouter_default_model()}"
    return "gemini/gemini-2.5-flash"


def _tier_profile_models(tier: str, hw: HardwareSnapshot) -> dict[str, tuple[str, str]]:
    """profile -> (model, reason)."""
    ollama = hw.ollama_models
    has_ollama = bool(ollama) and _provider_available("ollama")
    local_small = _pick_ollama_model(ollama, prefer_local=True) if has_ollama else ""
    local_mid = _pick_ollama_model(
        [m for m in ollama if _ollama_rank(m)[1] <= 1] or ollama,
        prefer_local=True,
    ) if has_ollama else ""
    local_best = _pick_ollama_model(ollama, prefer_local=True) if has_ollama else ""

    route_cloud = _cloud_route_model()
    chat_fast = _cloud_chat_model(fast=True)
    chat_balanced = _cloud_chat_model(fast=False)

    if tier == "minimal":
        return {
            "route": (route_cloud, "Tiny cloud model — low RAM"),
            "chat": (chat_fast, "Fast cloud model — <8GB RAM"),
            "summarize": (chat_fast, "Fast cloud summarization"),
            "research": (chat_fast, "Fast cloud research"),
            "agent": (chat_balanced, "Capable cloud agent"),
            "pdf": (chat_balanced, "Cloud RAG Q&A"),
            "predictions": (chat_balanced, "Cloud analysis"),
            "compose_video": (chat_fast, "Fast script generation"),
            "compose_slides": (chat_fast, "Fast slide script generation"),
            "default": (chat_fast, "General fast cloud default"),
        }

    if tier == "cloud_light":
        return {
            "route": (route_cloud, "Fast routing model"),
            "chat": (chat_balanced, "Balanced cloud chat"),
            "summarize": (chat_balanced, "Cloud summarization"),
            "research": (chat_balanced, "Cloud deep research"),
            "agent": (chat_balanced, "Cloud multi-step agent"),
            "pdf": (chat_balanced, "Cloud document Q&A"),
            "predictions": (chat_balanced, "Cloud market analysis"),
            "compose_video": (chat_balanced, "Cloud script writing"),
            "compose_slides": (chat_balanced, "Cloud slide script writing"),
            "default": (chat_balanced, "General cloud default"),
        }

    if tier == "balanced":
        route = f"ollama/{local_small}" if local_small else route_cloud
        chat = f"ollama/{local_mid}" if local_mid else chat_balanced
        return {
            "route": (route, "Small local or fast cloud routing"),
            "chat": (chat, "Local small model or cloud chat"),
            "summarize": (chat_balanced, "Cloud for long-context summarize"),
            "research": (chat_balanced, "Cloud for web research"),
            "agent": (chat_balanced, "Cloud agent for tool use"),
            "pdf": (chat_balanced, "Cloud for PDF RAG"),
            "predictions": (chat_balanced, "Cloud for analysis"),
            "compose_video": (chat_balanced, "Cloud script generation"),
            "compose_slides": (chat_balanced, "Cloud slide script generation"),
            "default": (chat, "Balanced default"),
        }

    if tier == "local_capable":
        route = f"ollama/{local_small or local_mid}" if has_ollama else route_cloud
        chat = f"ollama/{local_mid or local_best}" if has_ollama else chat_balanced
        agent = f"ollama/{local_best}" if local_best else chat_balanced
        return {
            "route": (route, "Local routing when Ollama available"),
            "chat": (chat, "Local mid-size chat model"),
            "summarize": (chat_balanced, "Cloud for long summaries"),
            "research": (chat_balanced, "Cloud for live web research"),
            "agent": (agent, "Local or cloud agent"),
            "pdf": (chat_balanced, "Cloud for document RAG"),
            "predictions": (chat_balanced, "Cloud for market data"),
            "compose_video": (chat, "Local script drafts"),
            "compose_slides": (chat, "Local slide script drafts"),
            "default": (chat, "Local-capable default"),
        }

    # local_heavy
    route = f"ollama/{local_small or local_mid}" if has_ollama else route_cloud
    chat = f"ollama/{local_best or local_mid}" if has_ollama else chat_balanced
    agent = f"ollama/{local_best}" if local_best else chat_balanced
    return {
        "route": (route, "Local fast routing"),
        "chat": (chat, "Best local chat model"),
        "summarize": (chat, "Local summarization"),
        "research": (chat_balanced, "Cloud for live web research"),
        "agent": (agent, "Best local agent model"),
        "pdf": (chat_balanced, "Cloud for heavy PDF RAG"),
        "predictions": (chat_balanced, "Cloud for live market data"),
        "compose_video": (chat, "Local script generation"),
        "compose_slides": (chat, "Local slide script generation"),
        "default": (chat, "Local-first default"),
    }


def build_report(hw: HardwareSnapshot | None = None) -> AdvisorReport:
    snap = hw or probe_hardware()
    tier = classify_tier(snap)
    mapping = _tier_profile_models(tier, snap)
    recs: list[ProfileRecommendation] = []
    for profile in known_task_profiles():
        model, reason = mapping.get(profile, (_cloud_chat_model(), "Fallback cloud"))
        recs.append(ProfileRecommendation(profile=profile, model=model, reason=reason))

    notes: list[str] = []
    if sys.platform == "darwin" and ("apple" in snap.cpu_model.lower() or snap.gpu_kind in {"mps", "metal"}):
        notes.append("Apple Silicon detected — consider MLX-native models and leave memory headroom for the OS/context.")
    model_text = " ".join(snap.ollama_models).lower()
    if any(tag in model_text for tag in ("moe", "mixtral", "qwen3", "deepseek")):
        notes.append("MoE-capable model detected — ranking should consider active parameters, not only total parameters.")
    if any(tag in model_text for tag in ("mtp", "speculative", "qwen3")):
        notes.append("Speculative/MTP-capable model hint detected — verify runtime support for faster local decoding.")
    if snap.on_battery:
        notes.append("On battery — preferring lighter cloud models where possible.")
    if snap.disk_free_gb and snap.disk_free_gb < 15:
        notes.append(f"Low disk free ({snap.disk_free_gb} GB) — local model pulls may be slow.")
    if not snap.ollama_models and tier in {"balanced", "local_capable", "local_heavy"}:
        notes.append("Ollama not reachable — run `ollama serve` and pull a model for local tiers.")
    has_gemini = _provider_available("gemini")
    has_groq = _provider_available("groq")
    has_openrouter = _provider_available("openrouter")
    if not has_gemini and not has_groq and not has_openrouter:
        notes.append(
            "No cloud LLM keys detected — set GEMINI_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY in .env."
        )
    elif has_openrouter and not has_gemini and not has_groq:
        notes.append("OpenRouter is the primary cloud provider (no direct Gemini/Groq keys).")

    return AdvisorReport(
        tier=tier,
        tier_label=TIER_LABELS.get(tier, tier),
        hardware=snap,
        recommendations=recs,
        notes=notes,
    )


def format_report(report: AdvisorReport, *, json_out: bool = False) -> str:
    if json_out:
        return json.dumps(report.to_dict(), indent=2)

    lines = [
        "━━━ Model advisor ━━━",
        f"Tier: {report.tier} — {report.tier_label}",
        "",
        "Hardware:",
        f"  Platform: {report.hardware.platform}",
        f"  CPU:      {report.hardware.cpu_model} ({report.hardware.cpu_cores} cores)",
        f"  RAM:      {report.hardware.ram_total_gb} GB total"
        + (f", {report.hardware.ram_available_gb} GB available" if report.hardware.ram_available_gb else ""),
        f"  GPU:      {report.hardware.gpu_name or 'none'} ({report.hardware.gpu_kind})"
        + (f", {report.hardware.gpu_vram_gb} GB VRAM" if report.hardware.gpu_vram_gb else ""),
        f"  Disk:     {report.hardware.disk_free_gb} GB free / {report.hardware.disk_total_gb} GB total",
    ]
    if report.hardware.on_battery is not None:
        lines.append(f"  Power:    {'battery' if report.hardware.on_battery else 'AC'}")
    if report.hardware.ollama_models:
        preview = ", ".join(report.hardware.ollama_models[:5])
        extra = f" (+{len(report.hardware.ollama_models) - 5} more)" if len(report.hardware.ollama_models) > 5 else ""
        lines.append(f"  Ollama:   {preview}{extra}")
    lines.extend(["", "Recommended profiles (ai-skill-model):"])
    for rec in report.recommendations:
        desc = TASK_PROFILES.get(rec.profile, {}).get("description", "")
        lines.append(f"  {rec.profile:14} {rec.model}")
        lines.append(f"                 {rec.reason}" + (f" — {desc}" if desc else ""))
    if report.notes:
        lines.append("")
        lines.append("Notes:")
        for note in report.notes:
            lines.append(f"  • {note}")
    lines.extend(
        [
            "",
            "Apply:  select_model --apply",
            "        ai-skill-model <profile> <provider/model>",
        ]
    )
    return "\n".join(lines)


def apply_recommendations(report: AdvisorReport | None = None) -> Path:
    from arka.llm.skill_models import set_skill_model, skill_models_path

    rep = report or build_report()
    for rec in rep.recommendations:
        set_skill_model(rec.profile, rec.model)
    return skill_models_path()


def is_model_select_query(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    return any(p.search(clean) for p in _SELECT_PATTERNS)


def nl_to_argv(text: str) -> list[str]:
    clean = (text or "").strip()
    if not is_model_select_query(clean):
        return []
    argv: list[str] = []
    if _APPLY_RE.search(clean):
        argv.append("--apply")
    if _LOCAL_RE.search(clean):
        argv.append("--local")
    count = re.search(r"\blist\s+(\d+)\s+(?:strongest|best|runnable)", clean, re.I)
    if count:
        if "--local" not in argv:
            argv.append("--local")
        argv.extend(["--top", count.group(1)])
    if re.search(r"(?i)\bjson\b", clean):
        argv.append("--json")
    return argv


def cmd_recommend(args: argparse.Namespace) -> int:
    report = build_report()
    if getattr(args, "local", False):
        models = strongest_runnable_local_models(report.hardware, limit=getattr(args, "top", 1))
        model = models[0] if models else ""
        if not model:
            print("No runnable local Ollama model found. Start Ollama and pull one first.", file=sys.stderr)
            return 1
        if getattr(args, "top", 1) > 1:
            print("Strongest runnable local models:")
            for index, candidate in enumerate(models, 1):
                print(f"  {index}. ollama/{candidate}")
        else:
            print(f"Best runnable local model: ollama/{model}")
        if getattr(args, "run", ""):
            ollama = shutil.which("ollama")
            if not ollama:
                print("Ollama is not installed or not on PATH.", file=sys.stderr)
                return 1
            return subprocess.call([ollama, "run", model, args.run])
        if getattr(args, "apply", False):
            for profile in known_task_profiles():
                from arka.llm.skill_models import set_skill_model

                set_skill_model(profile, f"ollama/{model}")
            print("Applied local model to all skill profiles.")
        return 0
    print(format_report(report, json_out=bool(getattr(args, "json", False))))
    if getattr(args, "apply", False):
        path = apply_recommendations(report)
        print(f"\nApplied profile models → {path}")
    return 0


def cmd_probe(_args: argparse.Namespace) -> int:
    hw = probe_hardware()
    print(json.dumps(asdict(hw), indent=2))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    if is_model_select_query(args.text):
        argv = nl_to_argv(args.text)
        print(" ".join(argv) if argv else "recommend")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recommend LLM models from PC resources")
    sub = parser.add_subparsers(dest="cmd")

    p_rec = sub.add_parser("recommend", help="Show hardware-based model recommendations")
    p_rec.add_argument("--apply", action="store_true", help="Write recommendations to llm-skill-models.json")
    p_rec.add_argument("--json", action="store_true", help="JSON output")
    p_rec.add_argument("--local", action="store_true", help="Choose the strongest installed model that fits locally")
    p_rec.add_argument("--run", metavar="PROMPT", help="Run a prompt with the selected local model")
    p_rec.add_argument("--top", type=int, default=1, help="List this many local models (use with --local)")
    p_rec.set_defaults(func=cmd_recommend)

    p_probe = sub.add_parser("probe", help="Dump hardware snapshot as JSON")
    p_probe.set_defaults(func=cmd_probe)

    p_parse = sub.add_parser("parse", help="Parse NL into select_model argv")
    p_parse.add_argument("text")
    p_parse.set_defaults(func=cmd_parse)

    args, extras = parser.parse_known_args(argv)
    if args.cmd is None:
        args.cmd = "recommend"
        args.apply = "--apply" in extras
        args.json = "--json" in extras
        args.func = cmd_recommend
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
