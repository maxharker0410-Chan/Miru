package com.miru.portrait;

final class OutfitCommand {
    private OutfitCommand() { }

    static String parse(String text, String current) {
        String input = text.replaceAll("\\s+", "");
        if (!(input.contains("換") || input.contains("穿") || input.contains("切換") || input.contains("改成"))
                || !(input.contains("衣") || input.contains("服") || input.contains("裝") || input.contains("造型"))) {
            return null;
        }
        if (input.contains("居家") || input.contains("家居") || input.contains("睡衣") || input.contains("家裡")) return "home";
        if (input.contains("外出") || input.contains("出門") || input.contains("外面")) return "outdoor";
        if (input.contains("一般") || input.contains("平常") || input.contains("原本") || input.contains("預設")
                || input.contains("普通")) return "normal";
        if ("normal".equals(current)) return "home";
        if ("home".equals(current)) return "outdoor";
        return "normal";
    }
}
