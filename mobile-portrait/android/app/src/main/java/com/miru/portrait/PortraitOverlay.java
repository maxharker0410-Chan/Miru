package com.miru.portrait;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;

public final class PortraitOverlay extends Service {
    private static final String CHANNEL = "miru_portrait";
    private WindowManager windows;
    private WindowManager.LayoutParams params;
    private CompanionView character;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "stop".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (!Settings.canDrawOverlays(this)) { stopSelf(); return START_NOT_STICKY; }
        if (character != null) return START_STICKY;
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, "Miru 浮動角色", NotificationManager.IMPORTANCE_LOW));
        Intent stop = new Intent(this, PortraitOverlay.class).setAction("stop");
        PendingIntent pending = PendingIntent.getService(this, 0, stop, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notice = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_myplaces).setContentTitle("Miru 角色顯示中")
                .setContentText("點角色聊天，或按此通知關閉").setOngoing(true)
                .setContentIntent(pending).build();
        startForeground(2003, notice);
        try {
            windows = getSystemService(WindowManager.class);
            float density = getResources().getDisplayMetrics().density;
            int side = (int) (176 * density);
            params = new WindowManager.LayoutParams(side, side, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    PixelFormat.TRANSLUCENT);
            params.gravity = Gravity.TOP | Gravity.LEFT;
            SharedPreferences prefs = getSharedPreferences("portrait", MODE_PRIVATE);
            params.x = prefs.getInt("overlay_x", getResources().getDisplayMetrics().widthPixels - side);
            params.y = prefs.getInt("overlay_y", getResources().getDisplayMetrics().heightPixels / 2);
            character = new CompanionView();
            windows.addView(character, params);
        } catch (RuntimeException e) {
            stopSelf();
        }
        return START_STICKY;
    }

    @Override public void onDestroy() {
        if (character != null) {
            character.close();
            try { windows.removeView(character); } catch (RuntimeException ignored) { }
            character = null;
        }
        super.onDestroy();
    }

    private final class CompanionView extends View {
        private final PortraitArt art = new PortraitArt(PortraitOverlay.this);
        private final Handler handler = new Handler(Looper.getMainLooper());
        private final RectF box = new RectF();
        private boolean moved;
        private float startX, startY;
        private int originX, originY;
        private final Runnable tick = new Runnable() {
            @Override public void run() {
                if (character != CompanionView.this) return;
                invalidate(); handler.postDelayed(this, 100);
            }
        };
        CompanionView() { super(PortraitOverlay.this); handler.post(tick); }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            box.set(0, 0, getWidth(), getHeight());
            art.draw(canvas, PortraitArt.selected(PortraitOverlay.this), box);
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    startX = event.getRawX(); startY = event.getRawY();
                    originX = params.x; originY = params.y; moved = false;
                    return true;
                case MotionEvent.ACTION_MOVE:
                    int dx = Math.round(event.getRawX() - startX);
                    int dy = Math.round(event.getRawY() - startY);
                    if (Math.abs(dx) + Math.abs(dy) > 12) moved = true;
                    if (moved) {
                        int sw = getResources().getDisplayMetrics().widthPixels;
                        int sh = getResources().getDisplayMetrics().heightPixels;
                        params.x = Math.max(0, Math.min(sw - getWidth(), originX + dx));
                        params.y = Math.max(0, Math.min(sh - getHeight(), originY + dy));
                        windows.updateViewLayout(this, params);
                    }
                    return true;
                case MotionEvent.ACTION_UP:
                    if (moved) {
                        getSharedPreferences("portrait", MODE_PRIVATE).edit()
                                .putInt("overlay_x", params.x).putInt("overlay_y", params.y).apply();
                    } else {
                        Intent open = new Intent(PortraitOverlay.this, MainActivity.class);
                        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                        startActivity(open);
                    }
                    return true;
            }
            return super.onTouchEvent(event);
        }
        void close() { handler.removeCallbacks(tick); art.close(); }
    }
}
