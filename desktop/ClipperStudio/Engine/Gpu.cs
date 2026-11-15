// Hardware for rendering, vendor-neutral: which graphics adapters exist (DXGI, with a registry fallback),
// which FFmpeg encoders really work on them (a short test encode, never just "compiled in"), and the
// arguments each vendor needs. Nothing here assumes a card: with none, everything runs on the CPU.
//
// Preference: dedicated NVIDIA (NVENC) → dedicated AMD (AMF) → Intel Arc (Quick Sync) → integrated
// Intel (Quick Sync) → integrated AMD (AMF) → Media Foundation (any Windows GPU driver) → CPU (libx264).
// CLIPPER_ENCODER=<id> forces one encoder (e.g. libx264 to test the CPU path on a gaming PC).
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace ClipperStudio.Engine;

public enum GpuVendor { Nvidia, Amd, Intel, Microsoft, Other }

public record GpuAdapter(int Index, string Name, GpuVendor Vendor, uint VendorId, uint DeviceId, long DedicatedMb, long SharedMb, bool Integrated, bool Software, string Driver)
{
    public string Kind => Software ? "software" : Integrated ? "integrada" : "dedicada";
}

public record HwProfile(IReadOnlyList<GpuAdapter> Adapters, IReadOnlyList<string> Working, string Encoder, GpuAdapter? Adapter, string? Hwaccel, string Mode, string Note)
{
    /// <summary>"gpu" (dedicated card), "igpu" (integrated graphics) or "cpu".</summary>
    public bool Hardware => Mode != "cpu";
    public string Device => Adapter == null ? "" : Adapter.Driver == "" ? Adapter.Name : $"{Adapter.Name} · driver {Adapter.Driver}";
}

public static class Hw
{
    /// <summary>Every encoder the app knows, in the order shown in settings.</summary>
    public static readonly string[] Known =
        ["h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_amf", "hevc_amf", "av1_amf", "h264_qsv", "hevc_qsv", "av1_qsv", "h264_mf", "hevc_mf", "libx264"];

    static readonly object Gate = new();
    static HwProfile? _profile;
    static readonly ConcurrentDictionary<string, int> Recipe = new();          // "enc|fast" → index of the first recipe that encodes (-1: none)
    static readonly ConcurrentDictionary<string, List<string>?> Decode = new(); // family → verified -hwaccel arguments (null: decode on the CPU)

    public static HwProfile Profile { get { lock (Gate) return _profile ??= Detect(); } }

    /// <summary>Forget everything learned (after FFmpeg or a driver is installed or replaced).</summary>
    public static void Reset() { lock (Gate) { _profile = null; _adapters = null; Recipe.Clear(); Decode.Clear(); Devices.Clear(); } }

    public static string Family(string enc) => enc == "libx264" ? "cpu" : enc[(enc.LastIndexOf('_') + 1)..];

    public static GpuVendor? VendorOf(string enc) => Family(enc) switch
    {
        "nvenc" => GpuVendor.Nvidia, "amf" => GpuVendor.Amd, "qsv" => GpuVendor.Intel, _ => null,
    };

    public static string Label(string enc) => Family(enc) switch
    {
        "nvenc" => "NVIDIA NVENC", "amf" => "AMD AMF", "qsv" => "Intel Quick Sync", "mf" => "Media Foundation (Windows)", _ => "CPU (x264)",
    } + (enc.StartsWith("hevc") ? " · HEVC" : enc.StartsWith("av1") ? " · AV1" : enc == "libx264" ? "" : " · H.264");

    // ---------------------------------------------------------------- detection

