#pragma once

#include "assets/lang_config.h"
#include "display/lvgl_display/lvgl_theme.h"
#include "material_symbols.h"
#include "operator_pixel_font.h"

#include <algorithm>
#include <cstring>

// Round-screen presentation owned by this board. Audio, pins and transport stay
// in their existing drivers; all LVGL mutations use the display lock.
class CustomLcdDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;

    static void RoundInvalidation(lv_event_t* event) {
        auto* area = static_cast<lv_area_t*>(lv_event_get_param(event));
        area->x1 &= ~1;
        area->y1 &= ~1;
        area->x2 |= 1;
        area->y2 |= 1;
    }

    void SetupUI() override {
        if (setup_ui_called_)
            return;
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);
        if (!lock)
            return;
        lv_display_add_event_cb(display_, RoundInvalidation, LV_EVENT_INVALIDATE_AREA, nullptr);
        CreateChrome();
        ApplyLayout();
        UpdatePhase();
    }

    void SetTheme(Theme* theme) override {
        SpiLcdDisplay::SetTheme(theme);
        DisplayLockGuard lock(this);
        if (lock && chrome_)
            ApplyLayout();
    }

    void SetStatus(const char* status) override {
        SpiLcdDisplay::SetStatus(status);
        DisplayLockGuard lock(this);
        if (!lock || !chrome_)
            return;
        thinking_ = false;
        alert_level_ = status && std::strcmp(status, Lang::Strings::ERROR) == 0     ? 2
                       : status && std::strcmp(status, Lang::Strings::WARNING) == 0 ? 1
                                                                                    : 0;
        UpdatePhase();
    }

    void UpdateStatusBar(bool update_all = false) override {
        SpiLcdDisplay::UpdateStatusBar(update_all);
        int level = 0;
        bool charging = false, discharging = false;
        const bool has_power = Board::GetInstance().GetBatteryLevel(level, charging, discharging);
        const int volume = Board::GetInstance().GetAudioCodec()->output_volume();
        DisplayLockGuard lock(this);
        if (!lock || !chrome_)
            return;
        if (has_power && discharging) {
            lv_label_set_text_fmt(power_text_, "BATTERY %d%%", std::clamp(level, 0, 100));
        } else {
            lv_label_set_text(power_text_, charging ? "CHARGING" : "USB POWER");
        }
        lv_label_set_text(speaker_icon_,
                          volume == 0 ? MATERIAL_SYMBOLS_VOLUME_OFF : MATERIAL_SYMBOLS_VOLUME_UP);
        // The stock idle clock uses the status label. Restore the round UI's
        // live phase after that update, including while a notification is shown.
        UpdatePhase();
    }

    void SetChatMessage(const char* role, const char* text) override {
        SpiLcdDisplay::SetChatMessage(role, text);
        DisplayLockGuard lock(this);
        if (!lock || !chrome_)
            return;
        if (role && std::strcmp(role, "user") == 0 && text && text[0])
            thinking_ = true;
        if (role && std::strcmp(role, "assistant") == 0)
            thinking_ = false;
        UpdatePhase();
    }

    void ClearChatMessages() override {
        SpiLcdDisplay::ClearChatMessages();
        DisplayLockGuard lock(this);
        if (!lock || !chrome_)
            return;
        thinking_ = false;
        UpdatePhase();
    }

