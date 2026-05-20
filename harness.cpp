#include <windows.h>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <chrono>
#include <thread>

// Configuration constants matching the automation layout
const char* MAPPING_NAME = "Global\\SteamClientService_SharedMemFile";
const size_t MAP_VIEW_SIZE = 4096;

bool ReadPayloadFile(const std::string& filepath, std::vector<char>& buffer) {
    std::ifstream file(filepath, std::ios::binary | std::ios::ate);
    if (!file.is_open()) return false;
    
    std::streamsize size = file.tellg();
    if (size <= 0) return false;
    
    buffer.resize(static_cast<size_t>(size));
    file.seekg(0, std::ios::beg);
    if (!file.read(buffer.data(), size)) return false;
    
    return true;
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "[-] Error: Missing communication payload path argument.\n";
        return 1;
    }
    
    std::string targetFile = argv[1];
    std::cout << "[+] Initializing Persistent Shared Memory Controller Interface...\n";
    
    // Establish a long-lived handle to the mapped target section
    HANDLE hMapFile = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, MAPPING_NAME);
    if (hMapFile == NULL) {
        std::cerr << "[-] Mapping View Acquisition Failed. Error: " << GetLastError() << "\n";
        return 1;
    }
    
    // Map the view into the local allocation space
    char* pBuf = (char*)MapViewOfFile(hMapFile, FILE_MAP_ALL_ACCESS, 0, 0, MAP_VIEW_SIZE);
    if (pBuf == NULL) {
        std::cerr << "[-] Map View Viewport Mapping Failed. Error: " << GetLastError() << "\n";
        CloseHandle(hMapFile);
        return 1;
    }
    
    std::cout << "[+] Inter-Process Control Pipeline Established. Beginning High-Speed Cycles.\n";
    
    std::vector<char> payloadBuffer;
    std::vector<char> previousBuffer;
    
    // Persistent execution loop matching the lifetime of the automation controller
    while (true) {
        if (ReadPayloadFile(targetFile, payloadBuffer)) {
            // Only force updates if the data has mutated to reduce memory bus thrashing
            if (payloadBuffer != previousBuffer) {
                size_t bytesToCopy = (payloadBuffer.size() < MAP_VIEW_SIZE) ? payloadBuffer.size() : MAP_VIEW_SIZE;
                
                // Atomically update the active allocation view layer
                std::memcpy(pBuf, payloadBuffer.data(), bytesToCopy);
                previousBuffer = payloadBuffer;
            }
        }
        
        // Micro-sleep adjustment prevents CPU starvation while maintaining execution rates
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    
    // Cleanup routines (unreachable in persistent execution state)
    UnmapViewOfFile(pBuf);
    CloseHandle(hMapFile);
    return 0;
}