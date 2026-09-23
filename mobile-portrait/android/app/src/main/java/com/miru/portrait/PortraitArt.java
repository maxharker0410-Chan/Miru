package com.miru.portrait;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

final class PortraitArt {
    static final String[] STATES = {"idle", "thinking", "talking", "happy", "sad", "surprised", "sleeping"};
    private final Context context;
    private final Map<String, Bitmap> cache = new HashMap<>();
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);

    PortraitArt(Context context) { this.context = context; }

    synchronized void draw(Canvas canvas, String requested, RectF area) {
        String state = isState(requested) ? requested : "idle";
        if ("idle".equals(state) && SystemClock.uptimeMillis() % 4140L < 140L) state = "blink";
        Bitmap image = image(state);
        if (image != null && !image.isRecycled()) canvas.drawBitmap(image, null, area, paint);
    }

    private static boolean isState(String state) {
        for (String candidate : STATES) if (candidate.equals(state)) return true;
        return false;
    }

    private Bitmap image(String name) {
        Bitmap result = cache.get(name);
        if (result != null) return result;
        try (InputStream in = context.getAssets().open(name + ".png")) {
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inScaled = false;
            result = BitmapFactory.decodeStream(in, null, options);
            if (result != null) cache.put(name, result);
        } catch (IOException ignored) { }
        return result;
    }

    synchronized void close() {
        for (Bitmap bitmap : cache.values()) bitmap.recycle();
        cache.clear();
    }

    static String selected(Context context) {
        return context.getSharedPreferences("portrait", Context.MODE_PRIVATE).getString("state", "idle");
    }

    static void select(Context context, String state) {
        if (!isState(state)) return;
        context.getSharedPreferences("portrait", Context.MODE_PRIVATE).edit().putString("state", state).apply();
        context.sendBroadcast(new android.content.Intent("com.miru.portrait.REFRESH")
                .setPackage(context.getPackageName()));
    }
}
