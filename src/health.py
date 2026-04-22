import os
import platform
import subprocess
import time
from typing import Dict, Optional
from src.logger import get_logger

logger = get_logger(__name__)

class PiHealthMonitor:
    """Monitora métricas vitais de hardware (focado no Raspberry Pi 5).
    
    Implementa "fallback gracioso" em sistemas que não são Linux/Pi, retornando
    valores padrão para não bloquear o desenvolvimento local (ex: no macOS).
    """
    
    def __init__(self):
        self.is_linux = platform.system() == "Linux"
        
    def get_temperature(self) -> Optional[float]:
        """Obtém a temperatura da CPU em graus Celsius.
        
        Tenta ler do arquivo sysfs primeiro, com fallback para vcgencmd.
        """
        if not self.is_linux:
            return 45.0  # Fallback gracioso
            
        try:
            # Tenta via sysfs
            temp_path = "/sys/class/thermal/thermal_zone0/temp"
            if os.path.exists(temp_path):
                with open(temp_path, "r") as f:
                    return float(f.read().strip()) / 1000.0
        except Exception as e:
            logger.debug("Falha ao ler temperatura via sysfs", extra={"error": str(e)})
            
        try:
            # Tenta via vcgencmd
            result = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, check=True)
            # result.stdout format: "temp=45.0'C"
            temp_str = result.stdout.strip().replace("temp=", "").replace("'C", "")
            return float(temp_str)
        except Exception as e:
            logger.debug("Falha ao ler temperatura via vcgencmd", extra={"error": str(e)})
            
        return None

    def get_memory_usage(self) -> Optional[Dict[str, float]]:
        """Lê informações de memória do /proc/meminfo.
        
        Returns:
            Dict com 'total_mb' e 'available_mb'.
        """
        if not self.is_linux:
            return {"total_mb": 8192.0, "available_mb": 4096.0, "percent": 50.0}
            
        try:
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_str = parts[1].strip().split()[0]
                        meminfo[key] = int(val_str)
                        
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            
            if total_kb == 0:
                return None
                
            total_mb = total_kb / 1024.0
            avail_mb = avail_kb / 1024.0
            percent = ((total_kb - avail_kb) / total_kb) * 100.0
            
            return {
                "total_mb": round(total_mb, 2),
                "available_mb": round(avail_mb, 2),
                "percent": round(percent, 2)
            }
        except Exception as e:
            logger.debug("Falha ao ler memória", extra={"error": str(e)})
            return None

    def get_cpu_usage(self) -> Optional[float]:
        """Calcula o percentual de uso da CPU via /proc/stat.
        Requer ler o arquivo duas vezes com um intervalo curto.
        """
        if not self.is_linux:
            return 20.0
            
        def _read_stat() -> tuple[Optional[int], Optional[int]]:
            try:
                with open("/proc/stat", "r") as f:
                    line = f.readline()
                    parts = line.split()
                    if parts[0] == "cpu":
                        # idle is the 4th column + iowait 5th
                        user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice = map(int, parts[1:11])
                        total = user + nice + system + idle + iowait + irq + softirq + steal
                        return total, idle + iowait
            except Exception:
                pass
            return None, None

        total1, idle1 = _read_stat()
        if total1 is None or idle1 is None:
            return None
            
        time.sleep(0.1) # Aguarda 100ms para delta
        
        total2, idle2 = _read_stat()
        if total2 is None or idle2 is None:
            return None
            
        delta_total = total2 - total1
        delta_idle = idle2 - idle1
        
        if delta_total == 0:
            return 0.0
            
        pct = ((delta_total - delta_idle) / delta_total) * 100.0
        return round(pct, 2)
        
    def is_throttled(self) -> Optional[bool]:
        """Verifica se há thermal throttling ativo via vcgencmd."""
        if not self.is_linux:
            return False
            
        try:
            result = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, check=True)
            # result.stdout format: "throttled=0x0"
            val = result.stdout.strip().replace("throttled=", "")
            int_val = int(val, 16)
            
            # Bit 1 (0x2) indicates ARM frequency capped (thermal throttling)
            # Bit 2 (0x4) indicates currently throttled
            return bool(int_val & 0x6) 
        except Exception as e:
            logger.debug("Falha ao verificar throttling", extra={"error": str(e)})
            return None
