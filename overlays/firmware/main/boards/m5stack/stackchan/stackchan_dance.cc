#include "stackchan_dance.h"
#include <lwip/inet.h>
#include <lwip/sockets.h>
#include <algorithm>
#include <cstring>
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "settings.h"

namespace {
constexpr char kTag[] = "StackChanDance";
constexpr int kPitchRest = 20;
// A bounded six-second sequence. Units here are degrees, not raw servo ticks.
struct Step {
    int yaw, pitch, duration;
};
constexpr Step kDance[] = {{0, 22, 600},   {-12, 30, 600}, {12, 22, 600},
                           {-12, 34, 600}, {12, 22, 600},  {0, 34, 600},
                           {-10, 26, 600}, {10, 26, 600},  {0, 22, 600}};
}  // namespace

StackChanDance::StackChanDance(i2c_master_bus_handle_t bus, std::function<void(bool)> changed)
    : changed_(std::move(changed)) {
    Settings calibration("servo", false);
    // Calibration belongs to the physical device. Missing values disable motion.
    yaw_home_ = calibration.GetInt("zero_pos_1", -1);
    pitch_zero_ = calibration.GetInt("zero_pos_2", -1);
    if (yaw_home_ < 100 || yaw_home_ > 900 || pitch_zero_ < 0 || pitch_zero_ > 850) {
        fault_ = true;
        ESP_LOGE(kTag, "Invalid calibration; motion disabled");
        return;
    }
    i2c_device_config_t config{};
    config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    config.device_address = 0x6f;
    config.scl_speed_hz = 100000;
    if (i2c_master_bus_add_device(bus, &config, &power_) != ESP_OK ||
        !servos_.begin(UART_NUM_1, 1000000, 6, 7)) {
        fault_ = true;
        ESP_LOGE(kTag, "Base I/O or UART unavailable");
        return;
    }
    // Board construction precedes Wi-Fi startup. Initialize lwIP before opening sockets;
    // esp_netif_init is idempotent, so the later Wi-Fi manager can initialize as usual.
    ESP_ERROR_CHECK(esp_netif_init());
    httpd_config_t http = HTTPD_DEFAULT_CONFIG();
    http.server_port = 8020;
    http.ctrl_port = 32769;
    http.stack_size = 6144;
    http.max_uri_handlers = 3;
    if (httpd_start(&http_, &http) == ESP_OK) {
        for (const char* path : {"/dance/start", "/dance/stop", "/dance/status"}) {
            httpd_uri_t uri{};
            uri.uri = path;
            uri.method = HTTP_POST;
            uri.handler = Http;
            uri.user_ctx = this;
            ESP_ERROR_CHECK(httpd_register_uri_handler(http_, &uri));
        }
    }
    xTaskCreate([](void* arg) { static_cast<StackChanDance*>(arg)->Run(); }, "stackchan_dance",
                6144, this, 3, nullptr);
}

bool StackChanDance::PowerBit(uint8_t reg, bool enabled) {
    if (!power_)
        return false;
    uint8_t value;
    if (i2c_master_transmit_receive(power_, &reg, 1, &value, 1, 100) != ESP_OK)
        return false;
    uint8_t data[] = {reg, static_cast<uint8_t>(enabled ? value | 1 : value & ~1)};
    return i2c_master_transmit(power_, data, 2, 100) == ESP_OK;
}