    static HwProfile Detect()
    {
        var adapters = Adapters();
        var real = adapters.Where(a => !a.Software && a.Vendor != GpuVendor.Microsoft).ToList();
        var forced = Environment.GetEnvironmentVariable("CLIPPER_ENCODER");

        // One H.264 candidate per vendor, best adapter first: dedicated before integrated, then by video memory.
        var candidates = real
            .OrderBy(a => a.Integrated).ThenBy(a => a.Vendor switch { GpuVendor.Nvidia => 0, GpuVendor.Amd => 1, GpuVendor.Intel => 2, _ => 3 }).ThenByDescending(a => a.DedicatedMb)
            .Select(a => a.Vendor switch { GpuVendor.Nvidia => "h264_nvenc", GpuVendor.Amd => "h264_amf", GpuVendor.Intel => "h264_qsv", _ => "" })
            .Where(e => e != "").Distinct().ToList();
        if (real.Count > 0) candidates.Add("h264_mf");
        candidates.Add("libx264");

        var working = candidates.Where(Works).ToList();
        string chosen = forced != null && Known.Contains(forced) && Works(forced) ? forced : working.FirstOrDefault() ?? "libx264";
        var adapter = AdapterFor(chosen, real);
        var hwaccel = DecodeArgs(chosen);
        string mode = Family(chosen) == "cpu" ? "cpu" : adapter?.Integrated == true ? "igpu" : "gpu";

        // Say why a card that is present is not being used: almost always an old driver.
        var notes = new List<string>();
        foreach (var vendor in real.Select(a => a.Vendor).Distinct())
        {
            var enc = vendor switch { GpuVendor.Nvidia => "h264_nvenc", GpuVendor.Amd => "h264_amf", GpuVendor.Intel => "h264_qsv", _ => null };
            if (enc != null && !working.Contains(enc))
                notes.Add($"Hay una GPU {VendorName(vendor)} pero su codificador ({Label(enc)}) no responde: actualiza el driver de {VendorName(vendor)}.");
        }
        bool forcedOk = forced != null && chosen == forced;
        if (forced != null) notes.Add(forcedOk ? $"Codificador fijado con CLIPPER_ENCODER={forced}." : $"CLIPPER_ENCODER={forced} no funciona en este equipo; se usa {chosen}.");
        if (real.Count == 0) notes.Add("No se detectó tarjeta gráfica: el render usa la CPU.");
        else if (mode == "cpu" && !forcedOk) notes.Add("Ningún codificador por hardware funcionó: el render usa la CPU.");
        return new HwProfile(adapters, working, chosen, adapter, hwaccel.Count > 0 ? string.Join(' ', hwaccel) : null, mode, string.Join(' ', notes));
    }

    static GpuAdapter? AdapterFor(string enc, List<GpuAdapter> real)
    {
        var vendor = VendorOf(enc);
        if (vendor != null) return real.Where(a => a.Vendor == vendor).OrderBy(a => a.Integrated).ThenByDescending(a => a.DedicatedMb).FirstOrDefault();
        return Family(enc) == "mf" ? real.FirstOrDefault(a => a.Index == 0) ?? real.FirstOrDefault() : null;   // MF uses the primary adapter
    }

    public static string VendorName(GpuVendor v) => v switch { GpuVendor.Nvidia => "NVIDIA", GpuVendor.Amd => "AMD", GpuVendor.Intel => "Intel", GpuVendor.Microsoft => "Microsoft", _ => "?" };

    /// <summary>Does this encoder produce frames here? Tested once per encoder; libx264 is assumed.</summary>
    public static bool Works(string enc) => enc == "libx264" || RecipeIndex(enc, false) >= 0;

    static int RecipeIndex(string enc, bool fast) => Recipe.GetOrAdd($"{enc}|{fast}", _ =>
    {
        var recipes = Recipes(enc, 23, fast);
        for (int i = 0; i < recipes.Count; i++)
        {
            var (code, err) = Ffmpeg(["-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x320:r=30:d=0.3", .. recipes[i], "-f", "null", "-"], 20_000);
            if (code == 0) return i;
            Debug.WriteLine($"{enc} recipe {i}: {err}");
        }
        return -1;
    });

    // ---------------------------------------------------------------- arguments

