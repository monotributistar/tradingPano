"""
api/routers/system.py — VPS / container system metrics
=======================================================

Exposes hardware and process metrics useful for monitoring a trading bot
running on a VPS.  All values are read via ``psutil`` from the host OS
namespace (or the container's cgroup if running in Docker).

Endpoints
---------
GET /api/system/metrics
    Snapshot of CPU, RAM, disk, and process RSS / uptime.

GET /api/system/uptime
    Simplified uptime-only endpoint (used by Dashboard header badge).
"""

import os
import time
from typing import Optional

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:  # pragma: no cover
    _PSUTIL_OK = False

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/system", tags=["system"])

# API process start time — used to compute process uptime
_PROCESS_START = time.time()


# ── Response models ────────────────────────────────────────────────────────────

class DiskInfo(BaseModel):
    path: str
    used_gb: float
    total_gb: float
    pct: float


class SystemMetrics(BaseModel):
    # CPU
    cpu_pct: float

    # RAM
    ram_pct: float
    ram_used_mb: float
    ram_total_mb: float

    # Disk (root partition)
    disk: DiskInfo

    # Current process
    process_rss_mb: float
    process_cpu_pct: float
    process_uptime_s: float
    process_threads: int

    # Host OS boot time (seconds ago)
    os_uptime_s: Optional[float] = None

    # Approximation of bot data directory usage
    data_dir_mb: Optional[float] = None


class UptimeInfo(BaseModel):
    process_uptime_s: float
    os_uptime_s: Optional[float] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dir_size_mb(path: str) -> Optional[float]:
    """Recursively sum file sizes under ``path`` (best-effort, non-blocking)."""
    try:
        total = 0
        for root, _dirs, files in os.walk(path):
            for fname in files:
                try:
                    total += os.path.getsize(os.path.join(root, fname))
                except OSError:
                    pass
        return round(total / 1_000_000, 2)
    except Exception:
        return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/metrics", response_model=SystemMetrics, summary="VPS system metrics snapshot")
def get_system_metrics() -> SystemMetrics:
    """
    Return a snapshot of CPU, RAM, disk, and process-level metrics.

    All values are best-effort: if ``psutil`` is unavailable (e.g. stripped
    Docker image) the endpoint returns HTTP 503 with an explanatory message.
    """
    if not _PSUTIL_OK:
        raise HTTPException(status_code=503, detail="psutil not installed — add to requirements.txt")

    # CPU — interval=0.2 gives a non-zero reading on first call
    cpu = psutil.cpu_percent(interval=0.2)

    # RAM
    vm = psutil.virtual_memory()

    # Disk (root)
    try:
        disk = psutil.disk_usage("/")
        disk_info = DiskInfo(
            path="/",
            used_gb=round(disk.used / 1e9, 2),
            total_gb=round(disk.total / 1e9, 2),
            pct=round(disk.percent, 1),
        )
    except Exception:
        disk_info = DiskInfo(path="/", used_gb=0, total_gb=0, pct=0)

    # Process
    proc = psutil.Process(os.getpid())
    with proc.oneshot():
        rss_mb = round(proc.memory_info().rss / 1e6, 2)
        proc_cpu = proc.cpu_percent()
        num_threads = proc.num_threads()

    # OS uptime
    try:
        os_uptime: Optional[float] = round(time.time() - psutil.boot_time(), 1)
    except Exception:
        os_uptime = None

    # Data directory size
    data_dir = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    data_mb = _dir_size_mb(data_dir)

    return SystemMetrics(
        cpu_pct=round(cpu, 1),
        ram_pct=round(vm.percent, 1),
        ram_used_mb=round(vm.used / 1e6, 1),
        ram_total_mb=round(vm.total / 1e6, 1),
        disk=disk_info,
        process_rss_mb=rss_mb,
        process_cpu_pct=round(proc_cpu, 1),
        process_uptime_s=round(time.time() - _PROCESS_START, 1),
        process_threads=num_threads,
        os_uptime_s=os_uptime,
        data_dir_mb=data_mb,
    )


@router.get("/uptime", response_model=UptimeInfo, summary="Process and OS uptime")
def get_uptime() -> UptimeInfo:
    """Lightweight uptime-only endpoint — used by the Dashboard header badge."""
    os_uptime: Optional[float] = None
    if _PSUTIL_OK:
        try:
            os_uptime = round(time.time() - psutil.boot_time(), 1)
        except Exception:
            pass

    return UptimeInfo(
        process_uptime_s=round(time.time() - _PROCESS_START, 1),
        os_uptime_s=os_uptime,
    )
