using System.Text.Json.Nodes;

namespace ClipperStudio.Engine;

public record TextPlacement(int X, int Y, int FontSize, double Em, List<string> Lines, int StartX, int StartY, double HalfWidth, double HalfHeight);

/// <summary>Conservative shared Shorts/Reels work area, not a universal platform pixel specification.</summary>
public static class SafeArea
{
    public const int Left = 180, RightMargin = 180, Top = 300, BottomMargin = 680;
    public const int Right = Ass.W - RightMargin, Bottom = Ass.H - BottomMargin;
    public const int Width = Right - Left, Height = Bottom - Top, CenterX = (Left + Right) / 2;
    public const string Profile = "shorts_reels_centered_v2";
    public static string Clip => $"\\clip({Left},{Top},{Right},{Bottom})";
    public static JsonObject Json() => new()
    {
        ["profile"] = Profile, ["enforced"] = true, ["left"] = Left, ["right"] = RightMargin,
        ["top"] = Top, ["bottom"] = BottomMargin, ["side"] = Left,
        ["width"] = Width, ["height"] = Height, ["center_x"] = CenterX,
        ["note"] = "Perfil común conservador para Shorts y Reels. La interfaz puede variar según dispositivo y publicación.",
    };

    public static TextPlacement PlaceText(JsonNode tx, string language)
    {
        string font = Studio.Font(J.S(tx["font"], "anton")).Id;
        double em = J.D(tx["size"], 80), rotation = Math.Abs(J.D(tx["rotate"])) * Math.PI / 180;
        string animation = J.S(tx["anim_in"]);
        double factor = animation == "zoom" ? 1.6 : animation == "pop" ? 1.12 : 1;
        int slide = animation.StartsWith("slide_") ? (int)J.D(Studio.Catalog["anim"]!["slide_px"]) : 0;
        double leftMotion = animation == "slide_right" ? slide : 0, rightMotion = animation == "slide_left" ? slide : 0;
        double topMotion = animation == "slide_down" ? slide : 0, bottomMotion = animation == "slide_up" ? slide : 0;
        double pad = J.S(tx["box"]) != "" ? Ass.TextBoxPad : J.D(tx["stroke_w"], 6) + J.D(tx["glow"]) * 3;
        for (; em >= 8; em -= 1)
        {
            int fs = Math.Max(1, (int)Math.Round(em / Studio.FontScale(Studio.Font(font).Path)));
            var lines = new List<string>();
            foreach (var raw in J.S(tx["text"]?[language]).Replace("\r", "").Split('\n'))
            {
                var text = J.B(tx["upper"]) ? raw.ToUpperInvariant() : raw;
                if (text.Trim() != "") lines.AddRange(Ass.Wrap(text, font, fs, Math.Max(40, (Width - leftMotion - rightMotion) / factor - 2 * pad)));
            }
            if (lines.Count == 0) return new(CenterX, (Top + Bottom) / 2, fs, em, lines, CenterX, (Top + Bottom) / 2, 0, 0);
            double w = lines.Max(line => Ass.TextWidth(line, font, fs)) + 2 * pad, h = lines.Count * fs + 2 * pad;
            double hw = (Math.Cos(rotation) * w + Math.Sin(rotation) * h) * factor / 2 + 4;
            double hh = (Math.Sin(rotation) * w + Math.Cos(rotation) * h) * factor / 2 + 4;
            int minX = (int)Math.Ceiling(Left + hw + leftMotion), maxX = (int)Math.Floor(Right - hw - rightMotion);
            int minY = (int)Math.Ceiling(Top + hh + topMotion), maxY = (int)Math.Floor(Bottom - hh - bottomMotion);
            if (minX > maxX || minY > maxY) continue;
            int x = Math.Clamp((int)Math.Round(J.D(tx["x"], .5) * Ass.W), minX, maxX);
            int y = Math.Clamp((int)Math.Round(J.D(tx["y"], .3) * Ass.H), minY, maxY);
            return new(x, y, fs, em, lines, x - (int)leftMotion + (int)rightMotion,
                y - (int)topMotion + (int)bottomMotion, hw, hh);
        }
        throw new EditException("El texto es demasiado grande para la zona segura. Reduce el contenido o la rotación.");
    }
}
