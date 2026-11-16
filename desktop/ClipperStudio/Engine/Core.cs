// Core of the desktop engine: paths, JSON helpers, FFmpeg / GPU access and the studio catalog.
// The maths here mirrors clipper/media/studio.py line by line, so both apps render the same EDL alike.
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace ClipperStudio.Engine;

public static class Paths
{
    public static readonly string App = AppContext.BaseDirectory;
    public static readonly string Web = Path.Combine(App, "web");
    public static readonly string Assets = Path.Combine(App, "assets");
    public static readonly string Fonts = Path.Combine(Assets, "fonts");
    public static readonly string Sfx = Path.Combine(Assets, "sfx");
    public static readonly string StudioDir = Path.Combine(Assets, "studio");
    public static readonly string Data = DataDirectory(App, Environment.GetEnvironmentVariable("CLIPPER_STUDIO_DATA"));

    // Only the portable ZIP carries this marker. Installed builds retain the existing user library.
    public static string DataDirectory(string applicationDirectory, string? overrideDirectory) =>
        !string.IsNullOrWhiteSpace(overrideDirectory) ? Path.GetFullPath(overrideDirectory)
        : File.Exists(Path.Combine(applicationDirectory,"portable.flag")) ? Path.Combine(applicationDirectory,"data")
        : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ClipperStudio");

    public static string Tool(string name)
    {
        // Next to the app, then in the user's data folder (where the in-app installer puts them), then PATH.
        foreach (var dir in new[] { Path.Combine(App, "tools"), Path.Combine(Data, "tools") })
            if (File.Exists(Path.Combine(dir, name + ".exe"))) return Path.Combine(dir, name + ".exe");
        return name;
    }

    public static string Dir(params string[] parts)
    {
        var d = Path.Combine([Data, .. parts]);
        Directory.CreateDirectory(d);
        return d;
    }
}

/// <summary>Small helpers so EDLs can stay as JSON trees, with the same shape the Python app stores.</summary>
public static class J
{
    public static readonly JsonSerializerOptions Pretty = new() { WriteIndented = true };
    public static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    public static double D(JsonNode? n, double def = 0)
    {
        try
        {
            if (n is JsonValue v)
            {
                if (v.TryGetValue(out double d)) return double.IsFinite(d) ? d : def;
                if (v.TryGetValue(out string? s))
                    return double.TryParse(s, NumberStyles.Float, Inv, out d) && double.IsFinite(d) ? d : def;
                // Values created by the C# engine may hold int/long/decimal rather than double.
                if (double.TryParse(v.ToJsonString(), NumberStyles.Float, Inv, out d) && double.IsFinite(d)) return d;
            }
        }
        catch { }
        return def;
    }

    public static string S(JsonNode? n, string def = "")
    {
        try { return n is JsonValue v && v.TryGetValue(out string? s) && s != null ? s : def; } catch { return def; }
    }

    public static bool B(JsonNode? n, bool def = false)
    {
        try { return n is JsonValue v && v.TryGetValue(out bool b) ? b : def; } catch { return def; }
    }

    public static double Num(JsonNode? n, double def, double lo, double hi)
    {
        var v = n is JsonValue ? D(n, double.NaN) : double.NaN;
        return double.IsNaN(v) ? def : Math.Round(Math.Min(hi, Math.Max(lo, v)), 3);
    }

    public static IEnumerable<JsonNode> Items(JsonNode? n) => n is JsonArray a ? a.Where(x => x != null).Select(x => x!) : [];
    public static JsonObject Obj(JsonNode? n) => n as JsonObject ?? [];
    public static JsonNode Clone(JsonNode n) => JsonNode.Parse(n.ToJsonString())!;
    public static string F(double v, string fmt = "0.###") => v.ToString(fmt, Inv);
}

public class FfmpegException(string message) : Exception(message);

public static class Ff
{
    static readonly SemaphoreSlim Slots = new(3);

