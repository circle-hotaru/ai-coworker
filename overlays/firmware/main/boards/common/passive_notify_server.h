#pragma once
#include <esp_http_server.h>
#include <esp_log.h>
#include <esp_netif.h>
#include <cJSON.h>
#include <lwip/inet.h>
#include <lwip/sockets.h>
#include <algorithm>
#include <cstring>
#include <mutex>
#include <string>
#include "application.h"
#include "settings.h"

// Idle-only notification channel. An independent LAN channel stays available when the voice WS
// closes.
class PassiveNotifyServer {
public:
    explicit PassiveNotifyServer(const char* device) : device_(device) {}
    void Start() {
        Settings persisted("push", false);
        id_ = persisted.GetString("id");
        if (!id_.empty())
            state_ = persisted.GetString("state", "done");
        ESP_ERROR_CHECK(esp_netif_init());
        httpd_config_t config = HTTPD_DEFAULT_CONFIG();
        config.server_port = 8021;
        config.ctrl_port = 32770;
        config.stack_size = 6144;
        if (httpd_start(&server_, &config) != ESP_OK)
            return;
        for (const char* path : {"/notify", "/notify/status"}) {
            httpd_uri_t uri{};
            uri.uri = path;
            uri.method = HTTP_POST;
            uri.handler = Handle;
            uri.user_ctx = this;
            ESP_ERROR_CHECK(httpd_register_uri_handler(server_, &uri));
        }
        ESP_LOGI("PassiveNotify", "Passive notification endpoint ready on 8021");
    }

private:
    const char* device_;
    httpd_handle_t server_ = nullptr;
    std::mutex mutex_;
    std::string id_, state_ = "idle";
    esp_err_t Reply(httpd_req_t* req) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto* json = cJSON_CreateObject();
        cJSON_AddStringToObject(json, "device", device_);
        cJSON_AddStringToObject(json, "id", id_.c_str());
        cJSON_AddStringToObject(json, "state", state_.c_str());
        char* result = cJSON_PrintUnformatted(json);
        httpd_resp_set_type(req, "application/json");
        auto err = httpd_resp_sendstr(req, result);
        cJSON_free(result);
        cJSON_Delete(json);
        return err;
    }
    static esp_err_t Handle(httpd_req_t* req) {
        auto* self = static_cast<PassiveNotifyServer*>(req->user_ctx);
        sockaddr_storage peer{};
        socklen_t size = sizeof(peer);
        char address[INET6_ADDRSTRLEN] = {};
        if (getpeername(httpd_req_to_sockfd(req), reinterpret_cast<sockaddr*>(&peer), &size) == 0) {
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
        Settings settings("websocket", false);
        auto ota = settings.GetString("url");
        auto scheme = ota.find("://");
        auto host = scheme == std::string::npos ? "" : ota.substr(scheme + 3);
        host = host.substr(0, host.find_first_of(":/"));
        if (source.empty() || host != source) {
            ESP_LOGW("PassiveNotify", "Push rejected source=%s expected=%s", source.c_str(),
                     host.c_str());
            return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Bridge host only");
        }
        if (strcmp(req->uri, "/notify/status") == 0)
            return self->Reply(req);
        if (req->content_len <= 0 || req->content_len > 8192)
            return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid size");
        std::string body(req->content_len, '\0');
        int received = 0;
        while (received < req->content_len) {
            int n = httpd_req_recv(req, body.data() + received, req->content_len - received);
            if (n <= 0)
                return ESP_FAIL;
            received += n;
        }
        auto* json = cJSON_ParseWithLength(body.data(), body.size());
        auto* id = cJSON_GetObjectItem(json, "id");
        auto* url = cJSON_GetObjectItem(json, "audio_url");
        auto* text = cJSON_GetObjectItem(json, "text");
        std::string prefix = "http://" + source + ":8003/xiaozhi/push/audio/";
        bool valid = cJSON_IsString(id) && strlen(id->valuestring) == 64 && cJSON_IsString(url) &&
                     std::string(url->valuestring).rfind(prefix, 0) == 0 && cJSON_IsString(text) &&
                     strlen(text->valuestring) <= 6000;
        if (valid) {
            std::string token(id->valuestring);
            valid = token.find_first_not_of("0123456789abcdef") == std::string::npos &&
                    std::string(url->valuestring) == prefix + token + ".ogg";
        }
        if (!valid) {
            cJSON_Delete(json);
            return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid notification");
        }
        std::string token(id->valuestring), audio(url->valuestring), caption(text->valuestring);
        cJSON_Delete(json);
        bool start = false;
        {
            std::lock_guard<std::mutex> lock(self->mutex_);
            if (token == self->id_ && self->state_ != "busy") {
                // Repeated POST after a lost response never restarts playback.
            } else if (self->state_ == "queued" || self->state_ == "playing") {
                httpd_resp_set_status(req, "409 Conflict");
            } else {
                self->id_ = token;
                self->state_ = "queued";
                start = true;
            }
        }
        if (start)
            Application::GetInstance().RequestNotification(
                audio, {{0, caption}}, [self, token](const std::string& state) {
                    std::lock_guard<std::mutex> lock(self->mutex_);
                    if (self->id_ == token)
                        self->state_ = state;
                    if (state == "done" || state == "interrupted" || state == "failed") {
                        Settings persisted("push", true);
                        persisted.SetString("id", token);
                        persisted.SetString("state", state);
                    }
                    ESP_LOGI("PassiveNotify", "Notification %s: %s", token.substr(0, 8).c_str(),
                             state.c_str());
                });
        return self->Reply(req);
    }
};
