"""Small facts about this computer."""
import platform
import subprocess


def ram_gb() -> float:
    try:
        if platform.system() == "Darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / 2**30
        if platform.system() == "Linux":
            return int(open("/proc/meminfo").readline().split()[1]) / 2**20
        out = subprocess.check_output(["wmic", "computersystem", "get", "TotalPhysicalMemory"], text=True)
        return int(out.split()[-1]) / 2**30
    except Exception:  # noqa: BLE001
        return 0.0


def swap_used_gb() -> float | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "vm.swapusage"], text=True)   # total = 7168.00M  used = 5944.12M  free = ...
            used = out.split("used =")[1].split()[0]
            return float(used[:-1]) / (1024 if used.endswith("M") else 1)
    except Exception:  # noqa: BLE001
        pass
    return None
