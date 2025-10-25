"""
Timing utilities for process extraction
"""

import logging
import time
from typing import Dict, List


class ProcessTimer:
    """Track timing for multiple processes"""

    def __init__(self):
        self.process_times: List[Dict[str, any]] = []
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

        # Log summary
        logging.info(f"Total de processos: {len(self.process_times)}")
        logging.info(
            f"Tempo total: {int(total_duration // 3600)}h {int((total_duration % 3600) // 60)}m {int(total_duration % 60)}s"
        )

        if successful_processes:
            logging.info(f"Tempo médio por processo: {avg_duration:.2f}s")
            logging.info(f"Processo mais rápido: {min_duration:.2f}s")
            logging.info(f"Processo mais lento: {max_duration:.2f}s")

        logging.debug("Tempos dos processos:")
        for process in self.process_times:
            logging.debug(f"{process['processo']}: {process['duration']:.2f}s")