    /// <summary>Encoder arguments, richest recipe first; the first one the driver accepts is kept. q works like x264's CRF (lower = better).</summary>
    static List<List<string>> Recipes(string enc, int q, bool fast)
    {
        string Q(int d = 0) => Math.Clamp(q + d, 1, 51).ToString();
        long kbps = Math.Clamp(16000 - (q - 15) * 800, 4000, 16000);   // bitrate fallback for drivers that refuse constant quality
        List<string> rate = ["-b:v", $"{kbps}k", "-maxrate", $"{kbps * 3 / 2}k", "-bufsize", $"{kbps * 2}k"];
        List<string> head = ["-c:v", enc];
        return Family(enc) switch
        {
            "nvenc" => fast
                ? [[.. head, "-preset", "p1", "-rc", "vbr", "-cq", Q(), "-b:v", "0", "-pix_fmt", "yuv420p"], [.. head, "-preset", "p1", .. rate, "-pix_fmt", "yuv420p"]]
                : [
                    // p6 + two-pass rate control + adaptive quantisation: the "high quality" NVENC recipe; -cq with -b:v 0 is constant quality.
                    [.. head, "-preset", "p6", "-tune", "hq", "-multipass", "fullres", "-rc", "vbr", "-cq", Q(), "-b:v", "0", "-spatial-aq", "1", "-temporal-aq", "1", "-rc-lookahead", "24", "-pix_fmt", "yuv420p",
                     .. enc == "hevc_nvenc" ? new[] { "-tag:v", "hvc1" } : []],
                    [.. head, "-preset", "p5", "-rc", "vbr", "-cq", Q(), "-b:v", "0", "-pix_fmt", "yuv420p", .. enc == "hevc_nvenc" ? new[] { "-tag:v", "hvc1" } : []],
                    [.. head, .. rate, "-pix_fmt", "yuv420p"],
                ],
            // AMF: constant QP per frame type is the closest thing to CRF that every AMF generation accepts.
            "amf" => [
                [.. head, "-usage", "transcoding", "-quality", fast ? "speed" : "quality", "-rc", "cqp", "-qp_i", Q(-1), "-qp_p", Q(1), "-pix_fmt", "nv12", .. enc == "hevc_amf" ? new[] { "-tag:v", "hvc1" } : []],
                [.. head, "-quality", fast ? "speed" : "balanced", .. rate, "-pix_fmt", "nv12"],
                [.. head, .. rate, "-pix_fmt", "nv12"],
            ],
            // Quick Sync: ICQ (global_quality without a bitrate) on recent Intel graphics, bitrate on older ones.
            "qsv" => [
                [.. head, "-preset", fast ? "veryfast" : "slow", "-global_quality", Q(), "-look_ahead_depth", fast ? "0" : "20", "-pix_fmt", "nv12", .. enc == "hevc_qsv" ? new[] { "-tag:v", "hvc1" } : []],
                [.. head, "-preset", fast ? "veryfast" : "medium", "-global_quality", Q(), "-pix_fmt", "nv12"],
                [.. head, .. rate, "-pix_fmt", "nv12"],
            ],
            // Media Foundation: Windows picks the hardware encoder of whatever driver is installed (integrated graphics included).
            "mf" => [
                [.. head, "-hw_encoding", "1", "-rate_control", "quality", "-quality", Math.Clamp(100 - (q - 10) * 4, 30, 95).ToString(), "-pix_fmt", "nv12"],
                [.. head, "-hw_encoding", "1", .. rate, "-pix_fmt", "nv12"],
            ],
            _ => [["-c:v", "libx264", "-preset", fast ? "ultrafast" : "veryfast", "-crf", Q(), "-pix_fmt", "yuv420p"]],
        };
    }

    /// <summary>The arguments to encode with <paramref name="enc"/> at quality <paramref name="q"/> (CRF scale).</summary>
    public static List<string> EncoderArgs(string enc, int q, bool fast = false)
    {
        if (enc == "libx264") return Recipes(enc, q, fast)[0];
        int i = fast ? RecipeIndex(enc, true) : -1;
        if (i >= 0) return Recipes(enc, q, true)[i];
        i = RecipeIndex(enc, false);   // no fast recipe works: the quality one still beats the CPU
        return i >= 0 ? Recipes(enc, q, false)[i] : Recipes("libx264", q, fast)[0];
    }

    /// <summary>The encoder to try first, then the other working hardware encoders, then the CPU.</summary>
    public static List<string> Chain(string enc)
    {
        if (enc == "libx264") return ["libx264"];   // CPU was chosen on purpose: never move to a card behind the user's back
        var chain = new List<string>();
        if (Works(enc)) chain.Add(enc);
        chain.AddRange(Profile.Working.Where(e => e != enc && e != "libx264"));
        chain.Add("libx264");
        return chain.Distinct().ToList();
    }

    /// <summary>Hardware decode for the encoder's card, verified on a real H.264 file; [] means decode on the CPU.
    /// Frames come back to system memory, so the CPU filters (text, colour, zoom) work the same on every path.</summary>
    public static List<string> DecodeArgs(string enc)
    {
        var family = Family(enc);
        if (family == "cpu") return [];
        return Decode.GetOrAdd(family, _ =>
        {
            var real = Adapters().Where(a => !a.Software && a.Vendor != GpuVendor.Microsoft).ToList();
            var adapter = AdapterFor(enc, real);
            var tries = new List<List<string>>();
            if (family == "nvenc") tries.Add(["-hwaccel", "cuda"]);
            if (adapter != null) tries.Add(["-hwaccel", "d3d11va", "-hwaccel_device", adapter.Index.ToString()]);
            tries.Add(["-hwaccel", "d3d11va"]);
            var sample = Sample();
            if (sample == null) return null;
            foreach (var t in tries)
            {
                var (code, err) = Ffmpeg(["-hide_banner", "-v", "error", .. t, "-i", sample, "-f", "null", "-"], 20_000);
                if (code == 0 && err.Trim() == "") return t;   // with -v error, any line means the decoder fell back or failed
            }
            return null;
        }) ?? [];
    }

