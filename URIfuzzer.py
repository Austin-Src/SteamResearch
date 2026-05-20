import subprocess
import random
import string
import time
import os
import sys

# Target executable path (Update if Steam is installed on a different drive)
TARGET_EXE = r"C:\Program Files (x86)\Steam\steam.exe"

class UriFuzzerHarness:
    def __init__(self):
        self.iteration = 0
        self.start_time = time.time()
        self.commands = ["run", "joinlobby", "install", "connect", "friends"]
        
        # Classic mutation primitives (safely encoded for URI parsing boundaries)
        self.payloads = [
            "A" * 5000,                        # Potential Buffer Overflow / Stack exhaustion
            "%x" * 50,                         # Format String testing
            "../" * 10 + "win.ini",            # Directory Traversal
            "240 --multiprocess --no-sandbox",   # Command / Flag injection
            "%00",                             # Percent-encoded null byte (safely bypasses Python)
            "-1",                              # Integer signedness / Underflow testing
            "0x7fffffff",                      # Integer overflow testing
            "%" * 100,                         # Broken percent-encoding parser test
        ]

    def generate_payload(self) -> str:
        self.iteration += 1
        cmd = random.choice(self.commands)
        
        # Alternately choose a structural boundary mutation or randomized junk
        if self.iteration % 2 == 0:
            payload = random.choice(self.payloads)
        else:
            # Generate random alphanumeric data along with URI/path delimiters
            charset = string.ascii_letters + string.digits + "%/\?=&-+"
            payload = ''.join(random.choices(charset, k=random.randint(5, 1500)))
            
        return f"steam://{cmd}/{payload}"

    def update_status(self, last_action="Testing"):
        """Prints a real-time, single-line status indicator."""
        elapsed_time = time.time() - self.start_time
        # Prevent division by zero right at start
        speed = self.iteration / elapsed_time if elapsed_time > 0 else 0
        
        status_line = f"\r[*] Iteration: {self.iteration} | Speed: {speed:.2f} exec/s | Elapsed: {elapsed_time:.1f}s | Status: {last_action}"
        sys.stdout.write(status_line)
        sys.stdout.flush()

    def log_crash(self, payload, exit_code):
        filename = f"crash_{int(time.time())}_iter_{self.iteration}.txt"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"--- CRASH REPORT ---\n")
                f.write(f"Iteration: {self.iteration}\n")
                f.write(f"Exit Code: {hex(exit_code)}\n")
                f.write(f"Payload:\n{payload}\n")
            print(f"\n\n[!!!] CRASH DETECTED (Exit Code: {hex(exit_code)}). Saved to {filename}")
        except Exception as e:
            print(f"\n\n[!] Failed to write crash log file: {e}")
            print(f"Crashing payload was: {payload}")

    def run(self):
        print("[+] Fuzzer active. Monitoring for abnormal exit codes...")
        print("[!] Note: Ensure Steam is completely closed before starting.")
        print("[*] Press Ctrl+C to halt execution.\n")
        
        while True:
            current_payload = self.generate_payload()
            self.update_status("Spawning Process")
            
            try:
                # Launch the target process with the mutated URI argument
                proc = subprocess.Popen(
                    [TARGET_EXE, current_payload], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
                
                # Settle window: gives the binary time to parse the arguments and fault
                time.sleep(0.4)
                
                # Check if the process terminated abnormally
                self.update_status("Checking Exit Code")
                exit_code = proc.poll()
                
                if exit_code is not None:
                    # Windows codes are 32-bit unsigned. Convert negative returns
                    unsigned_exit = exit_code & 0xFFFFFFFF
                    
                    # 0xC000XXXX series usually marks Access Violations/Heap Corruptions
                    if unsigned_exit >= 0xC0000000: 
                        self.update_status("CRASH FOUND!")
                        self.log_crash(current_payload, unsigned_exit)
                        break  # Halt to let you inspect the crash and reproduce it
                else:
                    # Application is still running fine. Terminate cleanly to reset the state
                    self.update_status("Killing Target")
                    proc.terminate()
                    proc.wait()
                    
            except KeyboardInterrupt:
                print(f"\n\n[-] Fuzzing paused by user at iteration {self.iteration}.")
                break
            except ValueError as ve:
                # Safety catch-all for any unexpected character issues in subprocess wrappers
                continue
            except Exception as e:
                print(f"\n\n[!] Error spawning process at iteration {self.iteration}: {e}")
                break

if __name__ == "__main__":
    # Self-verify target location
    if not os.path.exists(TARGET_EXE):
        print(f"[!] Target binary not found at path: {TARGET_EXE}")
        print("[!] Please edit the TARGET_EXE path variable in the script.")
    else:
        fuzzer = UriFuzzerHarness()
        fuzzer.run()