bool StackChanDance::Prepare() {
    // PY32 pin 0 controls VM: output, pull-up, no pull-down, high.
    if (!PowerBit(0x03, true) || !PowerBit(0x0b, false) || !PowerBit(0x09, true) ||
        !PowerBit(0x05, true))
        return false;
    vTaskDelay(pdMS_TO_TICKS(1000));
    for (uint8_t reg : {0x02, 0x03, 0x05, 0x07, 0x09, 0x0b, 0x13}) {
        uint8_t value = 0;
        if (i2c_master_transmit_receive(power_, &reg, 1, &value, 1, 100) == ESP_OK)
            ESP_LOGI(kTag, "Base register %02x=%02x", reg, value);
    }
    // Diagnose the physical link with read-only pings before changing any servo mode.
    servos_.IOTimeOut = 50;
    bool connected = false;
    for (int baud : {1000000, 500000, 250000, 115200}) {
        uart_set_baudrate(UART_NUM_1, baud);
        int yaw = servos_.Ping(1), yaw_error = servos_.getLastError();
        int pitch = servos_.Ping(2), pitch_error = servos_.getLastError();
        ESP_LOGI(kTag, "Servo ping baud=%d yaw=%d err=%d pitch=%d err=%d", baud, yaw, yaw_error,
                 pitch, pitch_error);
        if (yaw == 1 && pitch == 2) {
            connected = true;
            break;
        }
    }
    if (!connected)
        return false;
    for (int id : {1, 2}) {
        int minimum = servos_.readWord(id, SCSCL_MIN_ANGLE_LIMIT_L);
        int maximum = servos_.readWord(id, SCSCL_MAX_ANGLE_LIMIT_L);
        // The base MCU may acknowledge VM before the servo controllers have booted.
        // Only retry reads; no torque or movement is enabled during this wait.
        for (int attempt = 0; attempt < 15 && (minimum < 0 || maximum < 0); ++attempt) {
            vTaskDelay(pdMS_TO_TICKS(100));
            minimum = servos_.readWord(id, SCSCL_MIN_ANGLE_LIMIT_L);
            maximum = servos_.readWord(id, SCSCL_MAX_ANGLE_LIMIT_L);
        }
        ESP_LOGI(kTag, "Servo id=%d angle limits raw=%d/%d", id, minimum, maximum);
        if (minimum < 0 || maximum < 0 || servos_.EnableTorque(id, 0) != 1)
            return false;
        if (minimum < 0 || maximum <= minimum || maximum > 1023)
            return false;
        minimum_[id - 1] = minimum;
        maximum_[id - 1] = maximum;
    }
    return Feedback();
}

bool StackChanDance::Feedback() {
    for (int id : {1, 2}) {
        int pos = servos_.ReadPos(id), temperature = servos_.ReadTemper(id);
        if (pos < 0 || pos > 1023 || temperature < 0 || temperature >= 65) {
            ESP_LOGE(kTag, "Invalid servo feedback id=%d pos=%d temperature=%d", id, pos,
                     temperature);
            return false;
        }
    }
    return true;
}

bool StackChanDance::Move(int yaw, int pitch, int ms) {
    if (yaw < -15 || yaw > 15 || pitch < 15 || pitch > 40 || ms < 400)
        return false;
    const int a = yaw_home_ + yaw * 16 / 5;
    const int b = pitch_zero_ + pitch * 16 / 5;
    if (a < minimum_[0] || a > maximum_[0] || b < minimum_[1] || b > maximum_[1])
        return false;
    return servos_.WritePos(1, a, ms, 0) == 1 && servos_.WritePos(2, b, ms, 0) == 1;
}

void StackChanDance::Release() {
    servos_.EnableTorque(1, 0);
    servos_.EnableTorque(2, 0);
}

bool StackChanDance::Start() {
    std::lock_guard<std::mutex> lock(commands_);
    if (!ready_ || fault_ || active_)
        return false;
    stop_ = false;
    active_ = true;
    return true;
}

void StackChanDance::Stop() {
    std::lock_guard<std::mutex> lock(commands_);
    stop_ = true;
}

std::string StackChanDance::Status() const {
    return std::string(
               "{\"device\":\"Operator\",\"preset\":\"hello\",\"duration_ms\":6100,\"ready\":") +
           (ready_ ? "true" : "false") + ",\"state\":\"" +
           (fault_    ? "fault"
            : active_ ? (stop_ ? "returning" : "dancing")
                      : "idle") +
           "\",\"step\":" + std::to_string(step_.load()) + "}";
}

