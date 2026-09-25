package com.miru.portrait;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

final class PortraitArt {
    static final String[] STATES = {"idle", "thinking", "talking", "happy", "sad", "surprised", "sleeping", "shy", "angry"};
    static final String[] OUTFITS = {"normal", "home", "outdoor"};
    private final Context context;
    private final Map<String, Bitmap> cache = new HashMap<>();
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private String cachedOutfit = "normal";

    PortraitArt(Context context) { this.context = context; }

    synchronized void draw(Canvas canvas, String requested, RectF area) {
        String outfit = outfit(context);
        if (!outfit.equals(cachedOutfit)) { close(); cachedOutfit = outfit; }
        String state = isState(requested) ? requested : "idle";
        if ("idle".equals(state) && SystemClock.uptimeMillis() % 4140L < 140L) state = "blink";
        Bitmap image = image(("normal".equals(outfit) ? "" : outfit + "/") + resolve(outfit,state));
        if (image != null && !image.isRecycled()) canvas.drawBitmap(image, null, area, paint);
    }

    private static String resolve(String outfit, String state) {
        if ("home".equals(outfit)) {
            if ("blink".equals(state) || "talking".equals(state)) return "idle";
            if ("happy".equals(state) || "surprised".equals(state)) return "shy";
        } else if ("outdoor".equals(outfit)) {
            if ("sad".equals(state) || "angry".equals(state)) return "shy";
            if ("sleeping".equals(state)) return "blink";
        } else {
            if ("shy".equals(state)) return "happy";
            if ("angry".equals(state)) return "sad";
        }
        return state;
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

    static String outfit(Context context) {
        String chosen = context.getSharedPreferences("portrait", Context.MODE_PRIVATE).getString("outfit", "normal");
        for (String value : OUTFITS) if (value.equals(chosen)) return value;
        return "normal";
    }

    static void changeOutfit(Context context, String chosen) {
        boolean valid = false;
        for (String value : OUTFITS) if (value.equals(chosen)) valid = true;
        if (!valid) return;
        context.getSharedPreferences("portrait", Context.MODE_PRIVATE).edit().putString("outfit", chosen).apply();
    }

    static void select(Context context, String state) {
        if (!isState(state)) return;
        context.getSharedPreferences("portrait", Context.MODE_PRIVATE).edit().putString("state", state).apply();
        context.sendBroadcast(new android.content.Intent("com.miru.portrait.REFRESH")
                .setPackage(context.getPackageName()));
    }
}
