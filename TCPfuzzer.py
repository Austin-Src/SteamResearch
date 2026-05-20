import socket
import time
import struct
import random
import sys

# Target configuration bound strictly to local loopback interfaces
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 27036

class ContinuousMutationEngine:
    def __init__(self):
        self.iteration = 0
        self.successful_sends = 0
        self.connection_failures = 0
        
        # Seed values for structural variance
        self.boundary_integers = [
            b"\x00\x00\x00\x00",
            b"\xff\xff\xff\xff",
            b"\xff\xff\xff\x7f",
            b"\x00\x00\x00\x80",
            b"\x09\x00\x00\x00",  # Triggers the 9-byte tracking sequence
            b"\x08\x01\x00\x00"   # Triggers the 264-byte structural block
        ]
        
        self.corruption_templates = [
            b"%s%x%d%n" * 4,
            b"A" * 256,
            b"A\x00" * 32,
            b"../" * 8,
            b"\\\\.\\pipe\\",
            b";;;;;;;;",
            b"\xff" * 64
        ]

    def generate_mutated_payload(self) -> bytes:
        """Dynamically constructs mutated frames alternating across different structural layouts."""
        self.iteration += 1
        mode = self.iteration % 4
        
        # Base Magic Header (Can be customized if a specific static prefix is isolated)
        header_magic = b"\x00\x00\x00\x00"
        
        if mode == 0:
            # Layout A: Mutate perceived length field with boundary values
            length_field = random.choice(self.boundary_integers)
            body_field = b"RemoteClientAPData"
            return header_magic + length_field + body_field
            
        elif mode == 1:
            # Layout B: Keep length field standard, corrupt payload content
            length_field = struct.pack("<I", 128)
            body_field = random.choice(self.corruption_templates)
            return header_magic + length_field + body_field
            
        elif mode == 2:
            # Layout C: High-frequency random byte flipping on a structural spine
            spine = bytearray(b"\x00" * 12 + b"ClientUpdateValidationPackageBlock" + b"\xff" * 4)
            # Flip between 1 and 4 arbitrary bytes inside the payload
            for _ in range(random.randint(1, 4)):
                pos = random.randint(0, len(spine) - 1)
                spine[pos] = random.randint(0, 255)
            return bytes(spine)
            
        else:
            # Layout D: Variable frame sizing simulating the 9 to 264 byte spectrum
            target_size = random.choice([9, 24, 31, 128, 264])
            if target_size <= len(header_magic):
                return header_magic[:target_size]
            return header_magic + bytes(random.getrandbits(8) for _ in range(target_size - len(header_magic)))

    def run_fuzz_loop(self):
        print(f"[+] Launching Continuous Mutation Engine targeting {TARGET_HOST}:{TARGET_PORT}")
        print("[~] Monitoring system feedback... Press Ctrl+C to safely terminate execution.\n")
        
        while True:
            payload = self.generate_mutated_payload()
            
            try:
                # Initialize non-blocking socket with short timeouts to maximize throughput
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2) 
                
                s.connect((TARGET_HOST, TARGET_PORT))
                s.sendall(payload)
                
                # Check if target process returns data or triggers downstream file writes
                _ = s.recv(64)
                s.close()
                self.successful_sends += 1
                
                # Tiny cooling window to allow the OS to reclaim socket descriptors
                time.sleep(0.002)
                
            except (socket.timeout, ConnectionResetError, ConnectionAbortedError):
                # Expected behavior when mutations drop or reset the service port connection
                try:
                    s.close()
                except:
                    pass
                self.successful_sends += 1  # Still counted as a delivered variant
                time.sleep(0.002)
                
            except ConnectionRefusedError:
                # The target process or port has stopped listening entirely
                self.connection_failures += 1
                print(f"\n[!] Connection Refused at iteration {self.iteration}. Target may have shut down.")
                print("[~] Pausing for 2 seconds to check if WinDbg has intercepted a fault state...")
                time.sleep(2.0)
                
                if self.connection_failures > 5:
                    print("[-] Persistent connection failure. Terminating script execution loop.")
                    sys.exit(0)
                    
            except KeyboardInterrupt:
                print("\n[+] Testing loop stopped manually by user intervention.")
                self.print_metrics()
                sys.exit(0)
                
            if self.iteration % 250 == 0:
                self.print_metrics()

    def print_metrics(self):
        print(f"[Iter: {self.iteration}] Sent: {self.successful_sends} variants | Port Dropped States: {self.connection_failures}", end='\r')

if __name__ == "__main__":
    engine = ContinuousMutationEngine()
    engine.run_fuzz_loop()