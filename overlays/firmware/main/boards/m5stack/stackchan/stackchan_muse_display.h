#pragma once

#include "../../waveshare/esp32-s3-touch-amoled-1.75/operator_pixel_font.h"
#include "assets/lang_config.h"
#include "display/lvgl_display/lvgl_theme.h"
#include "material_symbols.h"

#include <algorithm>
#include <cstring>

// StackChan landscape presentation using the same Muse palette and pixel type
// as the round-screen colleagues. Touch comes from the board FT6336 poller.
class StackChanMuseDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;

    ~StackChanMuseDisplay() override {
        DisplayLockGuard lock(this);
        if (lock)
            lv_anim_delete(this, DanceFrame);
    }

    void SetDanceActive(bool active) {
        DisplayLockGuard lock(this);
        if (!lock)
            return;
        dancing_ = active;
        if (chrome_) {
            UpdateDanceAnimation();
            UpdatePhase();
        }
    }

    void HandleTap(int x, int y) {
        if (x >= 8 && x < 52 && y >= 32 && y < 76) {
            auto* codec = Board::GetInstance().GetAudioCodec();
            const int volume = codec->output_volume();
            if (volume > 0)
                restore_volume_ = volume;
            codec->SetOutputVolume(volume > 0 ? 0 : restore_volume_);
            UpdateStatusBar(true);
            return;
        }
        auto& app = Application::GetInstance();
        if (app.GetDeviceState() == kDeviceStateListening)
            app.StopListening();
        else
            app.ToggleChatState();
    }

    void SetTouchPressed(int x, int y, bool pressed) {
        DisplayLockGuard lock(this);
        if (!lock || !chrome_)
            return;
        for (auto* button : {speaker_button_, mic_button_})
            lv_obj_remove_state(button, LV_STATE_PRESSED);
        if (!pressed)
            return;
        if (x >= 8 && x < 52 && y >= 32 && y < 76)
            lv_obj_add_state(speaker_button_, LV_STATE_PRESSED);
        else if (x >= 268 && x < 312 && y >= 32 && y < 76)
            lv_obj_add_state(mic_button_, LV_STATE_PRESSED);
    }

    void SetupUI() override {
        if (setup_ui_called_)
            return;
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);
        if (!lock)
            return;
        CreateChrome();
        ApplyLayout();
        UpdateDanceAnimation();
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
    lv_obj_t* dance_background_ = nullptr;
    lv_obj_t* dance_halos_[3]{};
    lv_obj_t* dance_stars_[10]{};
    uint32_t last_dance_frame_ = 0;
    bool dancing_ = false;
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

    void CreateDanceBackground() {
        // Children of the stock background stay below portrait, captions and chrome.
        dance_background_ = lv_obj_create(container_);
        CleanBox(dance_background_);
        lv_obj_remove_flag(dance_background_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_size(dance_background_, width_, height_);
        lv_obj_set_pos(dance_background_, 0, 0);
        for (int i = 0; i < 3; ++i) {
            auto* halo = lv_obj_create(dance_background_);
            CleanBox(halo);
            lv_obj_remove_flag(halo, LV_OBJ_FLAG_CLICKABLE);
            const int size = 220 - i * 34;
            lv_obj_set_size(halo, size, size);
            lv_obj_set_pos(halo, 76 - size / 2, 144 - size / 2);
            lv_obj_set_style_radius(halo, LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_bg_color(halo, lv_color_hex(0x68368e), 0);
            dance_halos_[i] = halo;
        }
        const int stars[][3] = {{4, 94, 3},   {148, 82, 3},  {10, 214, 2},  {132, 222, 3},
                                {300, 90, 2}, {312, 156, 3}, {166, 204, 3}, {286, 218, 2},
                                {244, 82, 2}, {214, 224, 3}};
        for (int i = 0; i < 10; ++i) {
            auto* star = lv_obj_create(dance_background_);
            CleanBox(star);
            lv_obj_remove_flag(star, LV_OBJ_FLAG_CLICKABLE);
            lv_obj_set_pos(star, stars[i][0], stars[i][1]);
            lv_obj_set_size(star, stars[i][2], stars[i][2]);
            lv_obj_set_style_radius(star, 0, 0);
            lv_obj_set_style_bg_color(star, lv_color_hex(0xc4a6e4), 0);
            dance_stars_[i] = star;
        }
        lv_obj_add_flag(dance_background_, LV_OBJ_FLAG_HIDDEN);
    }

    static void DanceFrame(void* context, int32_t value) {
        auto* self = static_cast<StackChanMuseDisplay*>(context);
        // LVGL executes this callback under its own display lock. No servo/audio work here.
        // Limit full-background redraws to about 12 fps, leaving SPI/CPU room for interaction.
        if (self->last_dance_frame_ && lv_tick_elaps(self->last_dance_frame_) < 80)
            return;
        self->last_dance_frame_ = lv_tick_get();
        lv_obj_set_style_bg_color(self->container_,
                                  lv_color_mix(lv_color_hex(0x180b25), lv_color_black(), value), 0);
        for (int i = 0; i < 3; ++i)
            lv_obj_set_style_bg_opa(self->dance_halos_[i], 8 + value * (i + 1) / 16, 0);
        for (int i = 0; i < 10; ++i) {
            const int phase = (value + i * 47) % 256;
            const int brightness = phase < 128 ? phase : 255 - phase;
            lv_obj_set_style_bg_opa(self->dance_stars_[i], 40 + brightness * 4 / 3, 0);
        }
    }

    void UpdateDanceAnimation() {
        if (!dance_background_)
            return;
        lv_anim_delete(this, DanceFrame);
        last_dance_frame_ = 0;
        if (dancing_) {
            lv_obj_remove_flag(dance_background_, LV_OBJ_FLAG_HIDDEN);
            lv_anim_t animation;
            lv_anim_init(&animation);
            lv_anim_set_var(&animation, this);
            lv_anim_set_exec_cb(&animation, DanceFrame);
            lv_anim_set_values(&animation, 24, 220);
            // Each half-beat matches one 600 ms firmware dance step.
            lv_anim_set_duration(&animation, 600);
            lv_anim_set_reverse_duration(&animation, 600);
            lv_anim_set_path_cb(&animation, lv_anim_path_ease_in_out);
            lv_anim_set_repeat_count(&animation, LV_ANIM_REPEAT_INFINITE);
            lv_anim_start(&animation);
        } else {
            lv_obj_add_flag(dance_background_, LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_style_bg_color(container_, lv_color_black(), 0);
        }
        ESP_LOGI("StackChanMuse", "Dance background: %s", dancing_ ? "animated" : "black");
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
        CreateDanceBackground();
        chrome_ = lv_obj_create(screen);
        CleanBox(chrome_);
        lv_obj_remove_flag(chrome_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_size(chrome_, width_, height_);
        lv_obj_center(chrome_);
        // A quiet circular aura frames the unchanged 128px portrait on the left.
        lv_obj_move_to_index(chrome_, 1);
        auto* rim = lv_obj_create(chrome_);
        CleanBox(rim);
        lv_obj_remove_flag(rim, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_pos(rim, 6, 74);
        lv_obj_set_size(rim, 140, 140);
        lv_obj_set_style_radius(rim, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(rim, 1, 0);
        lv_obj_set_style_border_color(rim, lv_color_hex(0x1b1627), 0);
        const int stars[][3] = {{8, 84, 2}, {137, 92, 3}, {5, 179, 2}, {139, 199, 2}};
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
        speaker_button_ = MakeButton(8, 32, 44, MATERIAL_SYMBOLS_VOLUME_UP, &speaker_icon_);
        mic_button_ = MakeButton(268, 32, 44, MATERIAL_SYMBOLS_MIC, &mic_icon_);
        hint_ = MakeLabel(chrome_, "TAP SCREEN TO TALK", &lv_font_montserrat_14, 0x81748f);
        lv_obj_set_style_text_letter_space(hint_, 1, 0);
        lv_obj_align(hint_, LV_ALIGN_BOTTOM_MID, 0, -10);
        for (int i = 0; i < 4; ++i) {
            dots_[i] = lv_obj_create(chrome_);
            CleanBox(dots_[i]);
            lv_obj_remove_flag(dots_[i], LV_OBJ_FLAG_CLICKABLE);
            lv_obj_set_size(dots_[i], 5, 5);
            lv_obj_set_style_radius(dots_[i], 1, 0);
            lv_obj_set_pos(dots_[i], 139 + i * 12, 70);
            lv_obj_set_style_bg_opa(dots_[i], LV_OPA_COVER, 0);
        }
    }

    void ApplyLayout() {
        auto* screen = lv_screen_active();
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        lv_obj_set_style_bg_color(container_, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(container_, LV_OPA_COVER, 0);
        CleanBox(emoji_box_);
        lv_obj_set_size(emoji_box_, 136, 136);
        lv_obj_align(emoji_box_, LV_ALIGN_TOP_LEFT, 8, 76);
        lv_image_set_scale(emoji_image_, 256);
        lv_image_set_antialias(emoji_image_, false);
        lv_obj_center(emoji_image_);
        lv_obj_center(emoji_label_);

        CleanBox(top_bar_);
        lv_obj_set_style_layout(top_bar_, LV_LAYOUT_NONE, 0);
        lv_obj_set_size(top_bar_, 296, 24);
        lv_obj_align(top_bar_, LV_ALIGN_TOP_LEFT, 12, 3);
        lv_obj_set_parent(network_label_, top_bar_);
        lv_obj_set_parent(battery_label_, top_bar_);
        lv_obj_set_pos(network_label_, 0, 0);
        lv_obj_set_pos(battery_label_, 272, 0);
        lv_obj_set_pos(power_text_, 73, 3);
        lv_obj_set_style_text_color(network_label_, lv_color_hex(0x8d829f), 0);
        lv_obj_set_style_text_color(battery_label_, lv_color_hex(0x8d829f), 0);
        lv_obj_add_flag(mute_label_, LV_OBJ_FLAG_HIDDEN);
        auto* theme = static_cast<LvglTheme*>(current_theme_);
        const auto* icon_font = theme->icon_font()->font();
        for (auto* label : {network_label_, battery_label_, speaker_icon_, mic_icon_})
            lv_obj_set_style_text_font(label, icon_font, 0);

        CleanBox(status_bar_);
        lv_obj_set_size(status_bar_, 208, 30);
        lv_obj_align(status_bar_, LV_ALIGN_TOP_LEFT, 56, 36);
        lv_obj_set_size(status_label_, 204, 26);
        lv_obj_set_style_text_font(status_label_, &operator_ui::kPixelFont, 0);
        lv_obj_set_style_text_color(status_label_, lv_color_hex(0xc0adcf), 0);
        lv_obj_set_style_text_letter_space(status_label_, 1, 0);
        lv_label_set_long_mode(status_label_, LV_LABEL_LONG_MODE_CLIP);
        lv_obj_center(status_label_);
        // Alerts may contain long Chinese text; keep them on a separate full-width bar.
        lv_obj_set_parent(notification_label_, screen);
        lv_obj_set_width(notification_label_, 296);
        lv_obj_set_style_bg_color(notification_label_, lv_color_hex(0x0b0810), 0);
        lv_obj_set_style_bg_opa(notification_label_, LV_OPA_COVER, 0);
        lv_obj_set_style_text_color(notification_label_, lv_color_hex(0xd8cee6), 0);
        lv_obj_align(notification_label_, LV_ALIGN_TOP_MID, 0, 78);

        const auto* font = lv_obj_get_style_text_font(chat_message_label_, LV_PART_MAIN);
        const int height = std::min<int>(92, 2 * font->line_height);
        CleanBox(bottom_bar_);
        lv_obj_set_size(bottom_bar_, 156, height + 16);
        lv_obj_set_style_pad_all(bottom_bar_, 8, 0);
        lv_obj_set_style_radius(bottom_bar_, 12, 0);
        lv_obj_set_style_bg_color(bottom_bar_, lv_color_hex(0x0b0810), 0);
        lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_COVER, 0);
        lv_obj_align(bottom_bar_, LV_ALIGN_TOP_LEFT, 152, 92);
        lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_MODE_DOTS);
        lv_obj_set_size(chat_message_label_, 140, height);
        lv_obj_set_style_text_color(chat_message_label_, lv_color_hex(0xdad3e2), 0);
        lv_obj_set_style_text_line_space(chat_message_label_, 0, 0);
        lv_anim_delete(chat_message_label_, nullptr);
        lv_obj_center(chat_message_label_);
        ESP_LOGI("StackChanMuse",
                 "Muse landscape: 320x240, avatar=128 left, reply=140x%d right, controls=44",
                 height);
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
        if (dancing_) {
            label = "DANCING";
            phase = 3;
            color = 0x9dc7ba;
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
        lv_label_set_text(hint_, dancing_ ? "TAP AVATAR TO STOP" : "HOLD AVATAR TO DANCE");
        const bool subtitle = !lv_obj_has_flag(bottom_bar_, LV_OBJ_FLAG_HIDDEN);
        if (state == kDeviceStateIdle && !subtitle && !alert_level_)
            lv_obj_remove_flag(hint_, LV_OBJ_FLAG_HIDDEN);
        else
            lv_obj_add_flag(hint_, LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < 4; ++i)
            lv_obj_set_style_bg_color(dots_[i], lv_color_hex(i == phase ? color : 0x30263e), 0);
    }
};
