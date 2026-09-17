"""Operating systems and hardware a computer can be created with, and what each one supports.

Options are only selectable when a real provider backs them; everything else is listed with the reason
it is unavailable, so the dashboard never offers hardware that cannot be delivered.

  linux    OpenSandbox container with the Cubicle desktop image. Always available.
  windows  OpenSandbox's Windows profile (dockur/windows under KVM/QEMU). Operators enable it only on
           hosts with /dev/kvm and /dev/net/tun; OpenSandbox re-checks the devices at create time.
  macos    Needs Apple hardware and a macOS virtualization provider; no such provider exists here yet.
  gpu      OpenSandbox resourceLimits.gpu: Docker DeviceRequests (nvidia-container-toolkit) or
           nvidia.com/gpu on Kubernetes. Operators enable it only on GPU hosts. Linux computers only.
"""

from fastapi import APIRouter, HTTPException

from .config import settings

router = APIRouter(prefix="/v1")

LINUX_CAPABILITIES = {
    "viewer": True,
    "terminal": True,
    "audio": True,
    "screens": True,
    "apps": True,
    "secrets": True,
    "agent": True,
    "computer_api": True,
    "files": True,
    "templates": True,
}
WINDOWS_CAPABILITIES = {
    # The web console relays the guest display; guest tooling for input, files and Cubicle's agent is Linux-only.
    "viewer": True,
    "terminal": False,
    "audio": False,
    "screens": False,
    "apps": False,
    "secrets": False,
    "agent": False,
    "computer_api": False,
    "files": False,
    "templates": False,
}
WINDOWS_MINIMUM = {"cpu": 2, "memory_gib": 4, "storage_gib": 100}
WINDOWS_CONSOLE_PORT = 8006


def catalog():
    s = settings()
    windows_reason = None if s.windows_enabled else "Needs a host with KVM; not enabled on this deployment"
    gpu_reason = None if s.gpu_enabled else "No GPU host is configured on this deployment"
    return {
        "operating_systems": [
            {"id": "linux", "name": "Linux (Debian, XFCE)", "available": True, "reason": None},
            {
                "id": "windows",
                "name": f"Windows {s.windows_version}",
                "available": s.windows_enabled,
                "reason": windows_reason,
                "minimum": WINDOWS_MINIMUM,
                "first_boot_minutes": 20,
            },
            {
                "id": "macos",
                "name": "macOS",
                "available": False,
                "reason": "Needs Apple hardware and a macOS virtualization provider, which Cubicle does not have yet",
            },
        ],
        "gpu": {
            "available": s.gpu_enabled,
            "max_per_computer": s.gpu_max_per_computer if s.gpu_enabled else 0,
            "reason": gpu_reason,
            "linux_only": True,
        },
        "capabilities": {"linux": LINUX_CAPABILITIES, "windows": WINDOWS_CAPABILITIES},
    }


def validate(os_name, gpu, cpu, memory_gib, storage_gib):
    """Reject configurations no provider can deliver. Called before anything is persisted."""
    s = settings()
    if os_name == "macos":
        raise HTTPException(409, "macOS computers are not available: no Apple-hardware provider is configured")
    if os_name == "windows":
        if not s.windows_enabled:
            raise HTTPException(409, "Windows computers are not enabled on this deployment (needs a KVM host)")
        if cpu < WINDOWS_MINIMUM["cpu"] or memory_gib < WINDOWS_MINIMUM["memory_gib"]:
            raise HTTPException(422, "Windows needs at least 2 CPU cores and 4 GiB of memory")
        if storage_gib < WINDOWS_MINIMUM["storage_gib"]:
            raise HTTPException(422, "Windows needs the 100 GiB storage tier (its disk is at least 64 GiB)")
        if gpu:
            raise HTTPException(422, "GPUs are available for Linux computers only")
    if gpu:
        if not s.gpu_enabled:
            raise HTTPException(409, "GPUs are not available on this deployment")
        if gpu > s.gpu_max_per_computer:
            raise HTTPException(422, f"At most {s.gpu_max_per_computer} GPU per computer")


def capabilities(os_name):
    return WINDOWS_CAPABILITIES if os_name == "windows" else LINUX_CAPABILITIES


def require(os_name, capability):
    if not capabilities(os_name).get(capability):
        raise HTTPException(409, f"This is not supported on {os_name.capitalize()} computers yet")


def require_for(db, cid, capability):
    """Look up a computer's OS and enforce one capability."""
    from .feature_models import DesktopProfile

    profile = db.get(DesktopProfile, cid)
    require(profile.os if profile else "linux", capability)


@router.get("/platform/capabilities")
def platform_capabilities():
    return catalog()
