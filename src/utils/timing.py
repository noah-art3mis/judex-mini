"""
Timing utilities for process extraction
"""

import functools
import logging
import time
from typing import Callable


def track_extraction_timing(func: Callable) -> Callable:
    """Decorator to track extraction function timing"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logging.debug(f"{func.__name__} extraction: {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logging.warning(f"{func.__name__} failed after {duration:.3f}s: {e}")
            raise

    return wrapper


class ProcessTimer:
    """Track timing for multiple processes"""

    def __init__(self):
        self.process_times: list[dict] = []
        self.total_start_time = time.time()

    def start_process(self, processo: str) -> float:
        """Start timing a process and return start time"""
        return time.time()

    def end_process(
        self, processo: str, start_time: float, success: bool = True
    ) -> None:
        """End timing a process and record the results"""
        end_time = time.time()
        duration = end_time - start_time

        process_info = {
            "processo": processo,
            "duration": round(duration, 2),
            "success": success,
        }
        self.process_times.append(process_info)

        logging.info(f"{processo}: concluído em {duration:.1f}s")

    def log_summary(self) -> None:
        """Log comprehensive timing summary"""
        total_end_time = time.time()
        total_duration = total_end_time - self.total_start_time

        # Calculate statistics
        successful_processes = [p for p in self.process_times if p["success"]]

        if successful_processes:
            avg_duration = sum(p["duration"] for p in successful_processes) / len(
                successful_processes
            )
            min_duration = min(p["duration"] for p in successful_processes)
            max_duration = max(p["duration"] for p in successful_processes)
        else:
            avg_duration = min_duration = max_duration = 0

        if successful_processes:
            logging.info(f"Tempo médio por processo: {avg_duration:.2f}s")
            logging.info(f"Processo mais rápido: {min_duration:.2f}s")
            logging.info(f"Processo mais lento: {max_duration:.2f}s")

        logging.debug("Tempos dos processos:")
        for process in self.process_times:
            logging.debug(f"{process['processo']}: {process['duration']:.2f}s")

        logging.info(
            f"Tempo total: {int(total_duration // 3600)}h {int((total_duration % 3600) // 60)}m {int(total_duration % 60)}s"
        )

        logging.info(f"Total de processos: {len(self.process_times)}")