    public static (int code, string stdout, string stderr) Exec(string tool, IEnumerable<string> args, bool binaryStdout = false, Action<byte[]>? onStdout = null)
    {
        var psi = new ProcessStartInfo(Paths.Tool(tool)) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, CreateNoWindow = true };
        if (!binaryStdout) psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        foreach (var a in args) psi.ArgumentList.Add(a);
        using var p = Process.Start(psi) ?? throw new FfmpegException($"No se pudo iniciar {tool}.");
        var err = p.StandardError.ReadToEndAsync();
        string output = "";
        if (binaryStdout)
        {
            using var ms = new MemoryStream();
            p.StandardOutput.BaseStream.CopyTo(ms);
            onStdout?.Invoke(ms.ToArray());
        }
        else output = p.StandardOutput.ReadToEnd();
        p.WaitForExit();
        return (p.ExitCode, output, err.Result);
    }

    /// <summary>Run ffmpeg; returns its log (stderr). Throws with the tail of the log when it fails.</summary>
    public static string Run(IEnumerable<string> args)
    {
        string[] full = ["-hide_banner", "-nostdin", "-y", .. args];
        (int code, _, string err) = Exec("ffmpeg", full);
        if (code != 0) throw new FfmpegException($"ffmpeg falló ({code}): {string.Join(' ', full.Take(12))} ...\n{Tail(err, 2500)}");
        return err;
    }

    public static string RunLimited(IEnumerable<string> args)
    {
        Slots.Wait();
        try { return Run(args); } finally { Slots.Release(); }
    }

    public static string Tail(string s, int n) => s.Length <= n ? s : s[^n..];

    public static bool Available
    {
        get { try { return Exec("ffmpeg", ["-version"]).code == 0; } catch { return false; } }
    }

    public static JsonObject Probe(string path)
    {
        var (code, stdout, err) = Exec("ffprobe", ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]);
        if (code != 0) throw new FfmpegException($"ffprobe falló con {path}: {Tail(err, 800)}");
        var info = JsonNode.Parse(stdout)!;
        var streams = J.Items(info["streams"]).ToList();
        var video = streams.FirstOrDefault(s => J.S(s["codec_type"]) == "video") ?? throw new FfmpegException($"{path} no tiene video.");
        var audio = streams.FirstOrDefault(s => J.S(s["codec_type"]) == "audio");
        var rate = J.S(video["avg_frame_rate"], "0/1").Split('/');
        double den = rate.Length > 1 ? double.Parse(rate[1], J.Inv) : 1, fps = den != 0 ? double.Parse(rate[0], J.Inv) / den : 0;
        int w = (int)J.D(video["width"]), h = (int)J.D(video["height"]), rotation = 0;
        foreach (var sd in J.Items(video["side_data_list"])) if (sd["rotation"] != null) rotation = (int)J.D(sd["rotation"]);
        if (Math.Abs(rotation) is 90 or 270) (w, h) = (h, w);
        return new JsonObject
        {
            ["duration"] = J.D(info["format"]?["duration"], J.D(video["duration"])), ["width"] = w, ["height"] = h, ["fps"] = Math.Round(fps, 3),
            ["has_audio"] = audio != null, ["video_codec"] = J.S(video["codec_name"]), ["audio_codec"] = audio == null ? null : J.S(audio["codec_name"]),
        };
    }

    /// <summary>The card the render uses ("name · driver x"), or "" on the CPU. Any vendor: see Gpu.cs.</summary>
    public static string Gpu => Hw.Profile.Hardware ? Hw.Profile.Device : "";

    /// <summary>Best working H.264 encoder (NVENC, AMF, Quick Sync, Media Foundation or libx264), found by
    /// real test encodes: an encoder can be compiled into FFmpeg and still fail (no card, old driver).</summary>
    public static string Encoder => Hw.Profile.Encoder;

    public static bool Nvenc => Encoder.EndsWith("_nvenc");
    public static bool Hardware => Hw.Profile.Hardware;

    /// <summary>Forget what was learned about the hardware (after FFmpeg or a driver is installed or replaced).</summary>
    public static void Reset() => Hw.Reset();
    public static string FilterPath(string path) => path.Replace("\\", "/").Replace(":", "\\:").Replace("'", "\\'");
}

/// <summary>Colour looks, effects, caption styles, text presets and bundled fonts (assets/studio, assets/fonts).</summary>
public static class Studio
{
    static readonly double[] Luma = [0.2126, 0.7152, 0.0722];
    static readonly double[][] Sepia = [[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]];
    static readonly string[] Unipolar = ["fade", "sepia", "vignette"];
    static readonly ConcurrentDictionary<string, double> Scales = new();

    public static readonly JsonNode Catalog = JsonNode.Parse(File.ReadAllText(Path.Combine(Paths.StudioDir, "catalog.json")))!;
    public static readonly JsonNode Fx = Catalog["fx"]!;
    public static readonly Dictionary<string, FontInfo> Fonts = LoadFonts();

    public record FontInfo(string Id, string Label, string Family, string Path, bool Bold);

    static Dictionary<string, FontInfo> LoadFonts()
    {
        var index = Path.Combine(Paths.Fonts, "fonts.json");
        var map = new Dictionary<string, FontInfo>();
        if (!File.Exists(index)) return map;
        foreach (var f in J.Items(JsonNode.Parse(File.ReadAllText(index))))
        {
            var path = Path.Combine(Paths.Fonts, J.S(f["file"]));
            if (File.Exists(path)) map[J.S(f["id"])] = new(J.S(f["id"]), J.S(f["label"]), J.S(f["family"]), path, J.B(f["bold"]));
        }
        return map;
    }

    public static FontInfo Font(string id) => Fonts.TryGetValue(id, out var f) ? f : Fonts.GetValueOrDefault("caption") ?? Fonts.Values.First();
    public static readonly JsonNode FaceFocus = JsonNode.Parse("""{"id":"face_focus","label":"Reacción / cara","desc":"Amplía una región de la cara en un recuadro animado. Ajusta la región si la persona se mueve.","d":1.5,"min":0.4,"max":2.5}""")!;
    public static JsonNode? Effect(string id) => id == "face_focus" ? FaceFocus : J.Items(Catalog["effects"]).FirstOrDefault(e => J.S(e["id"]) == id);
    public static JsonNode Style(string id) => Catalog["caption_styles"]![id] ?? Catalog["caption_styles"]!["bold"]!;

