import os
import sys
import time
import random
import subprocess
import ctypes
import re
import shutil

# --- NATIVE WINDOWS ANSI COLOR INITIALIZATION ---
def enable_windows_ansi():
    kernel32 = ctypes.windll.kernel32
    stdout_handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_ulong()
    if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)

# --- COLOR DEFINITIONS ---
CLR_RESET = "\033[0m"
CLR_PANEL = "\033[38;5;33m"   # Bright Blue
CLR_TEXT  = "\033[38;5;251m"  # Soft White
CLR_VAL   = "\033[38;5;220m"   # Gold
CLR_OK    = "\033[38;5;82m"    # Emerald Green
CLR_WARN  = "\033[38;5;202m"   # Orange
CLR_BAD   = "\033[38;5;196m"   # Crimson Red

# --- CONFIGURATION ---
HARNESS_EXE = "outOfProcessHarness.exe"
SEED_FILE = "in_dir/seed.dat"  
DICT_FILE = "steam.dict"
CRASH_DIR = "out_crashes" 
TMP_INPUT = os.path.join(os.environ.get("TEMP", "."), "cur_input_fuzz.dat")
SERVICE_NAME = '"Steam Client Service"'
SERVICE_BINARY = "steamservice.exe"

# --- RIGID PROTOCOL SPECIFICATION MATRIX ---
# Maps specific interface versions to their required fixed-width allocation layouts
INTERFACE_SPEC_MATRIX = [
    { "header": b"SteamClient012\x00", "total_len": 256 },
    { "header": b"SteamClient017\x00", "total_len": 256 },
    { "header": b"SteamClientService001\x00", "total_len": 512 },
    { "header": b"SteamClientService_SharedMemFile\x00", "total_len": 1024 }
]