private:
    lv_obj_t* chrome_ = nullptr;
    lv_obj_t* power_text_ = nullptr;
    lv_obj_t* speaker_button_ = nullptr;
    lv_obj_t* speaker_icon_ = nullptr;
    lv_obj_t* mic_button_ = nullptr;
    lv_obj_t* mic_icon_ = nullptr;
    lv_obj_t* hint_ = nullptr;
    lv_obj_t* dots_[4]{};
    bool thinking_ = false;
    int alert_level_ = 0;
    int restore_volume_ = 60;
    DeviceState last_state_ = kDeviceStateUnknown;

    static void CleanBox(lv_obj_t* box) {
        lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_style_pad_all(box, 0, 0);
        lv_obj_set_style_border_width(box, 0, 0);
        lv_obj_set_style_bg_opa(box, LV_OPA_TRANSP, 0);
        lv_obj_set_style_shadow_width(box, 0, 0);
    }

    lv_obj_t* MakeLabel(lv_obj_t* parent, const char* text, const lv_font_t* font, uint32_t color) {
        auto* label = lv_label_create(parent);
        lv_label_set_text(label, text);
        lv_obj_set_style_text_font(label, font, 0);
        lv_obj_set_style_text_color(label, lv_color_hex(color), 0);
        return label;
    }

    lv_obj_t* MakeButton(int x, int y, int size, const char* symbol, lv_obj_t** icon) {
        auto* button = lv_button_create(chrome_);
        CleanBox(button);
        lv_obj_set_pos(button, x, y);
        lv_obj_set_size(button, size, size);
        lv_obj_set_style_radius(button, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(button, lv_color_hex(0x211a32), 0);
        lv_obj_set_style_bg_opa(button, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(button, lv_color_hex(0x3b2c55), LV_STATE_PRESSED);
        auto* theme = static_cast<LvglTheme*>(current_theme_);
        *icon = MakeLabel(button, symbol, theme->icon_font()->font(), 0xa69ab9);
        lv_obj_center(*icon);
        return button;
    }

    void CreateChrome() {
        auto* screen = lv_screen_active();
        chrome_ = lv_obj_create(screen);
        CleanBox(chrome_);
        lv_obj_remove_flag(chrome_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_size(chrome_, width_, height_);
        lv_obj_center(chrome_);
        // Keep the aura behind the portrait while controls remain outside it.
        lv_obj_move_to_index(chrome_, 1);
        auto* rim = lv_obj_create(chrome_);
        CleanBox(rim);
        lv_obj_remove_flag(rim, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_size(rim, 450, 450);
        lv_obj_center(rim);
        lv_obj_set_style_radius(rim, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(rim, 1, 0);
        lv_obj_set_style_border_color(rim, lv_color_hex(0x1b1627), 0);

        // Sparse, deterministic pixel stars leave a clear silhouette around Operator.
        const int stars[][3] = {{114, 157, 3}, {103, 202, 4}, {119, 239, 2}, {126, 290, 3},
                                {342, 146, 2}, {357, 188, 3}, {346, 230, 4}, {337, 289, 2},
                                {163, 116, 2}, {305, 115, 3}, {141, 306, 2}, {322, 308, 2}};
        for (const auto& star : stars) {
            auto* pixel = lv_obj_create(chrome_);
            CleanBox(pixel);
            lv_obj_remove_flag(pixel, LV_OBJ_FLAG_CLICKABLE);
            lv_obj_set_pos(pixel, star[0], star[1]);
            lv_obj_set_size(pixel, star[2], star[2]);
            lv_obj_set_style_radius(pixel, 0, 0);
            lv_obj_set_style_bg_color(pixel, lv_color_hex(0x514264), 0);
            lv_obj_set_style_bg_opa(pixel, LV_OPA_COVER, 0);
        }

        power_text_ = MakeLabel(top_bar_, "USB POWER", &lv_font_montserrat_14, 0x8d829f);
        lv_obj_set_width(power_text_, 150);
        lv_obj_set_style_text_align(power_text_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_letter_space(power_text_, 1, 0);
        speaker_button_ = MakeButton(61, 97, 56, MATERIAL_SYMBOLS_VOLUME_UP, &speaker_icon_);
        mic_button_ = MakeButton(349, 97, 56, MATERIAL_SYMBOLS_MIC, &mic_icon_);
        hint_ = MakeLabel(chrome_, "PRESS BOOT TO TALK", &lv_font_montserrat_14, 0x81748f);
        lv_obj_set_style_text_letter_space(hint_, 1, 0);
        lv_obj_align(hint_, LV_ALIGN_BOTTOM_MID, 0, -82);
        for (int i = 0; i < 4; ++i) {
            dots_[i] = lv_obj_create(chrome_);
            CleanBox(dots_[i]);
            lv_obj_remove_flag(dots_[i], LV_OBJ_FLAG_CLICKABLE);
            lv_obj_set_size(dots_[i], 5, 5);
            lv_obj_set_style_radius(dots_[i], 1, 0);
            lv_obj_set_pos(dots_[i], 213 + i * 12, 434);
            lv_obj_set_style_bg_opa(dots_[i], LV_OPA_COVER, 0);
        }
        lv_obj_add_event_cb(
            speaker_button_,
            [](lv_event_t* event) {
                auto* self = static_cast<CustomLcdDisplay*>(lv_event_get_user_data(event));
                Application::GetInstance().Schedule([self]() {
                    auto* codec = Board::GetInstance().GetAudioCodec();
                    const int volume = codec->output_volume();
                    if (volume > 0)
                        self->restore_volume_ = volume;
                    codec->SetOutputVolume(volume > 0 ? 0 : self->restore_volume_);
                    self->UpdateStatusBar(true);
                });
            },
            LV_EVENT_CLICKED, this);
        lv_obj_add_event_cb(
            mic_button_,
            [](lv_event_t*) {
                Application::GetInstance().Schedule([]() {
                    auto& app = Application::GetInstance();
                    if (app.GetDeviceState() == kDeviceStateListening) {
                        // Submit buffered speech without closing the response channel.
                        app.StopListening();
                    } else {
                        app.ToggleChatState();
                    }
                });
            },
            LV_EVENT_CLICKED, nullptr);
    }

    void ApplyLayout() {
        auto* screen = lv_screen_active();
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        lv_obj_set_style_bg_color(container_, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(container_, LV_OPA_COVER, 0);
        // The original GIF pixels remain untouched; only display scaling changes.
        CleanBox(emoji_box_);
        lv_obj_set_size(emoji_box_, 208, 208);
        lv_obj_align(emoji_box_, LV_ALIGN_CENTER, 0, -16);
        lv_image_set_scale(emoji_image_, 384);
        lv_image_set_antialias(emoji_image_, false);
        lv_obj_center(emoji_image_);
        lv_obj_center(emoji_label_);

        CleanBox(top_bar_);
        lv_obj_set_style_layout(top_bar_, LV_LAYOUT_NONE, 0);
        lv_obj_set_size(top_bar_, 220, 30);
        lv_obj_align(top_bar_, LV_ALIGN_TOP_MID, 0, 29);
        lv_obj_set_parent(network_label_, top_bar_);
        lv_obj_set_parent(battery_label_, top_bar_);
        lv_obj_set_pos(network_label_, 0, 0);
        lv_obj_set_pos(battery_label_, 196, 0);
        lv_obj_set_pos(power_text_, 34, 3);
        lv_obj_set_style_text_color(network_label_, lv_color_hex(0x8d829f), 0);
        lv_obj_set_style_text_color(battery_label_, lv_color_hex(0x8d829f), 0);
        lv_obj_add_flag(mute_label_, LV_OBJ_FLAG_HIDDEN);
        auto* theme = static_cast<LvglTheme*>(current_theme_);
        const auto* icon_font = theme->icon_font()->font();
        for (auto* label : {network_label_, battery_label_, speaker_icon_, mic_icon_})
            lv_obj_set_style_text_font(label, icon_font, 0);

        CleanBox(status_bar_);
        lv_obj_set_size(status_bar_, 320, 42);
        lv_obj_align(status_bar_, LV_ALIGN_TOP_MID, 0, 60);
        lv_obj_set_size(status_label_, 300, 30);
        lv_obj_set_style_text_font(status_label_, &operator_ui::kPixelFont, 0);
        lv_obj_set_style_text_color(status_label_, lv_color_hex(0xc0adcF), 0);
        lv_obj_set_style_text_letter_space(status_label_, 4, 0);
        lv_label_set_long_mode(status_label_, LV_LABEL_LONG_MODE_CLIP);
        lv_obj_center(status_label_);
        lv_obj_set_width(notification_label_, 308);
        lv_obj_set_style_text_color(notification_label_, lv_color_hex(0xd8cee6), 0);
        lv_obj_center(notification_label_);

        const auto* font = lv_obj_get_style_text_font(chat_message_label_, LV_PART_MAIN);
        const int height = 2 * font->line_height;
        CleanBox(bottom_bar_);
        lv_obj_set_size(bottom_bar_, 332, height + 16);
        lv_obj_set_style_pad_all(bottom_bar_, 8, 0);
        lv_obj_set_style_radius(bottom_bar_, 14, 0);
        lv_obj_set_style_bg_color(bottom_bar_, lv_color_hex(0x0b0810), 0);
        lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_80, 0);
        lv_obj_align(bottom_bar_, LV_ALIGN_BOTTOM_MID, 0, -40);
        lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_MODE_DOTS);
        lv_obj_set_size(chat_message_label_, 300, height);
        lv_obj_set_style_text_color(chat_message_label_, lv_color_hex(0xdad3e2), 0);
        lv_obj_set_style_text_line_space(chat_message_label_, 0, 0);
        lv_anim_delete(chat_message_label_, nullptr);
        lv_obj_center(chat_message_label_);
        ESP_LOGI(TAG, "Operator Muse UI: avatar=192, reply=300x%ld, max_lines=2",
                 static_cast<long>(height));
    }

    void UpdatePhase() {
        const auto state = Application::GetInstance().GetDeviceState();
        if (state != last_state_)
            thinking_ = false;
        last_state_ = state;
        const char* label = "STARTING";
        int phase = 0;
        uint32_t color = 0xa28bbd;
        switch (state) {
            case kDeviceStateIdle:
                label = "READY";
                break;
            case kDeviceStateListening:
                label = thinking_ ? "THINKING" : "LISTENING";
                phase = thinking_ ? 2 : 1;
                color = thinking_ ? 0xc5addd : 0x9dc7ba;
                break;
            case kDeviceStateSpeaking:
            case kDeviceStateNotifying:
                label = "SPEAKING";
                phase = 3;
                color = 0xc7b3e0;
                break;
            case kDeviceStateConnecting:
                label = "CONNECTING";
                phase = 2;
                break;
            case kDeviceStateWifiConfiguring:
                label = "SETUP";
                break;
            case kDeviceStateUpgrading:
                label = "UPDATING";
                phase = 2;
                break;
            case kDeviceStateFatalError:
                label = "ERROR";
                color = 0xd9a091;
                break;
            default:
                break;
        }
        if (alert_level_) {
            label = alert_level_ == 2 ? "ERROR" : "NOTICE";
            color = 0xd9a091;
        }
        lv_label_set_text(status_label_, label);
        lv_obj_set_style_text_color(status_label_, lv_color_hex(color), 0);
        lv_obj_set_style_text_color(mic_icon_, lv_color_hex(phase == 1 ? 0x9dc7ba : 0xa69ab9), 0);
        lv_obj_set_style_bg_opa(mic_button_, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(mic_button_, lv_color_hex(phase == 1 ? 0x21352f : 0x211a32), 0);
        const bool subtitle = !lv_obj_has_flag(bottom_bar_, LV_OBJ_FLAG_HIDDEN);
        if (state == kDeviceStateIdle && !subtitle && !alert_level_)
            lv_obj_remove_flag(hint_, LV_OBJ_FLAG_HIDDEN);
        else
            lv_obj_add_flag(hint_, LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < 4; ++i)
            lv_obj_set_style_bg_color(dots_[i], lv_color_hex(i == phase ? color : 0x30263e), 0);
    }
};