    static string? _sample;
    static string? Sample()
    {
        if (_sample != null && File.Exists(_sample)) return _sample;
        var path = Path.Combine(Path.GetTempPath(), "clipper-hwtest.mp4");
        var (code, _) = Ffmpeg(["-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path], 20_000);
        return _sample = code == 0 ? path : null;
    }

    static (int code, string err) Ffmpeg(IEnumerable<string> args, int timeoutMs)
    {
        try
        {
            var psi = new ProcessStartInfo(Paths.Tool("ffmpeg")) { RedirectStandardError = true, RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true, StandardErrorEncoding = Encoding.UTF8 };
            foreach (var a in args) psi.ArgumentList.Add(a);
            using var p = Process.Start(psi)!;
            var err = p.StandardError.ReadToEndAsync();
            p.StandardOutput.ReadToEndAsync();
            if (!p.WaitForExit(timeoutMs)) { try { p.Kill(true); } catch { } return (-1, "timeout"); }   // a hung driver must not freeze the app
            return (p.ExitCode, err.Result);
        }
        catch (Exception e) { return (-1, e.Message); }
    }

    // ---------------------------------------------------------------- transcription backend

    /// <summary>whisper.cpp build for this PC. Its Windows releases ship CUDA and CPU builds only (no Vulkan/ROCm),
    /// so AMD and Intel get the OpenBLAS CPU build, which is the fastest option there.</summary>
    public static (string Asset, string Label, bool Gpu) WhisperBuild()
    {
        bool nvidia = Profile.Adapters.Any(a => a.Vendor == GpuVendor.Nvidia && !a.Integrated) && Works("h264_nvenc");   // NVENC answering means the driver is loaded
        return nvidia ? ("whisper-cublas-12.4.0-bin-x64.zip", "GPU NVIDIA (CUDA)", true) : ("whisper-blas-bin-x64.zip", "CPU optimizada (OpenBLAS)", false);
    }

    // ---------------------------------------------------------------- status for the interface

    static GpuAdapter? Selected(string device) => int.TryParse(device.Replace("dxgi:", ""), out var index) ? Adapters().FirstOrDefault(a => a.Index == index && !a.Software) : null;
    public static List<string> DeviceInit(string device, string enc)
    {
        var a = Selected(device);
        if (a == null || VendorOf(enc) != a.Vendor || Family(enc) == "nvenc") return [];
        if (Family(enc) == "amf") return ["-init_hw_device", $"d3d11va=clipper:{a.Index}", "-filter_hw_device", "clipper"];
        if (Family(enc) == "qsv") return ["-init_hw_device", $"d3d11va=clipper:{a.Index}", "-init_hw_device", "qsv=qs@clipper", "-filter_hw_device", "qs"];
        return [];
    }
    public static List<string> DeviceOutput(string device, string enc)
    {
        var a = Selected(device);
        return a?.Vendor == GpuVendor.Nvidia && Family(enc) == "nvenc" ? ["-gpu", Adapters().Where(x => x.Vendor == GpuVendor.Nvidia && !x.Software).ToList().FindIndex(x => x.Index == a.Index).ToString()] : [];
    }
    static readonly ConcurrentDictionary<string, string> Devices = new();
    public static string DeviceEncoder(string device) => Devices.GetOrAdd(device, key =>
    {
        var a = Selected(key);
        var enc = a?.Vendor switch { GpuVendor.Nvidia => "h264_nvenc", GpuVendor.Amd => "h264_amf", GpuVendor.Intel => "h264_qsv", _ => "libx264" };
        if (enc == "libx264" || !Works(enc)) return "libx264";
        var (code, _) = Ffmpeg(["-hide_banner", "-v", "error", .. DeviceInit(key, enc), "-f", "lavfi", "-i", "color=s=320x320:r=30:d=0.3", .. EncoderArgs(enc, 23), .. DeviceOutput(key, enc), "-f", "null", "-"], 20_000);
        return code == 0 ? enc : "libx264";
    });
    public static JsonArray DeviceList() => new(Adapters().Where(a => !a.Software).Select(a => (JsonNode)new JsonObject
    {
        ["id"] = $"dxgi:{a.Index}", ["name"] = a.Name, ["kind"] = a.Kind,
        ["encoder"] = DeviceEncoder($"dxgi:{a.Index}"), ["available"] = DeviceEncoder($"dxgi:{a.Index}") != "libx264",
    }).ToArray());

    public static JsonObject Json()
    {
        var p = Profile;
        return new JsonObject
        {
            ["name"] = p.Device, ["vendor"] = p.Adapter == null ? "none" : VendorName(p.Adapter.Vendor).ToLowerInvariant(),
            ["mode"] = p.Mode, ["hardware"] = p.Hardware, ["encoder"] = p.Encoder, ["encoder_label"] = Label(p.Encoder),
            ["nvenc"] = Family(p.Encoder) == "nvenc", ["decode"] = p.Hwaccel, ["note"] = p.Note,
            ["encoders"] = new JsonArray(p.Working.Select(e => (JsonNode)new JsonObject { ["id"] = e, ["label"] = Label(e) }).ToArray()),
            ["adapters"] = new JsonArray(p.Adapters.Select(a => (JsonNode)new JsonObject
            {
                ["name"] = a.Name, ["vendor"] = VendorName(a.Vendor).ToLowerInvariant(), ["kind"] = a.Kind,
                ["vram_mb"] = a.DedicatedMb, ["shared_mb"] = a.SharedMb, ["driver"] = a.Driver,
            }).ToArray()),
        };
    }

    // ---------------------------------------------------------------- adapters

    static List<GpuAdapter>? _adapters;

    /// <summary>Graphics adapters in DXGI order (index 0 drives the main display). Falls back to the registry.</summary>
    public static List<GpuAdapter> Adapters()
    {
        if (_adapters != null) return _adapters;
        List<GpuAdapter> list;
        try { list = Dxgi.Enumerate(); } catch { list = []; }
        if (list.Count == 0) try { list = FromRegistry(); } catch { list = []; }
        return _adapters = list;
    }

    internal static GpuVendor VendorFromId(uint id) => id switch
    {
        0x10DE => GpuVendor.Nvidia, 0x1002 or 0x1022 => GpuVendor.Amd, 0x8086 => GpuVendor.Intel, 0x1414 => GpuVendor.Microsoft, _ => GpuVendor.Other,
    };

    /// <summary>Integrated graphics share system memory: Intel without "Arc", AMD APUs ("Radeon(TM) Graphics", 680M/780M/…), or a tiny carve-out.</summary>
    internal static bool LooksIntegrated(GpuVendor v, string name, long dedicatedMb) => v switch
    {
        GpuVendor.Intel => !name.Contains("Arc", StringComparison.OrdinalIgnoreCase) || dedicatedMb < 2048,   // "Arc(TM) Graphics" in Core Ultra is integrated
        GpuVendor.Amd => Regex.IsMatch(name, @"Radeon\(TM\) Graphics|Radeon Graphics|Vega \d+ Graphics|\b(610M|660M|680M|740M|760M|780M|880M|890M|8060S|8050S)\b", RegexOptions.IgnoreCase) || dedicatedMb < 1024,
        GpuVendor.Nvidia => false,
        _ => dedicatedMb < 1024,
    };

    /// <summary>Driver version from the display class key. NVIDIA's 32.0.15.6094 is shown as 560.94, like the NVIDIA app.</summary>
    internal static string DriverVersion(uint vendor, uint device)
    {
        try
        {
            using var cls = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}");
            if (cls == null) return "";
            var id = $"ven_{vendor:x4}&dev_{device:x4}";
            foreach (var sub in cls.GetSubKeyNames().Where(n => Regex.IsMatch(n, @"^\d{4}$")))
            {
                using var k = cls.OpenSubKey(sub);
                if ((k?.GetValue("MatchingDeviceId") as string)?.Contains(id, StringComparison.OrdinalIgnoreCase) != true) continue;
                var ver = k!.GetValue("DriverVersion") as string ?? "";
                if (vendor == 0x10DE)
                {
                    var digits = string.Concat(ver.Split('.').TakeLast(2));
                    if (digits.Length >= 5) return $"{digits[^5..^2]}.{digits[^2..]}";
                }
                return ver;
            }
        }
        catch { }
        return "";
    }

    static List<GpuAdapter> FromRegistry()
    {
        var list = new List<GpuAdapter>();
        using var cls = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}");
        if (cls == null) return list;
        foreach (var sub in cls.GetSubKeyNames().Where(n => Regex.IsMatch(n, @"^\d{4}$")))
        {
            try
            {
                using var k = cls.OpenSubKey(sub);
                var match = Regex.Match(k?.GetValue("MatchingDeviceId") as string ?? "", @"ven_([0-9a-f]{4})&dev_([0-9a-f]{4})", RegexOptions.IgnoreCase);
                if (k == null || !match.Success) continue;
                uint ven = Convert.ToUInt32(match.Groups[1].Value, 16), dev = Convert.ToUInt32(match.Groups[2].Value, 16);
                var name = k.GetValue("DriverDesc") as string ?? "GPU";
                long mem = k.GetValue("HardwareInformation.qwMemorySize") switch
                {
                    long l => l, byte[] b when b.Length >= 8 => BitConverter.ToInt64(b), byte[] b when b.Length >= 4 => BitConverter.ToUInt32(b), int i => (uint)i, _ => 0,
                };
                var v = VendorFromId(ven);
                list.Add(new GpuAdapter(list.Count, name, v, ven, dev, mem >> 20, 0, LooksIntegrated(v, name, mem >> 20), v == GpuVendor.Microsoft, DriverVersion(ven, dev)));
            }
            catch { }
        }
        return list;
    }

