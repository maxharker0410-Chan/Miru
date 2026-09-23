package com.miru.portrait;

import android.Manifest;
import android.app.Activity;
import android.app.WallpaperManager;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.RectF;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private EditText server, token, message;
    private TextView conversation;
    private Preview preview;
    private boolean waitingForOverlay;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("portrait", MODE_PRIVATE);
        int padding = dp(18);
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(padding, padding, padding, padding);
        scroll.addView(body);
        setContentView(scroll);

        TextView title = label("Miru 圖片角色", 25);
        body.addView(title);
        body.addView(label("八張角色圖已內建。可設為桌面動態桌布，或顯示可拖曳的浮動角色；點角色會開啟這個頁面。", 15));
        preview = new Preview();
        body.addView(preview, new LinearLayout.LayoutParams(-1, dp(300)));
        button(body, "設為桌面動態桌布", () -> {
            Intent picker = new Intent(WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER);
            picker.putExtra(WallpaperManager.EXTRA_LIVE_WALLPAPER_COMPONENT,
                    new ComponentName(this, PortraitWallpaper.class));
            try { startActivity(picker); }
            catch (Exception e) { status("無法開啟桌布選擇器：" + e.getMessage()); }
        });
        button(body, "顯示浮動角色（需允許顯示在其他應用程式上層）", this::enableOverlay);
        button(body, "關閉浮動角色", () -> stopService(new Intent(this, PortraitOverlay.class)));

        body.addView(label("表情測試", 19));
        String[] names = {"待機", "思考", "說話", "開心", "難過", "驚訝", "睡覺"};
        for (int i = 0; i < PortraitArt.STATES.length; i++) {
            final String state = PortraitArt.STATES[i];
            button(body, names[i], () -> { PortraitArt.select(this, state); preview.invalidate(); });
        }
        body.addView(label("聊天（需要可從手機連線的 Miru 服務）", 19));
        body.addView(label("同一個 Wi-Fi 上的電腦網址可填 http://電腦區域網路IP:5001；若服務要求權杖，請改用 HTTPS。電腦的 127.0.0.1 不是手機可用的網址。", 14));
        server = field("Miru 服務網址，例如 https://example.com", prefs.getString("server", ""));
        server.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        body.addView(server);
        token = field("存取權杖（可留空）", prefs.getString("token", ""));
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        body.addView(token);
        message = field("輸入訊息", "");
        body.addView(message);
        button(body, "送出訊息", this::sendMessage);
        conversation = label("", 16);
        body.addView(conversation);
        body.addView(label("這是圖片角色測試版，可獨立安裝；聊天使用你設定的 Miru 服務，不會共用 ChatGPT Plus 訂閱。", 13));
    }

    @Override protected void onResume() {
        super.onResume();
        if (waitingForOverlay && Settings.canDrawOverlays(this)) {
            waitingForOverlay = false;
            startOverlay();
        }
    }

    private void enableOverlay() {
        if (Settings.canDrawOverlays(this)) { startOverlay(); return; }
        waitingForOverlay = true;
        Intent permission = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:" + getPackageName()));
        try { startActivity(permission); }
        catch (Exception e) { waitingForOverlay = false; status("請到設定中允許浮動視窗：" + e.getMessage()); }
    }

    private void startOverlay() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 302);
        }
        try {
            Intent intent = new Intent(this, PortraitOverlay.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent);
            else startService(intent);
            status("浮動角色已啟動；可拖動角色調整位置。");
        } catch (Exception e) { status("浮動角色啟動失敗：" + e.getMessage()); }
    }

    private void sendMessage() {
        String base = server.getText().toString().trim().replaceAll("/+$", "");
        String secret = token.getText().toString().trim();
        String text = message.getText().toString().trim();
        if (text.isEmpty()) { status("請先輸入訊息。"); return; }
        if (!base.startsWith("https://") && !base.startsWith("http://")) {
            status("請先填寫 http:// 或 https:// 開頭的 Miru 服務網址。"); return;
        }
        if (!secret.isEmpty() && !base.startsWith("https://")) {
            status("存取權杖只能透過 HTTPS 傳送；請換用 HTTPS 網址。"); return;
        }
        prefs.edit().putString("server", base).putString("token", secret).apply();
        message.setText("");
        status("你：「" + text + "」\nMiru 正在思考……");
        PortraitArt.select(this, "thinking"); preview.invalidate();
        new Thread(() -> {
            HttpURLConnection connection = null;
            String reply;
            try {
                URL url = new URL(base + "/api/chat");
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(12000);
                connection.setReadTimeout(90000);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                if (!secret.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + secret);
                connection.setDoOutput(true);
                JSONObject payload = new JSONObject().put("text", text).put("sync", true);
                try (OutputStream out = connection.getOutputStream()) {
                    out.write(payload.toString().getBytes(StandardCharsets.UTF_8));
                }
                int code = connection.getResponseCode();
                if (code < 200 || code >= 300) throw new Exception("伺服器回傳 HTTP " + code);
                try (InputStream in = connection.getInputStream()) {
                    ByteArrayOutputStream collected = new ByteArrayOutputStream();
                    byte[] bytes = new byte[4096];
                    int count;
                    while ((count = in.read(bytes)) != -1) {
                        if (collected.size() + count > 1024 * 1024) throw new Exception("回覆過長");
                        collected.write(bytes, 0, count);
                    }
                    if (collected.size() == 0) throw new Exception("伺服器回傳空白訊息");
                    JSONObject result = new JSONObject(collected.toString("UTF-8"));
                    reply = result.optString("reply", result.optString("text", ""));
                }
                if (reply.isEmpty()) throw new Exception("Miru 沒有回傳回覆");
                String answer = reply;
                handler.post(() -> {
                    status("你：「" + text + "」\nMiru：" + answer);
                    PortraitArt.select(this, "talking"); preview.invalidate();
                    handler.postDelayed(() -> {
                        PortraitArt.select(this, "idle"); preview.invalidate();
                    }, 3000);
                });
            } catch (Exception e) {
                String error = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                handler.post(() -> {
                    status("無法連上 Miru：" + error + "。請確認手機可連到服務網址。");
                    PortraitArt.select(this, "idle"); preview.invalidate();
                });
            } finally { if (connection != null) connection.disconnect(); }
        }).start();
    }

    private void status(String text) { if (conversation != null) conversation.setText(text); }
    private TextView label(String text, int size) {
        TextView view = new TextView(this);
        view.setText(text); view.setTextSize(size);
        view.setPadding(0, dp(8), 0, dp(8));
        return view;
    }
    private EditText field(String hint, String value) {
        EditText view = new EditText(this);
        view.setSingleLine(true); view.setHint(hint); view.setText(value);
        return view;
    }
    private void button(LinearLayout body, String title, Runnable action) {
        Button button = new Button(this);
        button.setText(title); button.setAllCaps(false);
        button.setOnClickListener(view -> action.run());
        body.addView(button, new LinearLayout.LayoutParams(-1, -2));
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private final class Preview extends View {
        private final PortraitArt art = new PortraitArt(MainActivity.this);
        private final RectF area = new RectF();
        Preview() { super(MainActivity.this); setBackgroundColor(0xfff2eaf6); }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float side = Math.min(getWidth(), getHeight());
            area.set((getWidth() - side) / 2f, (getHeight() - side) / 2f,
                    (getWidth() + side) / 2f, (getHeight() + side) / 2f);
            art.draw(canvas, PortraitArt.selected(MainActivity.this), area);
            if ("idle".equals(PortraitArt.selected(MainActivity.this))) postInvalidateDelayed(100);
        }
        @Override protected void onDetachedFromWindow() { art.close(); super.onDetachedFromWindow(); }
    }
}
import java.io.ByteArrayOutputStream;
