// FFmpeg and yt-dlp: where they are, and a one-click installer for people who do not have them.
using System.IO.Compression;
using System.Net.Http;
using System.Text.Json.Nodes;
using ClipperStudio.Ai;

namespace ClipperStudio.Engine;

public static class Tools
{
    const string FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip";
    const string YtDlpUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe";
    public static string InstallDir => Paths.Dir("tools");

    public static JsonObject Status()
    {
        string? version = null;
        bool ffmpeg = false;
        try
        {
            var (code, stdout, _) = Ff.Exec("ffmpeg", ["-hide_banner", "-version"]);
            ffmpeg = code == 0;
            version = stdout.Split('\n')[0].Trim();
        }
        catch { }
        bool ytdlp = Paths.Tool("yt-dlp").EndsWith(".exe") || OnPath("yt-dlp");
        return new JsonObject
        {
            ["ffmpeg"] = new JsonObject { ["ok"] = ffmpeg, ["version"] = version },
            ["ytdlp"] = new JsonObject { ["ok"] = ytdlp },
            ["whisper"] = new JsonObject { ["ok"] = Whisper.Ready, ["engine"] = Whisper.Cli != null, ["model"] = File.Exists(Whisper.ModelPath), ["backend"] = Whisper.Backend, ["recommended"] = Hw.WhisperBuild().Label },
            ["gpu"] = Hw.Json(),
            ["dir"] = InstallDir,
        };
    }

    const string WhisperRelease = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.7.6/";

    /// <summary>whisper.cpp for this PC: the CUDA build with a working NVIDIA card, the OpenBLAS CPU build otherwise
    /// (AMD, Intel, integrated graphics). Each build is checked on a second of silence; if it does not run, the
    /// next one is installed, ending with the plain CPU build that needs nothing else.</summary>
    public static async Task InstallWhisperAsync(Action<string> log)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromMinutes(20) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("ClipperStudio");
        if (!File.Exists(Whisper.ModelPath))
        {
            log("Descargando el modelo multilingüe small cuantizado…");
            await Download(http, "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/" + Whisper.ModelFile, Whisper.ModelPath, log);
        }
        if (Whisper.Cli != null && Whisper.Check()) { log($"Transcripción lista ({Whisper.Backend})."); return; }

        var best = Hw.WhisperBuild();
        var builds = new List<(string asset, string label)> { (best.Asset, best.Label) };
        if (best.Gpu) builds.Add(("whisper-blas-bin-x64.zip", "CPU optimizada (OpenBLAS)"));
        builds.Add(("whisper-bin-x64.zip", "CPU"));
        var dir = Path.Combine(InstallDir, "whisper");
        foreach (var (asset, label) in builds)
        {
            log($"Descargando whisper.cpp · {label}…");
            var zip = Path.Combine(InstallDir, "whisper.zip");
            try
            {
                await Download(http, WhisperRelease + asset, zip, log);
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
                ZipFile.ExtractToDirectory(zip, dir, true);
            }
            catch (Exception e) when (e is HttpRequestException or IOException or InvalidDataException) { log($"  no se pudo descargar: {e.Message}"); continue; }
            finally { File.Delete(zip); }
            if (Whisper.Check()) { log($"Transcripción instalada ({Whisper.Backend}). Ya puedes procesar videos con Claude."); return; }
            log($"  la compilación {label} no arranca en este equipo; se prueba la siguiente.");
        }
        throw new FfmpegException("No se pudo instalar un motor de transcripción que arranque en este equipo.");
    }

    static bool OnPath(string exe) => (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';').Any(d => d != "" && File.Exists(Path.Combine(d, exe + ".exe")));

    /// <summary>Download and unpack both tools into the user's data folder (no admin rights needed).</summary>
    public static async Task InstallAsync(Action<string> log)
    {
        var dir = InstallDir;
        using var http = new HttpClient { Timeout = TimeSpan.FromMinutes(20) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("ClipperStudio");
        var zip = Path.Combine(Path.GetTempPath(), "kairos-ffmpeg-"+Guid.NewGuid().ToString("N")+".zip");
        log("Descargando FFmpeg (compilación con NVENC y libass)…");
        await Download(http, FfmpegUrl, zip, log);
        log("Extrayendo…");
        using (var archive = ZipFile.OpenRead(zip))
            foreach (var entry in archive.Entries.Where(e => e.FullName.Contains("/bin/") && (e.Name is "ffmpeg.exe" or "ffprobe.exe")))
                entry.ExtractToFile(Path.Combine(dir, entry.Name), true);
        File.Delete(zip);
        log("Descargando yt-dlp…");
        await Download(http, YtDlpUrl, Path.Combine(dir, "yt-dlp.exe"), log);
        Ff.Reset();
        var s = Status();
        if (!J.B(s["ffmpeg"]!["ok"])) throw new FfmpegException("FFmpeg se descargó pero no arranca. Puede que un antivirus lo haya bloqueado.");
        log($"Listo: {J.S(s["ffmpeg"]!["version"])}");
        var hw = Hw.Profile;
        log(hw.Hardware ? $"Render por {(hw.Mode == "igpu" ? "gráfica integrada" : "GPU")}: {Hw.Label(hw.Encoder)} en {hw.Device}." : "El render usará la CPU (libx264).");
        if (hw.Note != "") log(hw.Note);
    }

    static async Task Download(HttpClient http, string url, string path, Action<string> log)
    {
        using var res = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead);
        res.EnsureSuccessStatusCode();
        long total = res.Content.Headers.ContentLength ?? 0, done = 0, lastLogged = 0;
        var tmp = path + "." + Guid.NewGuid().ToString("N") + ".part";
        await using (var src = await res.Content.ReadAsStreamAsync())
        await using (var dst = File.Create(tmp))
        {
            var buf = new byte[1 << 17];
            int n;
            while ((n = await src.ReadAsync(buf)) > 0)
            {
                await dst.WriteAsync(buf.AsMemory(0, n));
                done += n;
                if (done - lastLogged >= 15 << 20) { lastLogged = done; log($"  {done / 1048576} MB{(total > 0 ? $" de {total / 1048576} MB" : "")}"); }
            }
        }
        File.Move(tmp, path, true);
    }
}