    /// <summary>DXGI enumeration through COM interop: no extra package, works for every vendor's WDDM driver.</summary>
    static class Dxgi
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct AdapterDesc1
        {
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Description;
            public uint VendorId, DeviceId, SubSysId, Revision;
            public nuint DedicatedVideoMemory, DedicatedSystemMemory, SharedSystemMemory;
            public uint LuidLow; public int LuidHigh; public uint Flags;
        }

        // Slots are declared in vtable order; only EnumAdapters1 and GetDesc1 are called.
        [ComImport, Guid("770aae78-f26f-4dba-a829-253c83d1b387"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IFactory1
        {
            void SetPrivateData(); void SetPrivateDataInterface(); void GetPrivateData(); void GetParent();
            void EnumAdapters(); void MakeWindowAssociation(); void GetWindowAssociation(); void CreateSwapChain(); void CreateSoftwareAdapter();
            [PreserveSig] int EnumAdapters1(uint index, out IAdapter1 adapter);
        }

        [ComImport, Guid("29038f61-3839-4626-91fd-086879011a05"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IAdapter1
        {
            void SetPrivateData(); void SetPrivateDataInterface(); void GetPrivateData(); void GetParent();
            void EnumOutputs(); void GetDesc(); void CheckInterfaceSupport();
            [PreserveSig] int GetDesc1(out AdapterDesc1 desc);
        }

        [DllImport("dxgi.dll")]
        static extern int CreateDXGIFactory1(ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out IFactory1 factory);

        public static List<GpuAdapter> Enumerate()
        {
            var list = new List<GpuAdapter>();
            var iid = typeof(IFactory1).GUID;
            if (CreateDXGIFactory1(ref iid, out var factory) < 0) return list;
            try
            {
                for (uint i = 0; i < 16; i++)
                {
                    if (factory.EnumAdapters1(i, out var adapter) < 0) break;   // DXGI_ERROR_NOT_FOUND ends the list
                    try
                    {
                        if (adapter.GetDesc1(out var d) < 0) continue;
                        var v = VendorFromId(d.VendorId);
                        long ded = (long)(d.DedicatedVideoMemory >> 20), shared = (long)(d.SharedSystemMemory >> 20);
                        bool software = (d.Flags & 2) != 0 || v == GpuVendor.Microsoft;   // DXGI_ADAPTER_FLAG_SOFTWARE, Basic Render Driver
                        list.Add(new GpuAdapter((int)i, d.Description.Trim(), v, d.VendorId, d.DeviceId, ded, shared, !software && LooksIntegrated(v, d.Description, ded), software, software ? "" : DriverVersion(d.VendorId, d.DeviceId)));
                    }
                    finally { Marshal.ReleaseComObject(adapter); }
                }
            }
            finally { Marshal.ReleaseComObject(factory); }
            return list;
        }
    }
}