    /// <summary>Em size per unit of ASS font size, the way libass sizes text (OS/2 win metrics, else hhea).</summary>
    public static double FontScale(string path) => Scales.GetOrAdd(path, p =>
    {
        try
        {
            var d = File.ReadAllBytes(p);
            int U16(int o) => (d[o] << 8) | d[o + 1];
            int S16(int o) => (short)U16(o);
            int U32(int o) => (U16(o) << 16) | U16(o + 2);
            var tables = new Dictionary<string, int>();
            for (int i = 0, n = U16(4); i < n; i++) tables[Encoding.ASCII.GetString(d, 12 + 16 * i, 4)] = U32(12 + 16 * i + 8);
            int upm = U16(tables["head"] + 18), height = 0;
            if (tables.TryGetValue("OS/2", out var os2)) height = U16(os2 + 74) + U16(os2 + 76);
            if (height == 0) height = S16(tables["hhea"] + 4) - S16(tables["hhea"] + 6);
            return Math.Round((double)upm / height, 4);
        }
        catch { return 0.83; }
    });

    // ---------- colour ----------
    public static Dictionary<string, double> ColorParams(JsonNode? color)
    {
        var c = J.Obj(color);
        var look = J.Items(Catalog["looks"]).FirstOrDefault(l => J.S(l["id"]) == J.S(c["look"], "none"))?["p"];
        double amount = J.D(c["look_amount"], 1);
        var o = new Dictionary<string, double>();
        foreach (var kn in J.Items(Catalog["color_params"]))
        {
            var k = J.S(kn);
            double v = J.D(look?[k]) * amount + J.D(c[k]);
            o[k] = Math.Max(Unipolar.Contains(k) ? 0 : -1, Math.Min(1, v));
        }
        return o;
    }

    /// <summary>The grade as three rows [r, g, b, offset] on gamma-encoded RGB in 0..1; null when it changes nothing.</summary>
    public static double[][]? ColorAffine(Dictionary<string, double> p)
    {
        double sat = 1 + p["saturation"];
        var m = new double[3][];
        for (int i = 0; i < 3; i++) { m[i] = new double[3]; for (int j = 0; j < 3; j++) m[i][j] = (1 - sat) * Luma[j] + (i == j ? sat : 0); }
        double sp = p["sepia"];
        if (sp != 0)
        {
            var r = new double[3][];
            for (int i = 0; i < 3; i++)
            {
                r[i] = new double[3];
                for (int j = 0; j < 3; j++)
                    for (int k = 0; k < 3; k++) r[i][j] += ((1 - sp) * (i == k ? 1 : 0) + sp * Sepia[i][k]) * m[k][j];
            }
            m = r;
        }
        double t = p["temperature"], ti = p["tint"], c = p["contrast"], f = p["fade"];
        double[] gains = [1 + 0.18 * t + 0.05 * ti, 1 - 0.14 * ti, 1 - 0.18 * t + 0.05 * ti];
        double slope = 1 + c * (c >= 0 ? 0.6 : 0.5), k2 = slope * (1 - 0.2 * f);
        double off = Math.Round((0.5 - 0.5 * slope + 0.25 * p["brightness"]) * (1 - 0.2 * f) + 0.1 * f, 5);
        var rows = new double[3][];
        bool ident = Math.Abs(off) < 1e-4;
        for (int i = 0; i < 3; i++)
        {
            rows[i] = new double[4];
            for (int j = 0; j < 3; j++)
            {
                rows[i][j] = Math.Round(Math.Max(-2, Math.Min(2, k2 * gains[i] * m[i][j])), 5);
                if (Math.Abs(rows[i][j] - (i == j ? 1 : 0)) >= 1e-4) ident = false;
            }
            rows[i][3] = off;
        }
        return ident ? null : rows;
    }

    /// <summary>FFmpeg filter for the grade: colorchannelmixer, with its alpha input (always 1) as the offset term.</summary>
    public static string? ColorFilter(JsonNode? color)
    {
        var rows = ColorAffine(ColorParams(color));
        if (rows == null) return null;
        var parts = new List<string>();
        for (int i = 0; i < 3; i++) for (int j = 0; j < 4; j++) parts.Add($"{"rgb"[i]}{"rgba"[j]}={J.F(rows[i][j], "0.#####")}");
        return "format=rgba,colorchannelmixer=" + string.Join(':', parts) + ",format=yuv420p";
    }

    /// <summary>#RRGGBB -> BBGGRR (the colour part of an ASS &amp;HAABBGGRR value).</summary>
    public static string Bgr(string hex)
    {
        var h = Regex.IsMatch(hex ?? "", "^#[0-9A-Fa-f]{6}$") ? hex!.TrimStart('#').ToUpperInvariant() : "FFFFFF";
        return h[4..6] + h[2..4] + h[0..2];
    }

    public static string AssColor(string hex) => "&H00" + Bgr(hex);
    public static string Alpha(double opacity) => $"&H{(int)Math.Round((1 - Math.Max(0, Math.Min(1, opacity))) * 255):X2}&";
}