bool StackChanDance::Wait(int ms) {
    for (int elapsed = 0; elapsed < ms; elapsed += 20) {
        if (stop_)
            return false;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    return !stop_;
}

void StackChanDance::Run() {
    ready_ = Prepare();
    fault_ = !ready_;
    if (!ready_) {
        Release();
        PowerBit(0x05, false);
    }
    ESP_LOGI(kTag, "Motion ready=%d, factory home raw=%d/%d; idle without motion", ready_.load(),
             yaw_home_, pitch_zero_);
    while (true) {
        if (!active_) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        ESP_LOGI(kTag, "Preset hello starting");
        changed_(true);
        bool ok = Feedback() && servos_.EnableTorque(1, 1) == 1 && servos_.EnableTorque(2, 1) == 1;
        step_ = 0;
        for (const auto& point : kDance) {
            if (!ok || stop_)
                break;
            ++step_;
            ok = Feedback() && Move(point.yaw, point.pitch, point.duration);
            if (ok && !Wait(point.duration))
                break;
        }
        if (ok) {
            // Stop cancels the remaining choreography, then gently returns to rest.
            ok = Move(0, kPitchRest, 700);
            vTaskDelay(pdMS_TO_TICKS(700));
            int yaw = servos_.ReadPos(1), pitch = servos_.ReadPos(2);
            ok = ok && std::abs(yaw - yaw_home_) < 30 &&
                 std::abs(pitch - (pitch_zero_ + kPitchRest * 16 / 5)) < 30;
        }
        Release();
        if (!ok) {
            fault_ = true;
            ready_ = false;
            PowerBit(0x05, false);
        }
        step_ = 0;
        active_ = false;
        changed_(false);
        ESP_LOGI(kTag, "Preset ended: %s", ok ? "returned_to_rest" : "fault_power_off");
    }
}

esp_err_t StackChanDance::Http(httpd_req_t* req) {
    // Only the Mac hosting the configured OTA bridge may control this LAN endpoint.
    Settings settings("wifi", false);
    std::string url = settings.GetString("ota_url");
    const auto scheme = url.find("://");
    std::string host = scheme == std::string::npos ? "" : url.substr(scheme + 3);
    host = host.substr(0, host.find_first_of(":/"));
    sockaddr_storage peer{};
    socklen_t size = sizeof(peer);
    const int fd = httpd_req_to_sockfd(req);
    char address[INET6_ADDRSTRLEN] = {};
    if (getpeername(fd, reinterpret_cast<sockaddr*>(&peer), &size) == 0) {
        if (peer.ss_family == AF_INET)
            inet_ntop(AF_INET, &reinterpret_cast<sockaddr_in*>(&peer)->sin_addr, address,
                      sizeof(address));
        else if (peer.ss_family == AF_INET6)
            inet_ntop(AF_INET6, &reinterpret_cast<sockaddr_in6*>(&peer)->sin6_addr, address,
                      sizeof(address));
    }
    std::string source(address);
    if (source.rfind("::ffff:", 0) == 0 || source.rfind("::FFFF:", 0) == 0)
        source.erase(0, 7);
    if (host != source) {
        ESP_LOGW(kTag, "Control rejected source=%s expected=%s", source.c_str(), host.c_str());
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Bridge host only");
        return ESP_OK;
    }
    auto* self = static_cast<StackChanDance*>(req->user_ctx);
    if (strcmp(req->uri, "/dance/start") == 0 && !self->Start()) {
        httpd_resp_set_status(req, "409 Conflict");
    } else if (strcmp(req->uri, "/dance/stop") == 0)
        self->Stop();
    httpd_resp_set_type(req, "application/json");
    std::string result = self->Status();
    return httpd_resp_send(req, result.c_str(), result.size());
}
