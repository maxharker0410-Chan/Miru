package com.miru.portrait;

import android.app.WallpaperManager;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.RectF;
import android.os.Handler;
import android.os.Looper;
import android.service.wallpaper.WallpaperService;
import android.view.MotionEvent;
import android.view.SurfaceHolder;

public final class PortraitWallpaper extends WallpaperService {
    @Override public Engine onCreateEngine() { return new PortraitEngine(); }

    private final class PortraitEngine extends Engine {
        private final Handler handler = new Handler(Looper.getMainLooper());
        private final PortraitArt art = new PortraitArt(PortraitWallpaper.this);
        private final RectF bounds = new RectF();
        private boolean visible, destroyed;
        private float downX, downY;
        private final Runnable redraw = new Runnable() {
            @Override public void run() {
                if (!visible || destroyed) return;
                Canvas canvas = null;
                try {
                    canvas = getSurfaceHolder().lockCanvas();
                    if (canvas != null) {
                        int w = canvas.getWidth(), h = canvas.getHeight();
                        canvas.drawColor(Color.rgb(242, 234, 246));
                        float size = Math.min(w * .94f, h * .56f);
                        float left = (w - size) / 2f;
                        bounds.set(left, h - size - h * .14f, left + size, h - h * .14f);
                        art.draw(canvas, PortraitArt.selected(PortraitWallpaper.this), bounds);
                    }
                } catch (Exception ignored) {
                } finally {
                    if (canvas != null) getSurfaceHolder().unlockCanvasAndPost(canvas);
                }
                handler.postDelayed(this, 100);
            }
        };

        PortraitEngine() { setTouchEventsEnabled(true); }
        @Override public void onVisibilityChanged(boolean isVisible) {
            visible = isVisible;
            handler.removeCallbacks(redraw);
            if (visible) handler.post(redraw);
        }
        @Override public void onSurfaceChanged(SurfaceHolder holder, int format, int width, int height) {
            super.onSurfaceChanged(holder, format, width, height);
            if (visible) { handler.removeCallbacks(redraw); handler.post(redraw); }
        }
        @Override public void onTouchEvent(MotionEvent event) {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                downX = event.getX(); downY = event.getY();
            } else if (event.getAction() == MotionEvent.ACTION_UP
                    && Math.hypot(event.getX() - downX, event.getY() - downY) < 24
                    && bounds.contains(event.getX(), event.getY())) {
                Intent open = new Intent(PortraitWallpaper.this, MainActivity.class);
                open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                startActivity(open);
            }
        }
        @Override public void onDestroy() {
            destroyed = true; visible = false;
            handler.removeCallbacks(redraw); art.close();
            super.onDestroy();
        }
    }
}