class HighSpeedStructuralFuzzer:
    def __init__(self):
        self.total_execs = 0
        self.start_time = time.time()
        self.last_speed_check = time.time()
        self.execs_since_last_check = 0
        self.current_speed = 0.0
        
        self.mutation_density_pct = 0.0
        self.total_restarts = 0
        self.total_hangs = 0
        self.total_crashes_saved = 0
        
        self.target_pid = "INIT"
        self.target_memory = "0 MB"
        self.last_event_time = time.strftime("%H:%M:%S")
        self.last_event_type = "Initialization"
        self.harness_proc = None

        enable_windows_ansi()
        self.tokens = self.load_dictionary()

        if not os.path.exists("in_dir"):
            os.makedirs("in_dir")
        if not os.path.exists(CRASH_DIR):
            os.makedirs(CRASH_DIR)
            
        if not os.path.exists(SEED_FILE):
            with open(SEED_FILE, "wb") as f:
                # Seed contains mutable parameter fields
                f.write(b"\x01\x00\x00\x00\x00\x00\x00\x00PARAMETER_DATA_FIELD_RESERVE_PADDING")

        self.seed_data = bytearray(open(SEED_FILE, "rb").read())

    def load_dictionary(self):
        tokens = []
        if not os.path.exists(DICT_FILE):
            return [b"\xff\xff\xff\xff", b"\x00\x00\x00\x00"]
        with open(DICT_FILE, "r", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith('"') and line.endswith('"'):
                    line = line[1:-1]
                try:
                    raw_bytes = bytes(line, "utf-8").decode("unicode_escape").encode("latin-1")
                    tokens.append(raw_bytes)
                except Exception:
                    continue
        return tokens

    def check_admin_privileges(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def update_target_process_telemetry(self):
        try:
            out = subprocess.check_output(f'tasklist /FI "IMAGENAME eq {SERVICE_BINARY}" /NH', shell=True).decode()
            if SERVICE_BINARY in out.lower():
                parts = [p for p in re.split(r'\s+', out.strip()) if p]
                if len(parts) >= 5:
                    self.target_pid = parts[1]
                    mem_k = parts[4].replace(',', '').replace('.', '')
                    if mem_k.isdigit():
                        self.target_memory = f"{int(mem_k) // 1024} MB"
                    return
            self.target_pid = "OFFLINE"
            self.target_memory = "0 MB"
        except Exception:
            pass

    def verify_target_alive(self):
        try:
            out = subprocess.check_output(f"sc query {SERVICE_NAME}", shell=True).decode()
            return "RUNNING" in out
        except Exception:
            return False

    def start_persistent_harness(self):
        """Spawns the continuous C++ channel manager in the background."""
        if self.harness_proc:
            try:
                self.harness_proc.terminate()
            except Exception:
                pass
        
        self.harness_proc = subprocess.Popen(
            [HARNESS_EXE, TMP_INPUT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    def handle_crash_recovery(self):
        self.total_crashes_saved += 1
        self.last_event_time = time.strftime("%H:%M:%S")
        self.last_event_type = f"CRASH #{self.total_crashes_saved} ENCOUNTERED"
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        crash_filename = f"crash_struct_exec_{self.total_execs}_{timestamp}.dat"
        dest_path = os.path.join(CRASH_DIR, crash_filename)
        
        try:
            if os.path.exists(TMP_INPUT):
                shutil.copy2(TMP_INPUT, dest_path)
        except Exception:
            pass

        self.total_restarts += 1
        try:
            if self.harness_proc:
                self.harness_proc.terminate()
                
            subprocess.run(f"taskkill /F /IM {SERVICE_BINARY}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            subprocess.run(f"net start {SERVICE_NAME}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.0)
        except Exception:
            pass
        
        self.start_persistent_harness()
        self.update_target_process_telemetry()

    def mutate_structural(self):
        """Mutates parameter sets while maintaining the absolute fixed-width protocol requirements."""
        spec = random.choice(INTERFACE_SPEC_MATRIX)
        header = bytearray(spec["header"])
        target_total_len = spec["total_len"]
        
        # Calculate exactly how much room remains for structural variables
        allowed_payload_len = target_total_len - len(header)
        
        # Pull payload tracking baseline
        payload = bytearray(self.seed_data)
        
        # Core structural resizing layout constraints
        if len(payload) < allowed_payload_len:
            payload.extend(b"\x00" * (allowed_payload_len - len(payload)))
        else:
            payload = payload[:allowed_payload_len]
            
        # --- VALUE SPECIFIC ALTERATION MATRIX ---
        num_mutations = random.randint(1, 3)
        mutated_indices = set()
        
        for _ in range(num_mutations):
            idx = random.randint(0, len(payload) - 1)
            mutated_indices.add(idx)
            strategy = random.choice(["havoc", "token"])
            
            if strategy == "havoc" or not self.tokens:
                payload[idx] = random.randint(0, 255)
            elif strategy == "token":
                token = random.choice(self.tokens)
                t_len = len(token)
                if idx + t_len <= len(payload):
                    payload[idx:idx+t_len] = token

        self.mutation_density_pct = (len(mutated_indices) / len(payload)) * 100.0
        
        # Reconstruct the finalized packet
        final_packet = header + payload
        
        # Enforce structural layout size match
        if len(final_packet) < target_total_len:
            final_packet.extend(b"\x00" * (target_total_len - len(final_packet)))
        elif len(final_packet) > target_total_len:
            final_packet = final_packet[:target_total_len]

        with open(TMP_INPUT, "wb") as f:
            f.write(final_packet)

    def print_dashboard(self):
        elapsed = time.time() - self.start_time
        now = time.time()
        
        if now - self.last_speed_check >= 1.0:
            self.current_speed = self.execs_since_last_check / (now - self.last_speed_check)
            self.last_speed_check = now
            self.execs_since_last_check = 0

        status_string = f"{CLR_OK}ACTIVE (HIGH-SPEED){CLR_RESET}" if self.target_pid != "OFFLINE" else f"{CLR_BAD}RECOVERING...{CLR_RESET}"

        sys.stdout.write("\033[H\033[J") 
        fmt_row = lambda label, val, unit="": f"{CLR_PANEL}│ {CLR_TEXT}{label:<18}: {CLR_VAL}{val:<14} {CLR_TEXT}{unit:<16}{CLR_PANEL}│\n"
        
        out =  f"{CLR_PANEL}┌──────────────────────────────────────────────────────┐{CLR_RESET}\n"
        out += f"{CLR_PANEL}│ {CLR_VAL}CONTINUOUS PERSISTENT STRUCTURAL ENGINE (v2.0)       {CLR_PANEL}│{CLR_RESET}\n"
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        out += fmt_row("Run Time", f"{int(elapsed//3600)}h {int((elapsed%3600)//60)}m {int(elapsed%60)}s")
        out += fmt_row("Total Execs", f"{self.total_execs}")
        out += fmt_row("Exec Speed", f"{self.current_speed:.2f}", "execs/sec")
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        out += f"{CLR_PANEL}│ {CLR_VAL}TARGET TELEMETRY PROFILE                             {CLR_PANEL}│{CLR_RESET}\n"
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        out += fmt_row("Target Process", SERVICE_BINARY)
        out += fmt_row("Active PID", self.target_pid)
        out += fmt_row("RAM Footprint", self.target_memory)
        out += f"{CLR_PANEL}│ {CLR_TEXT}{'Channel Status':<18}: {status_string}{' '*(31 - 20)}{CLR_PANEL}│{CLR_RESET}\n"
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        out += f"{CLR_PANEL}│ {CLR_VAL}METRICS & PERFORMANCE PROFILE                        {CLR_PANEL}│{CLR_RESET}\n"
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        out += fmt_row("Mutation Density", f"{self.mutation_density_pct:.1f}", "% entropy")
        out += fmt_row("Active Dictionary", f"{len(self.tokens)} loaded", "tokens")
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        out += f"{CLR_PANEL}│ {CLR_VAL}INCIDENT EXCEPTION LOGS                              {CLR_PANEL}│{CLR_RESET}\n"
        out += f"{CLR_PANEL}├──────────────────────────────────────────────────────┤{CLR_RESET}\n"
        
        crash_color = CLR_OK if self.total_crashes_saved == 0 else CLR_BAD
        out += f"{CLR_PANEL}│ {CLR_TEXT}{'CRASHES SAVED':<18}: {crash_color}{self.total_crashes_saved:<14}{CLR_TEXT}{'unique files  ':<16}{CLR_PANEL}│{CLR_RESET}\n"
        out += fmt_row("Auto Restarts", f"{self.total_restarts}")
        
        evt_str = f"{self.last_event_type} at {self.last_event_time}"
        out += f"{CLR_PANEL}│ {CLR_TEXT}{'Last Event':<18}: {CLR_VAL}{evt_str:<31} {CLR_PANEL} │{CLR_RESET}\n"
        out += f"{CLR_PANEL}└──────────────────────────────────────────────────────┘{CLR_RESET}\n"
        
        sys.stdout.write(out)
        sys.stdout.flush()

    def run_campaign(self):
        if not self.check_admin_privileges():
            print(f"{CLR_BAD}[-] Critical Error: Administrative privileges required.{CLR_RESET}")
            return
        if not self.verify_target_alive():
            print(f"{CLR_BAD}[-] Error: Target service {SERVICE_NAME} is completely offline.{CLR_RESET}")
            return
            
        self.update_target_process_telemetry()
        
        # Unify initial mutation payload state and kick off long-lived harness
        self.mutate_structural()
        self.start_persistent_harness()

        # High-velocity cycle engine loop
        while True:
            self.mutate_structural()
            
            self.total_execs += 1
            self.execs_since_last_check += 1

            # Micro-sleep throttles file I/O to avoid contention errors
            time.sleep(0.001)

            if self.total_execs % 200 == 0:
                self.print_dashboard()
                
            if self.total_execs % 1000 == 0:
                self.update_target_process_telemetry()
                # Verify background worker continuity
                if self.harness_proc.poll() is not None:
                    self.last_event_type = "Harness Restart"
                    self.start_persistent_harness()
                if not self.verify_target_alive():
                    self.handle_crash_recovery()

if __name__ == "__main__":
    fuzzer = HighSpeedStructuralFuzzer()
    fuzzer.run_campaign()