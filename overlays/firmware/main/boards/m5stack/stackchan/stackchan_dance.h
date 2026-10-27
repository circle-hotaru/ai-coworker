#pragma once
#include <driver/i2c_master.h>
#include <esp_http_server.h>
#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include "ftservo/SCSCL.h"

class StackChanDance {
public:
    explicit StackChanDance(i2c_master_bus_handle_t bus, std::function<void(bool)> changed);
    bool Start();
    void Stop();
    bool Active() const { return active_; }
    std::string Status() const;

private:
    SCSCL servos_;
    std::mutex commands_;
    i2c_master_dev_handle_t power_ = nullptr;
    std::function<void(bool)> changed_;
    std::atomic<bool> ready_{false}, active_{false}, stop_{false}, fault_{false};
    std::atomic<int> step_{0};
    int yaw_home_ = 476, pitch_zero_ = 598;
    int minimum_[2] = {0, 0}, maximum_[2] = {1023, 1023};
    httpd_handle_t http_ = nullptr;
    bool PowerBit(uint8_t reg, bool enabled);
    bool Prepare();
    bool Feedback();
    bool Move(int yaw_degrees, int pitch_degrees, int ms);
    void Release();
    void Run();
    bool Wait(int ms);
    static esp_err_t Http(httpd_req_t* req);
};
